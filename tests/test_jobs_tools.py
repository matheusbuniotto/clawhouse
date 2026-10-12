"""Lakeflow Jobs tools, observed through `run_turn` (the chat seam)."""

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from unittest.mock import MagicMock

from databricks.sdk.service.jobs import (
    BaseJob,
    JobSettings,
    Run,
    RunLifeCycleState,
    RunResultState,
    RunState,
    RunTask,
    SparkPythonTask,
    SqlTask,
    SqlTaskFile,
    Task,
)
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel

from crabriks.agent.turn import TurnContext, TurnResult, resume_turn, run_turn
from crabriks.capabilities.databricks import DatabricksCapability
from crabriks.store.store import MemorySessionStore

SESSION = "00000000-0000-4000-8000-0000000000a1"


async def _says_done(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str]:
    del messages, info
    yield "done"


def _calls_tool(name: str, args: dict[str, object]) -> FunctionModel:
    async def stream(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        del info
        returned = any(
            getattr(part, "part_kind", "") == "tool-return" for m in messages for part in m.parts
        )
        if returned:
            yield "done"
            return
        yield {0: DeltaToolCall(name=name, json_args=json.dumps(args), tool_call_id="call-1")}

    return FunctionModel(stream_function=stream)


def _ctx(
    client: MagicMock,
    store: MemorySessionStore,
    model: FunctionModel | None = None,
    warehouse_id: str | None = "wh-1",
) -> TurnContext:
    return TurnContext(
        owner_id="user-1",
        store=store,
        model=model or FunctionModel(stream_function=_says_done),
        now=lambda: datetime(2026, 10, 12, 12, 0, 0, tzinfo=UTC),
        user_token="client-credential",
        databricks_capability=DatabricksCapability(
            client_factory=lambda _token: client, warehouse_id=warehouse_id
        ),
    )


async def _turn(
    client: MagicMock,
    tool: str,
    args: dict[str, object],
    store: MemorySessionStore | None = None,
) -> TurnResult:
    ctx = _ctx(client, store or MemorySessionStore(), _calls_tool(tool, args))
    return await run_turn(SESSION, "go", ctx=ctx)


async def _approve(
    client: MagicMock,
    store: MemorySessionStore,
    approval_id: str,
    warehouse_id: str | None = "wh-1",
) -> TurnResult:
    ctx = _ctx(client, store, warehouse_id=warehouse_id)
    return await resume_turn(SESSION, approval_id, "approved", ctx=ctx)


def _tool_result(result: TurnResult) -> dict[str, object]:
    entry = next(e for e in result.transcript if e.role == "tool_result")
    return json.loads(entry.content)


async def test_jobs_get_run_reports_state_without_approval() -> None:
    client = MagicMock()
    client.jobs.get_run.return_value = Run(
        run_id=77,
        job_id=5,
        run_page_url="https://example.cloud.databricks.com/#job/5/run/77",
        start_time=1_000,
        end_time=4_500,
        state=RunState(
            life_cycle_state=RunLifeCycleState.TERMINATED,
            result_state=RunResultState.SUCCESS,
            state_message="",
        ),
    )

    result = await _turn(client, "jobs_get_run", {"run_id": 77})

    assert result.status == "ok"
    assert _tool_result(result) == {
        "run_id": 77,
        "job_id": 5,
        "life_cycle_state": "TERMINATED",
        "result_state": "SUCCESS",
        "state_message": "",
        "duration_ms": 3_500,
        "url": "https://example.cloud.databricks.com/#job/5/run/77",
        "tasks": [],
    }
    client.jobs.get_run.assert_called_once_with(run_id=77)


async def test_jobs_list_returns_jobs_without_approval() -> None:
    client = MagicMock()
    client.jobs.list.return_value = [
        BaseJob(job_id=5, creator_user_name="a@x.com", settings=JobSettings(name="nightly")),
        BaseJob(job_id=6, creator_user_name="b@x.com", settings=JobSettings(name="hourly")),
    ]

    result = await _turn(client, "jobs_list", {"limit": 2})

    assert result.status == "ok"
    assert _tool_result(result) == {
        "jobs": [
            {"job_id": 5, "name": "nightly", "creator": "a@x.com"},
            {"job_id": 6, "name": "hourly", "creator": "b@x.com"},
        ],
        "job_count": 2,
    }


async def test_jobs_run_now_waits_for_approval_then_triggers_the_run() -> None:
    client = MagicMock()
    client.jobs.run_now.return_value = MagicMock(run_id=901)
    store = MemorySessionStore()

    paused = await _turn(
        client, "jobs_run_now", {"job_id": 5, "parameters": {"env": "prod"}}, store
    )

    assert paused.status == "pending_approval"
    assert paused.approval_id is not None
    client.jobs.run_now.assert_not_called()

    resumed = await _approve(client, store, paused.approval_id)

    assert resumed.status == "ok"
    assert _tool_result(resumed) == {"run_id": 901, "job_id": 5}
    client.jobs.run_now.assert_called_once_with(job_id=5, job_parameters={"env": "prod"})


async def test_jobs_cancel_run_waits_for_approval_then_cancels() -> None:
    client = MagicMock()
    store = MemorySessionStore()

    paused = await _turn(client, "jobs_cancel_run", {"run_id": 77}, store)

    assert paused.status == "pending_approval"
    assert paused.approval_id is not None
    client.jobs.cancel_run.assert_not_called()

    resumed = await _approve(client, store, paused.approval_id)

    assert resumed.status == "ok"
    assert _tool_result(resumed) == {"run_id": 77, "cancel_requested": True}
    client.jobs.cancel_run.assert_called_once_with(run_id=77)


async def test_jobs_create_python_task_waits_for_approval_then_creates_the_job() -> None:
    client = MagicMock()
    client.jobs.create.return_value = MagicMock(job_id=42)
    store = MemorySessionStore()
    args: dict[str, object] = {
        "name": "etl",
        "task_type": "python",
        "path": "/Workspace/Users/a@x.com/etl.py",
        "parameters": ["--env", "prod"],
    }

    paused = await _turn(client, "jobs_create", args, store)

    assert paused.status == "pending_approval"
    assert paused.approval_id is not None
    client.jobs.create.assert_not_called()

    resumed = await _approve(client, store, paused.approval_id)

    assert resumed.status == "ok"
    assert _tool_result(resumed) == {"job_id": 42, "name": "etl"}
    client.jobs.create.assert_called_once_with(
        name="etl",
        tasks=[
            Task(
                task_key="etl",
                spark_python_task=SparkPythonTask(
                    python_file="/Workspace/Users/a@x.com/etl.py",
                    parameters=["--env", "prod"],
                ),
            )
        ],
    )


async def test_jobs_create_sql_task_uses_the_session_warehouse() -> None:
    client = MagicMock()
    client.jobs.create.return_value = MagicMock(job_id=43)
    store = MemorySessionStore()
    args: dict[str, object] = {
        "name": "report",
        "task_type": "sql",
        "path": "/Workspace/Users/a@x.com/report.sql",
    }

    paused = await _turn(client, "jobs_create", args, store)
    assert paused.approval_id is not None
    resumed = await _approve(client, store, paused.approval_id)

    assert _tool_result(resumed) == {"job_id": 43, "name": "report"}
    client.jobs.create.assert_called_once_with(
        name="report",
        tasks=[
            Task(
                task_key="report",
                sql_task=SqlTask(
                    warehouse_id="wh-1",
                    file=SqlTaskFile(path="/Workspace/Users/a@x.com/report.sql"),
                ),
            )
        ],
    )


async def test_jobs_create_sql_task_without_a_warehouse_reports_an_error() -> None:
    client = MagicMock()
    client.warehouses.list.return_value = []
    store = MemorySessionStore()
    args: dict[str, object] = {"name": "report", "task_type": "sql", "path": "/r.sql"}

    paused = await _turn(client, "jobs_create", args, store)
    assert paused.approval_id is not None
    resumed = await _approve(client, store, paused.approval_id, warehouse_id=None)

    assert _tool_result(resumed) == {"error": "A SQL job needs a SQL warehouse; none is available."}
    client.jobs.create.assert_not_called()


async def test_jobs_edit_waits_for_approval_then_updates_the_settings() -> None:
    client = MagicMock()
    store = MemorySessionStore()
    args: dict[str, object] = {
        "job_id": 5,
        "new_settings": {"name": "nightly-v2", "max_concurrent_runs": 2},
    }

    paused = await _turn(client, "jobs_edit", args, store)

    assert paused.status == "pending_approval"
    assert paused.approval_id is not None
    client.jobs.update.assert_not_called()

    resumed = await _approve(client, store, paused.approval_id)

    assert resumed.status == "ok"
    assert _tool_result(resumed) == {"job_id": 5, "updated": True}
    client.jobs.update.assert_called_once()
    call = client.jobs.update.call_args
    assert call.kwargs["job_id"] == 5
    assert call.kwargs["new_settings"].as_dict() == {"name": "nightly-v2", "max_concurrent_runs": 2}


async def test_system_prompt_lists_every_jobs_tool() -> None:
    seen: list[str] = []

    async def capture(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str]:
        del messages
        seen.append(info.instructions or "")
        yield "done"

    ctx = _ctx(MagicMock(), MemorySessionStore(), FunctionModel(stream_function=capture))
    await run_turn(SESSION, "hi", ctx=ctx)

    for tool in (
        "jobs_list",
        "jobs_get_run",
        "jobs_run_now",
        "jobs_create",
        "jobs_edit",
        "jobs_cancel_run",
    ):
        assert tool in seen[0]


async def test_jobs_get_run_reports_each_task_of_a_multi_task_run() -> None:
    client = MagicMock()
    client.jobs.get_run.return_value = Run(
        run_id=80,
        job_id=5,
        state=RunState(life_cycle_state=RunLifeCycleState.RUNNING),
        tasks=[
            RunTask(
                task_key="extract",
                state=RunState(
                    life_cycle_state=RunLifeCycleState.TERMINATED,
                    result_state=RunResultState.SUCCESS,
                ),
            ),
            RunTask(task_key="load", state=RunState(life_cycle_state=RunLifeCycleState.RUNNING)),
        ],
    )

    result = await _turn(client, "jobs_get_run", {"run_id": 80})

    assert _tool_result(result)["tasks"] == [
        {"task_key": "extract", "life_cycle_state": "TERMINATED", "result_state": "SUCCESS"},
        {"task_key": "load", "life_cycle_state": "RUNNING", "result_state": None},
    ]


async def test_jobs_list_keeps_the_limit_within_the_api_range() -> None:
    client = MagicMock()
    client.jobs.list.return_value = []

    await _turn(client, "jobs_list", {"limit": 500})

    client.jobs.list.assert_called_once_with(limit=100)
