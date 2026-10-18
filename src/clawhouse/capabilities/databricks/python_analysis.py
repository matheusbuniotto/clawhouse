"""Single-node cluster Python analysis execution."""

from __future__ import annotations

import asyncio
import io
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.compute import ClusterSpec
from databricks.sdk.service.jobs import Source, SparkPythonTask, SubmitTask
from databricks.sdk.service.workspace import ImportFormat

if TYPE_CHECKING:
    from clawhouse.capabilities.databricks.tools import DatabricksTools

_LOG_CAP = 20_000


def _enum_value(value: Any) -> str | None:
    if value is None:
        return None
    return str(getattr(value, "value", value))


def _execution_timeout_seconds() -> int:
    raw = os.environ.get("CLAWHOUSE_EXECUTION_TIMEOUT_SECONDS", "120")
    try:
        return int(raw)
    except ValueError:
        return 120


def _single_node_cluster() -> ClusterSpec:
    return ClusterSpec(
        spark_version=os.environ.get("CLAWHOUSE_EXECUTION_SPARK_VERSION", "15.4.x-scala2.12"),
        node_type_id=os.environ.get("CLAWHOUSE_EXECUTION_NODE_TYPE", "i3.xlarge"),
        num_workers=0,
        spark_conf={
            "spark.databricks.cluster.profile": "singleNode",
            "spark.master": "local[*]",
        },
        custom_tags={"ResourceClass": "SingleNode"},
    )


def _submitted_run(value: object) -> Any:
    if isinstance(getattr(value, "run_id", None), int):
        return value
    response = getattr(value, "response", None)
    if isinstance(getattr(response, "run_id", None), int):
        return response
    return value


def _output_fields(out: object | None) -> dict[str, object]:
    if out is None:
        return {"logs": None, "error": None}
    return {
        "logs": getattr(out, "logs", None),
        "error": getattr(out, "error", None) or getattr(out, "error_trace", None),
    }


def _task_outputs(client: WorkspaceClient, tasks: list[object]) -> dict[str, object]:
    logs: list[str] = []
    errors: list[str] = []
    for task in tasks:
        task_run_id = getattr(task, "run_id", None)
        if task_run_id is None:
            continue
        try:
            task_out = client.jobs.get_run_output(run_id=task_run_id)
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))
            continue
        if getattr(task_out, "logs", None):
            logs.append(str(task_out.logs))
        if getattr(task_out, "error", None):
            errors.append(str(task_out.error))
    return {"logs": "\n".join(logs) or None, "error": "\n".join(errors) or None}


def _upload_user_python(client: WorkspaceClient, path: str, code: str) -> None:
    parent = str(Path(path).parent)
    client.workspace.mkdirs(parent)
    client.workspace.upload(
        path,
        io.BytesIO(code.encode("utf-8")),
        overwrite=True,
        format=ImportFormat.AUTO,
    )


def _safe_run_output(client: WorkspaceClient, run_id: int) -> object | None:
    try:
        return client.jobs.get_run_output(run_id=run_id)
    except Exception:  # noqa: BLE001
        return None


def _user_run_output(
    client: WorkspaceClient, run_id: int, tasks: list[object]
) -> dict[str, object]:
    direct = _output_fields(_safe_run_output(client, run_id))
    if direct["logs"] or direct["error"]:
        return direct
    return _task_outputs(client, tasks)


def _terminal_analysis(
    client: WorkspaceClient, run_id: int, view: dict[str, object]
) -> dict[str, object]:
    tasks = view.get("tasks")
    output = _user_run_output(client, run_id, tasks if isinstance(tasks, list) else [])
    logs = output.get("logs")
    if isinstance(logs, str) and len(logs) > _LOG_CAP:
        logs = logs[-_LOG_CAP:]
    result_state = view.get("result_state")
    payload: dict[str, object] = {
        "run_id": view.get("run_id"),
        "life_cycle_state": view.get("life_cycle_state"),
        "result_state": result_state,
        "duration_ms": view.get("duration_ms"),
        "run_page_url": view.get("run_page_url"),
        "logs": logs,
    }
    if result_state == "FAILED":
        payload["error"] = output.get("error")
    return payload


def _user_run_view(client: WorkspaceClient, run_id: int, page: str | None) -> dict[str, object]:
    run = client.jobs.get_run(run_id=run_id)
    state = run.state
    duration = run.end_time - run.start_time if run.start_time and run.end_time else None
    return {
        "run_id": run.run_id,
        "life_cycle_state": _enum_value(state.life_cycle_state if state else None),
        "result_state": _enum_value(state.result_state if state else None),
        "state_message": state.state_message if state else None,
        "duration_ms": duration,
        "run_page_url": run.run_page_url or page,
        "tasks": list(run.tasks or []),
    }


async def _wait_user_run(
    client: WorkspaceClient, run_id: int, timeout_seconds: int, page: str | None
) -> dict[str, object]:
    deadline = time.monotonic() + max(1, timeout_seconds)
    interval = 5
    last: dict[str, object] = {"run_id": run_id, "run_page_url": page}
    while time.monotonic() < deadline:
        last = _user_run_view(client, run_id, page)
        if last.get("life_cycle_state") in ("TERMINATED", "SKIPPED", "INTERNAL_ERROR"):
            return _terminal_analysis(client, run_id, last)
        await asyncio.sleep(interval)
    return {
        "run_id": run_id,
        "life_cycle_state": last.get("life_cycle_state"),
        "status": "TIMED_OUT_WAITING",
        "run_page_url": last.get("run_page_url") or page,
    }


async def run_python_analysis(
    tools: DatabricksTools,
    code: str,
    execution_id: str | None = None,
    timeout_seconds: int | None = None,
) -> dict[str, object]:
    """Run ad-hoc Python on a one-off Lakeflow submit as the caller."""
    if not tools.user_token.strip():
        return {"error": "user token required"}
    execution_id = execution_id or str(uuid4())
    timeout = timeout_seconds if timeout_seconds is not None else _execution_timeout_seconds()
    path = f"/Workspace/Shared/clawhouse/executions/{execution_id}.py"
    _upload_user_python(tools.client, path, code)
    submitted = tools.client.jobs.submit(
        run_name=f"clawhouse-exec-{execution_id}",
        tasks=[
            SubmitTask(
                task_key="analysis",
                spark_python_task=SparkPythonTask(python_file=path, source=Source.WORKSPACE),
                new_cluster=_single_node_cluster(),
            )
        ],
        timeout_seconds=timeout,
    )
    run = _submitted_run(submitted)
    run_id = int(run.run_id)
    page = getattr(run, "run_page_url", None)
    waited = await _wait_user_run(tools.client, run_id, timeout, page)
    waited["execution_id"] = execution_id
    return waited
