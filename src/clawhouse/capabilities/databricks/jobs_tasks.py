"""Lakeflow Jobs task construction, workspace uploads, output aggregation, and run waiting."""

from __future__ import annotations

import asyncio
import io
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import PermissionDenied
from databricks.sdk.service.jobs import (
    RunTask,
    Source,
    SqlTask,
    SqlTaskFile,
    Task,
)
from databricks.sdk.service.workspace import ImportFormat

from clawhouse.capabilities.databricks.catalog import _estate_closed, _hidden_or_error
from clawhouse.capabilities.databricks.cron_util import build_cron_schedule
from clawhouse.capabilities.databricks.python_analysis import _enum_value
from clawhouse.capabilities.databricks.sql_util import build_agentic_query

if TYPE_CHECKING:
    from clawhouse.capabilities.databricks.tools import DatabricksTools

logger = logging.getLogger("clawhouse.databricks")


def _failed_tasks(tasks: list[Any]) -> list[dict[str, object]]:
    failed = []
    for task in tasks:
        task_state = task.state
        task_result = _enum_value(task_state.result_state if task_state else None)
        if task_result != "FAILED":
            continue
        failed.append(
            {
                "task_key": task.task_key,
                "result_state": task_result,
                "state_message": task_state.state_message if task_state else None,
            }
        )
    return failed


def _run_failure_payload(run: Any) -> dict[str, object]:
    state = run.state
    life_cycle = _enum_value(state.life_cycle_state if state else None)
    result_state = _enum_value(state.result_state if state else None)
    if life_cycle == "RUNNING" and result_state == "FAILED":
        result_state = None
    duration = run.end_time - run.start_time if run.start_time and run.end_time else None
    return {
        "run_id": run.run_id,
        "life_cycle_state": life_cycle,
        "result_state": result_state,
        "state_message": state.state_message if state else None,
        "duration_ms": duration,
        "run_page_url": run.run_page_url,
        "failed_tasks": _failed_tasks(run.tasks or []),
    }


def _upload_workspace_file(client: WorkspaceClient, path: str, content: bytes) -> None:
    parent_dir = str(Path(path).parent)
    try:
        client.workspace.mkdirs(parent_dir)
    except Exception as exc:  # noqa: BLE001
        logger.debug("mkdirs %s: %s", parent_dir, exc)
    client.workspace.upload(
        path=path,
        content=io.BytesIO(content),
        overwrite=True,
        format=ImportFormat.AUTO,
    )


def _save_workspace_sql_file(
    tools: DatabricksTools,
    path: str,
    sql_text: str,
    *,
    client: WorkspaceClient | None = None,
) -> None:
    content = sql_text.encode("utf-8")
    target_client = client or tools.client
    try:
        _upload_workspace_file(target_client, path, content)
    except Exception as exc:
        if client is None:
            fallback = tools._fallback_client()
            if fallback is not None and fallback is not target_client:
                try:
                    _upload_workspace_file(fallback, path, content)
                except Exception as fb_exc:  # noqa: BLE001
                    raise RuntimeError(
                        f"Failed to upload workspace SQL file to {path}: {fb_exc}"
                    ) from exc
                else:
                    return
        raise RuntimeError(f"Failed to upload workspace SQL file to {path}: {exc}") from exc


def _build_sql_task(  # noqa: PLR0913
    tools: DatabricksTools,
    task_key: str,
    path: str,
    *,
    query: str | None,
    warehouse_id: str | None,
    agent_name: str | None = None,
    instructions: str | None = None,
    client: WorkspaceClient | None = None,
) -> tuple[Task | None, str | None]:
    sql_warehouse = warehouse_id or tools.effective_warehouse_id
    if not sql_warehouse:
        return None, "A SQL job needs a SQL warehouse; none is available."
    effective_path = path
    sql_text = query or (
        path if path and not path.endswith(".sql") and "select" in path.lower() else None
    )
    if sql_text and agent_name:
        sql_text = build_agentic_query(
            query=sql_text,
            agent_name=agent_name,
            instructions=instructions,
        )
    if sql_text:
        if not effective_path or sql_text == effective_path or agent_name:
            effective_path = f"/Workspace/Shared/clawhouse/{task_key}.sql"
        try:
            _save_workspace_sql_file(tools, effective_path, sql_text, client=client)
        except Exception as exc:  # noqa: BLE001
            return None, f"Failed to save SQL file to workspace: {exc}"
    elif not effective_path:
        return None, "A SQL job requires either a workspace file path or a SQL query."
    task = Task(
        task_key=task_key,
        sql_task=SqlTask(
            warehouse_id=sql_warehouse,
            file=SqlTaskFile(path=effective_path, source=Source.WORKSPACE),
        ),
    )
    return task, None


def _update_job_sql_file(  # noqa: PLR0913
    tools: DatabricksTools,
    job_id: int,
    query: str,
    *,
    agent_name: str | None = None,
    instructions: str | None = None,
    client: WorkspaceClient | None = None,
) -> str | None:
    sql_text = (
        build_agentic_query(query, agent_name=agent_name or "Agent", instructions=instructions)
        if agent_name
        else query
    )
    try:
        _save_workspace_sql_file(
            tools,
            f"/Workspace/Shared/clawhouse/job_{job_id}.sql",
            sql_text,
            client=client,
        )
    except Exception as exc:  # noqa: BLE001
        return f"Failed to save updated SQL file: {exc}"
    else:
        return None


def _prepare_edit_settings(
    new_settings: dict[str, Any] | None,
    *,
    name: str | None,
    cron_expression: str | None,
    timezone_id: str,
    pause_status: str | None,
) -> dict[str, Any]:
    settings_dict = dict(new_settings or {})
    if name:
        settings_dict["name"] = name
    if cron_expression or pause_status:
        schedule = build_cron_schedule(cron_expression, timezone_id, pause_status or "UNPAUSED")
        if schedule:
            settings_dict["schedule"] = schedule.as_dict()
    return settings_dict


def _format_task_output(task_key: str, task_run_id: int, out: Any) -> dict[str, object]:
    sql_out = out.sql_output.as_dict() if getattr(out, "sql_output", None) else None
    return {
        "task_key": task_key,
        "run_id": task_run_id,
        "logs": getattr(out, "logs", None),
        "error": getattr(out, "error", None) or getattr(out, "error_trace", None),
        "sql_output": sql_out,
    }


def _fetch_single_task_output(tools: DatabricksTools, task: RunTask) -> dict[str, object]:
    tid = task.run_id
    if tid is None:
        return {"task_key": task.task_key, "error": "No run_id for task"}
    try:
        out = tools._call(lambda cl, task_id=tid: cl.jobs.get_run_output(run_id=task_id))
        return _format_task_output(task.task_key or "", tid, out)
    except Exception as exc:  # noqa: BLE001
        return {
            "task_key": task.task_key,
            "run_id": tid,
            "error": f"Failed to get output: {exc}",
        }


def _aggregate_task_outputs(
    parent_run_id: int, task_outputs: list[dict[str, object]]
) -> dict[str, object]:
    if not task_outputs:
        return {"run_id": parent_run_id, "tasks": []}
    if len(task_outputs) == 1:
        first = task_outputs[0]
        return {
            "run_id": parent_run_id,
            "logs": first.get("logs"),
            "error": first.get("error"),
            "sql_output": first.get("sql_output"),
            "tasks": task_outputs,
        }
    all_logs = [f"[{t.get('task_key')}]: {t['logs']}" for t in task_outputs if t.get("logs")]
    all_errors = [f"[{t.get('task_key')}]: {t['error']}" for t in task_outputs if t.get("error")]
    return {
        "run_id": parent_run_id,
        "logs": "\n\n".join(all_logs) if all_logs else None,
        "error": "\n\n".join(all_errors) if all_errors else None,
        "tasks": task_outputs,
    }


def _fetch_tasks_output(tools: DatabricksTools, parent_run_id: int) -> dict[str, object] | None:
    try:
        run = tools._call(lambda cl: cl.jobs.get_run(run_id=parent_run_id))
    except Exception:  # noqa: BLE001
        return None
    tasks = run.tasks or []
    if not tasks:
        return None
    task_outputs = [_fetch_single_task_output(tools, t) for t in tasks]
    return _aggregate_task_outputs(parent_run_id, task_outputs)


async def jobs_get_run_output(tools: DatabricksTools, run_id: int) -> dict[str, object]:
    """Get the execution output and logs of a Lakeflow job run."""
    try:
        out = tools._call(lambda cl: cl.jobs.get_run_output(run_id=run_id))
        sql_out = out.sql_output.as_dict() if out.sql_output else None
        return {
            "run_id": run_id,
            "logs": out.logs,
            "error": out.error or getattr(out, "error_trace", None),
            "sql_output": sql_out,
        }
    except Exception as exc:  # noqa: BLE001
        resolved = _fetch_tasks_output(tools, run_id)
        if resolved is not None:
            return resolved
        return {"error": f"Failed to get output for run {run_id}: {exc}"}


async def jobs_wait_run(
    tools: DatabricksTools,
    run_id: int,
    timeout_seconds: int = 120,
    poll_interval_seconds: int = 5,
) -> dict[str, object]:
    """Poll and wait for a job run to complete, returning final status and output."""
    deadline = time.monotonic() + max(1, timeout_seconds)
    interval = max(1, poll_interval_seconds)
    last_info: dict[str, object] = {}

    while time.monotonic() < deadline:
        last_info = await tools.jobs_get_run(run_id)
        if "error" in last_info:
            return last_info
        state = str(last_info.get("life_cycle_state", ""))
        if state in ("TERMINATED", "SKIPPED", "INTERNAL_ERROR"):
            output = await jobs_get_run_output(tools, run_id)
            return {
                "run_id": run_id,
                "job_id": last_info.get("job_id"),
                "life_cycle_state": state,
                "result_state": last_info.get("result_state"),
                "duration_ms": last_info.get("duration_ms"),
                "url": last_info.get("url"),
                "tasks": last_info.get("tasks", []),
                "output": output,
            }
        await asyncio.sleep(interval)

    return {
        "run_id": run_id,
        "job_id": last_info.get("job_id"),
        "life_cycle_state": last_info.get("life_cycle_state", "RUNNING"),
        "status": "TIMED_OUT_WAITING",
        "message": f"Run {run_id} is still in progress after {timeout_seconds}s.",
        "url": last_info.get("url"),
        "tasks": last_info.get("tasks", []),
    }


async def job_run_failure(tools: DatabricksTools, run_id: int) -> dict[str, object]:
    """Why a run failed, using only the forwarded client."""
    closed = _estate_closed(tools)
    if closed is not None:
        return closed
    try:
        run = tools.client.jobs.get_run(run_id=run_id)
    except PermissionDenied:
        return {"error": "not visible to you"}
    except Exception as exc:  # noqa: BLE001
        return _hidden_or_error(exc, f"Failed to get run {run_id}: {exc}")
    return _run_failure_payload(run)
