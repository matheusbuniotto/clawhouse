"""Lakeflow Jobs creation, edition, execution, and monitoring."""

from __future__ import annotations

import itertools
import logging
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.jobs import (
    JobSettings,
    SparkPythonTask,
    Task,
)

from clawhouse.capabilities.databricks.cron_util import build_cron_schedule
from clawhouse.capabilities.databricks.jobs_tasks import (
    _apply_job_settings,
    _build_sql_task,
    _prepare_edit_settings,
    _update_job_sql_file,
    jobs_get_run_output,
    jobs_wait_run,
)
from clawhouse.capabilities.databricks.python_analysis import _enum_value

if TYPE_CHECKING:
    from clawhouse.capabilities.databricks.tools import DatabricksTools
    from clawhouse.settings import Settings

logger = logging.getLogger("clawhouse.databricks")

_JOBS_PAGE_MAX = 100
_TASK_KEY_UNSAFE = re.compile(r"[^A-Za-z0-9_-]+")

__all__ = [
    "JobsIdentity",
    "MissingJobsIdentityError",
    "jobs_cancel_run",
    "jobs_create",
    "jobs_delete",
    "jobs_edit",
    "jobs_get_run",
    "jobs_get_run_output",
    "jobs_identity",
    "jobs_list",
    "jobs_run_now",
    "jobs_wait_run",
]


@dataclass(frozen=True, slots=True)
class JobsIdentity:
    kind: Literal["service_principal", "user_obo"]
    client: WorkspaceClient
    label: str


class MissingJobsIdentityError(RuntimeError):
    """Raised when neither a dedicated service principal nor a user token is available."""


def _workspace_client_cls() -> type[WorkspaceClient]:
    mod = sys.modules.get("clawhouse.capabilities.databricks")
    if mod and hasattr(mod, "WorkspaceClient"):
        return mod.WorkspaceClient
    return WorkspaceClient


def jobs_identity(
    settings: Settings | None = None,
    user_token: str = "",
    *,
    client_factory: Callable[..., WorkspaceClient] | None = None,
) -> JobsIdentity:
    """Resolve acting identity for Lakeflow Jobs execution."""
    factory = client_factory or _workspace_client_cls()
    if settings is not None and settings.jobs_sp_client_id and settings.jobs_sp_client_secret:
        sp_id = settings.jobs_sp_client_id
        sp_secret = settings.jobs_sp_client_secret
        kwargs: dict[str, Any] = {
            "client_id": sp_id,
            "client_secret": sp_secret,
            "auth_type": "oauth-m2m",
        }
        if settings.workspace_host:
            kwargs["host"] = settings.workspace_host
        client = factory(**kwargs)
        return JobsIdentity(kind="service_principal", client=client, label=sp_id)

    token = user_token.strip() if user_token else ""
    if token:
        kwargs = {"token": token, "auth_type": "pat"}
        if settings is not None and settings.workspace_host:
            kwargs["host"] = settings.workspace_host
        client = factory(**kwargs)
        return JobsIdentity(kind="user_obo", client=client, label="user")

    raise MissingJobsIdentityError(
        "No jobs execution identity configured: "
        "neither dedicated Service Principal nor user token is available"
    )


async def jobs_list(tools: DatabricksTools, limit: int = 25) -> dict[str, object]:
    """List Lakeflow jobs in the workspace."""
    limit = max(1, min(limit, _JOBS_PAGE_MAX))
    try:
        jobs = tools._call(lambda cl: list(itertools.islice(cl.jobs.list(limit=limit), limit)))
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Failed to list jobs: {exc}"}
    return {
        "jobs": [
            {
                "job_id": job.job_id,
                "name": job.settings.name if job.settings else None,
                "creator": job.creator_user_name,
            }
            for job in jobs
        ],
        "job_count": len(jobs),
    }


async def jobs_run_now(
    tools: DatabricksTools,
    job_id: int,
    parameters: dict[str, str] | None = None,
    *,
    wait: bool = False,
    timeout_seconds: int = 120,
) -> dict[str, object]:
    """Trigger an immediate run of a Lakeflow job, optionally overriding job parameters."""
    try:
        identity = tools._resolve_jobs_identity()
    except MissingJobsIdentityError as exc:
        return {"error": str(exc)}

    try:
        wait_handle = identity.client.jobs.run_now(job_id=job_id, job_parameters=parameters)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Failed to run job {job_id}: {exc}"}
    identity_meta = {"kind": identity.kind, "label": identity.label}
    if wait:
        res = await jobs_wait_run(tools, wait_handle.run_id, timeout_seconds=timeout_seconds)
        if "error" not in res:
            res["identity"] = identity_meta
        return res
    return {"run_id": wait_handle.run_id, "job_id": job_id, "identity": identity_meta}


def _build_create_task(  # noqa: PLR0913
    tools: DatabricksTools,
    name: str,
    task_type: Literal["python", "sql", "agentic"],
    path: str,
    *,
    parameters: list[str] | None,
    warehouse_id: str | None,
    query: str | None,
    agent_name: str | None,
    instructions: str | None,
    client: WorkspaceClient,
) -> tuple[Task | None, str | None, str | None]:
    task_key = _TASK_KEY_UNSAFE.sub("_", name)
    effective_agent = agent_name or (name if task_type == "agentic" else None)
    if task_type == "python":
        task = Task(
            task_key=task_key,
            spark_python_task=SparkPythonTask(python_file=path, parameters=parameters),
        )
        return task, effective_agent, None
    task, error = _build_sql_task(
        tools,
        task_key,
        path,
        query=query,
        warehouse_id=warehouse_id,
        agent_name=effective_agent,
        instructions=instructions,
        client=client,
    )
    if error or task is None:
        return None, effective_agent, error or "Failed to build SQL task."
    return task, effective_agent, None


def _format_created_job(  # noqa: PLR0913
    job_id: int,
    name: str,
    identity: JobsIdentity,
    task_type: str,
    *,
    effective_agent: str | None,
    scheduled: bool,
) -> dict[str, object]:
    result: dict[str, object] = {
        "job_id": job_id,
        "name": name,
        "identity": {"kind": identity.kind, "label": identity.label},
    }
    if task_type == "agentic" or effective_agent:
        result["task_type"] = task_type
        result["agent_name"] = effective_agent
    if scheduled:
        result["scheduled"] = True
    return result


def _submit_created_job(
    identity: JobsIdentity, name: str, task: Task, schedule: Any
) -> tuple[int | None, str | None]:
    kwargs: dict[str, Any] = {"name": name, "tasks": [task]}
    if schedule is not None:
        kwargs["schedule"] = schedule
    try:
        created = identity.client.jobs.create(**kwargs)
    except Exception as exc:  # noqa: BLE001
        return None, f"Failed to create job {name}: {exc}"
    else:
        return created.job_id, None


async def jobs_create(  # noqa: PLR0913
    tools: DatabricksTools,
    name: str,
    task_type: Literal["python", "sql", "agentic"] = "sql",
    path: str = "",
    *,
    parameters: list[str] | None = None,
    warehouse_id: str | None = None,
    query: str | None = None,
    agent_name: str | None = None,
    instructions: str | None = None,
    cron_expression: str | None = None,
    timezone_id: str = "UTC",
    pause_status: Literal["PAUSED", "UNPAUSED"] = "UNPAUSED",
) -> dict[str, object]:
    """Create a single-task Lakeflow job running SQL, Python, or an Agentic query."""
    try:
        identity = tools._resolve_jobs_identity()
    except MissingJobsIdentityError as exc:
        return {"error": str(exc)}

    task, agent, error = _build_create_task(
        tools,
        name,
        task_type,
        path,
        parameters=parameters,
        warehouse_id=warehouse_id,
        query=query,
        agent_name=agent_name,
        instructions=instructions,
        client=identity.client,
    )
    if error or task is None:
        return {"error": error or "Failed to build SQL task."}

    schedule = build_cron_schedule(cron_expression, timezone_id, pause_status)
    job_id, err = _submit_created_job(identity, name, task, schedule)
    if err or job_id is None:
        return {"error": err or "Failed to create job."}

    return _format_created_job(
        job_id,
        name,
        identity,
        task_type,
        effective_agent=agent,
        scheduled=bool(schedule),
    )


async def jobs_edit(  # noqa: PLR0913
    tools: DatabricksTools,
    job_id: int,
    new_settings: dict[str, Any] | None = None,
    *,
    name: str | None = None,
    cron_expression: str | None = None,
    timezone_id: str = "UTC",
    pause_status: Literal["PAUSED", "UNPAUSED"] | None = None,
    query: str | None = None,
    agent_name: str | None = None,
    instructions: str | None = None,
) -> dict[str, object]:
    """Update a Lakeflow job settings, schedule, or query."""
    try:
        identity = tools._resolve_jobs_identity()
    except MissingJobsIdentityError as exc:
        return {"error": str(exc)}

    if query:
        err = _update_job_sql_file(
            tools,
            job_id,
            query,
            agent_name=agent_name,
            instructions=instructions,
            client=identity.client,
        )
        if err:
            return {"error": err}

    settings_dict = _prepare_edit_settings(
        new_settings,
        name=name,
        cron_expression=cron_expression,
        timezone_id=timezone_id,
        pause_status=pause_status,
    )
    identity_meta = {"kind": identity.kind, "label": identity.label}
    if not settings_dict and not query:
        msg = "No settings to update"
        return {"job_id": job_id, "updated": False, "message": msg, "identity": identity_meta}

    if settings_dict:
        err = _apply_job_settings(identity.client, job_id, JobSettings.from_dict(settings_dict))
        if err:
            return {"error": err}
    return {"job_id": job_id, "updated": True, "identity": identity_meta}


async def jobs_delete(tools: DatabricksTools, job_id: int) -> dict[str, object]:
    """Delete a Lakeflow job from the workspace."""
    try:
        identity = tools._resolve_jobs_identity()
    except MissingJobsIdentityError as exc:
        return {"error": str(exc)}

    try:
        identity.client.jobs.delete(job_id=job_id)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Failed to delete job {job_id}: {exc}"}
    return {"job_id": job_id, "deleted": True}


async def jobs_cancel_run(tools: DatabricksTools, run_id: int) -> dict[str, object]:
    """Request cancellation of an active Lakeflow job run."""
    try:
        identity = tools._resolve_jobs_identity()
    except MissingJobsIdentityError as exc:
        return {"error": str(exc)}

    try:
        identity.client.jobs.cancel_run(run_id=run_id)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Failed to cancel run {run_id}: {exc}"}
    return {
        "run_id": run_id,
        "cancel_requested": True,
        "identity": {"kind": identity.kind, "label": identity.label},
    }


def _task_run_dict(task: Any) -> dict[str, object]:
    state = getattr(task, "state", None)
    return {
        "task_key": getattr(task, "task_key", None),
        "run_id": getattr(task, "run_id", None),
        "life_cycle_state": _enum_value(getattr(state, "life_cycle_state", None)),
        "result_state": _enum_value(getattr(state, "result_state", None)),
    }


def _run_duration(run: Any) -> int | None:
    if run.start_time and run.end_time:
        return run.end_time - run.start_time
    return None


async def jobs_get_run(tools: DatabricksTools, run_id: int) -> dict[str, object]:
    """Get the state of a Lakeflow job run."""
    try:
        run = tools._call(lambda cl: cl.jobs.get_run(run_id=run_id))
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Failed to get run {run_id}: {exc}"}
    state = getattr(run, "state", None)
    return {
        "run_id": run.run_id,
        "job_id": run.job_id,
        "life_cycle_state": _enum_value(getattr(state, "life_cycle_state", None)),
        "result_state": _enum_value(getattr(state, "result_state", None)),
        "state_message": getattr(state, "state_message", None),
        "duration_ms": _run_duration(run),
        "url": run.run_page_url,
        "tasks": [_task_run_dict(task) for task in getattr(run, "tasks", None) or []],
    }
