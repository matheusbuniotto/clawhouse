"""Lakeflow Jobs tools, observed through `run_turn` (the chat seam)."""

import json
import warnings
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

from databricks.sdk.service.jobs import (
    BaseJob,
    JobSettings,
    PauseStatus,
    Run,
    RunLifeCycleState,
    RunOutput,
    RunResultState,
    RunState,
    RunTask,
    Source,
    SparkPythonTask,
    SqlTask,
    SqlTaskFile,
    Task,
)
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel

from crabriks.agent.turn import TurnContext, TurnResult, resume_turn, run_turn
from crabriks.capabilities.databricks import DatabricksCapability
from crabriks.capabilities.workspace import resolve_agent_workspace
from crabriks.store.store import MemorySessionStore

SESSION = "00000000-0000-4000-8000-0000000000a1"


def _parts(messages: list[ModelMessage]) -> list[str]:
    return [part.part_kind for message in messages for part in message.parts]


async def _says_done(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str]:
    del messages, info
    yield "done"


def _calls_tool(name: str, args: Mapping[str, object]) -> FunctionModel:
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


def _has_tool_return(messages: list[ModelMessage], tool_name: str) -> bool:
    return any(
        getattr(p, "part_kind", "") == "tool-return" and getattr(p, "tool_name", "") == tool_name
        for m in messages
        for p in m.parts
    )


def _step_model(
    tool_name: str, args: Mapping[str, object], tool_id: str, done_reply: str
) -> FunctionModel:
    async def stream(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        del info
        if not _has_tool_return(messages, tool_name):
            yield {
                0: DeltaToolCall(
                    name=tool_name,
                    json_args=json.dumps(args),
                    tool_call_id=tool_id,
                )
            }
            return
        yield done_reply

    return FunctionModel(stream_function=stream)


REPO_ROOT = Path(__file__).resolve().parent.parent


def _ctx(
    client: MagicMock,
    store: MemorySessionStore,
    *,
    model: FunctionModel | None = None,
    warehouse_id: str | None = "wh-1",
    workspace_root: Path | None = None,
) -> TurnContext:
    return TurnContext(
        workspace=resolve_agent_workspace(workspace_root, "main") if workspace_root else None,
        workspace_root=workspace_root,
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
    ctx = _ctx(client, store or MemorySessionStore(), model=_calls_tool(tool, args))
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
                    file=SqlTaskFile(
                        path="/Workspace/Users/a@x.com/report.sql", source=Source.WORKSPACE
                    ),
                ),
            )
        ],
    )


async def test_jobs_create_sql_task_with_inline_query_imports_file_to_workspace() -> None:
    client = MagicMock()
    client.jobs.create.return_value = MagicMock(job_id=44)
    store = MemorySessionStore()
    args: dict[str, object] = {
        "name": "ny_taxi_outliers",
        "task_type": "sql",
        "query": "SELECT * FROM samples.nyctaxi.trips WHERE fare_amount > 100",
    }

    paused = await _turn(client, "jobs_create", args, store)
    assert paused.approval_id is not None
    resumed = await _approve(client, store, paused.approval_id)

    assert _tool_result(resumed) == {"job_id": 44, "name": "ny_taxi_outliers"}
    expected_path = "/Workspace/Shared/crabriks/ny_taxi_outliers.sql"
    assert client.workspace.upload.call_args.kwargs["path"] == expected_path
    client.workspace.mkdirs.assert_called_once_with("/Workspace/Shared/crabriks")
    client.jobs.create.assert_called_once()
    task = client.jobs.create.call_args.kwargs["tasks"][0]
    assert task.sql_task.file.path == expected_path
    assert task.sql_task.file.source == Source.WORKSPACE


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

    ctx = _ctx(MagicMock(), MemorySessionStore(), model=FunctionModel(stream_function=capture))
    await run_turn(SESSION, "hi", ctx=ctx)

    for tool in (
        "jobs_list",
        "jobs_get_run",
        "jobs_get_run_output",
        "jobs_run_now",
        "jobs_create",
        "jobs_edit",
        "jobs_delete",
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
                run_id=81,
                state=RunState(
                    life_cycle_state=RunLifeCycleState.TERMINATED,
                    result_state=RunResultState.SUCCESS,
                ),
            ),
            RunTask(
                task_key="load",
                run_id=82,
                state=RunState(life_cycle_state=RunLifeCycleState.RUNNING),
            ),
        ],
    )

    result = await _turn(client, "jobs_get_run", {"run_id": 80})

    assert _tool_result(result)["tasks"] == [
        {
            "task_key": "extract",
            "run_id": 81,
            "life_cycle_state": "TERMINATED",
            "result_state": "SUCCESS",
        },
        {"task_key": "load", "run_id": 82, "life_cycle_state": "RUNNING", "result_state": None},
    ]


async def test_jobs_list_keeps_the_limit_within_the_api_range() -> None:
    client = MagicMock()
    client.jobs.list.return_value = []

    await _turn(client, "jobs_list", {"limit": 500})

    client.jobs.list.assert_called_once_with(limit=100)


async def test_lakeflow_jobs_skill_activates_in_a_turn_and_the_harness_loads_it() -> None:
    seen: list[str] = []

    async def capture(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str]:
        del info
        for m in messages:
            for part in m.parts:
                content = getattr(part, "content", None)
                if content is not None:
                    seen.append(str(content))
        yield "done"

    ctx = _ctx(
        MagicMock(),
        MemorySessionStore(),
        model=FunctionModel(stream_function=capture),
        workspace_root=REPO_ROOT,
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = await run_turn(SESSION, "/skill:lakeflow-jobs rerun my etl", ctx=ctx)

    assert result.status == "ok"
    assert any("### Skill Instructions: lakeflow-jobs" in text for text in seen)
    assert any("jobs_run_now" in text for text in seen)
    assert [str(w.message) for w in caught if "lakeflow-jobs" in str(w.message)] == []


async def test_chat_creates_agent_creates_job_and_delivers_deep_analysis(
    tmp_path: Path,
) -> None:
    """Demonstrates the complete workflow:

    1. User asks in chat to create an agent.
    2. Agent is created in store and workspace provisioned.
    3. User asks to create a Databricks Job to query samples.nyctaxi.trips and analyze it.
    4. Mutating tool jobs_create requires approval -> approved -> job created.
    5. Test run triggered -> jobs_run_now requires approval -> approved -> run starts.
    6. jobs_get_run fetches status and deep analysis is delivered.
    """
    client = MagicMock()
    client.jobs.create.return_value = MagicMock(job_id=99)
    client.jobs.run_now.return_value = MagicMock(run_id=888)
    client.jobs.get_run.return_value = Run(
        run_id=888,
        job_id=99,
        run_page_url="https://workspace.databricks.com/#job/99/run/888",
        state=RunState(
            life_cycle_state=RunLifeCycleState.TERMINATED,
            result_state=RunResultState.SUCCESS,
        ),
    )

    store = MemorySessionStore()
    workspace = resolve_agent_workspace(tmp_path, "main")
    workspace.directory.mkdir(parents=True)

    # Step 1 & 2: Create Agent in chat
    agent_args = {
        "name": "NyTaxiAnalyst",
        "description": "Specialist in NYC taxi ride anomalies and fare outliers",
        "system_prompt": "Analyze taxi fares and trip distance distributions.",
        "signature_emoji": "🚕",
    }
    m1 = _step_model(
        "create_agent", agent_args, "call-create-taxi", "Agent NyTaxiAnalyst 🚕 created."
    )
    turn1 = await run_turn(
        SESSION,
        "Create an agent named NyTaxiAnalyst to analyze taxi trips",
        ctx=_ctx(client, store, model=m1, workspace_root=tmp_path),
    )
    assert turn1.status == "ok"
    assert "Agent NyTaxiAnalyst 🚕 created." in turn1.reply
    created_agents = await store.list_custom_agents("user-1")
    assert len(created_agents) == 1
    assert created_agents[0].name == "NyTaxiAnalyst"

    # Step 3 & 4: User asks to create a Databricks Job to query samples.nyctaxi.trips
    job_args = {
        "name": "nyctaxi_deep_analysis",
        "task_type": "sql",
        "path": "/Workspace/Shared/nyctaxi_analysis.sql",
    }
    m2 = _step_model("jobs_create", job_args, "call-create-job", "Job created with ID 99.")
    turn2 = await run_turn(
        SESSION,
        "Create a job to query samples.nyctaxi.trips for NyTaxiAnalyst",
        ctx=_ctx(client, store, model=m2, workspace_root=tmp_path),
    )
    assert turn2.status == "pending_approval"
    assert turn2.approval_id is not None
    client.jobs.create.assert_not_called()

    # User approves job creation
    resumed2 = await _approve(client, store, turn2.approval_id)
    assert resumed2.status == "ok"
    client.jobs.create.assert_called_once()

    # Step 5: Trigger test run (jobs_run_now requires approval)
    m3 = _step_model("jobs_run_now", {"job_id": 99}, "call-run-job", "Run 888 triggered.")
    turn3 = await run_turn(
        SESSION,
        "Trigger a test run of job 99",
        ctx=_ctx(client, store, model=m3, workspace_root=tmp_path),
    )
    assert turn3.status == "pending_approval"
    assert turn3.approval_id is not None
    client.jobs.run_now.assert_not_called()

    # User approves run trigger
    resumed3 = await _approve(client, store, turn3.approval_id)
    assert resumed3.status == "ok"
    client.jobs.run_now.assert_called_once_with(job_id=99, job_parameters=None)

    # Step 6: Query run status and deliver deep analysis
    report = (
        "🚕 **NyTaxiAnalyst Deep Analysis Report** (Run #888 - SUCCESS)\n"
        "- Analyzed: `samples.nyctaxi.trips`\n"
        "- Identified 3.2% outlier fares exceeding $100.\n"
        "- Average trip distance: 2.8 miles."
    )
    m4 = _step_model("jobs_get_run", {"run_id": 888}, "call-get-run", report)
    turn4 = await run_turn(
        SESSION,
        "Check status and deliver deep analysis",
        ctx=_ctx(client, store, model=m4, workspace_root=tmp_path),
    )
    assert turn4.status == "ok"
    assert "NyTaxiAnalyst Deep Analysis Report" in turn4.reply
    assert "samples.nyctaxi.trips" in turn4.reply
    assert "Run #888" in turn4.reply


async def test_jobs_create_agentic_task_builds_ai_query() -> None:
    client = MagicMock()
    client.jobs.create.return_value = MagicMock(job_id=101)
    store = MemorySessionStore()
    args: dict[str, object] = {
        "name": "nyctaxi_agentic",
        "task_type": "agentic",
        "agent_name": "TaxiAnalyst",
        "query": "SELECT * FROM samples.nyctaxi.trips WHERE fare_amount > 100",
        "instructions": "Identify outlier fares and anomalous pickup locations",
    }

    paused = await _turn(client, "jobs_create", args, store)
    assert paused.status == "pending_approval"
    assert paused.approval_id is not None
    resumed = await _approve(client, store, paused.approval_id)
    assert resumed.status == "ok"

    result = _tool_result(resumed)
    assert result["job_id"] == 101
    assert result["task_type"] == "agentic"
    assert result["agent_name"] == "TaxiAnalyst"

    client.workspace.upload.assert_called_once()
    uploaded_content = client.workspace.upload.call_args.kwargs["content"].getvalue().decode()
    assert "ai_query" in uploaded_content
    assert "You are @TaxiAnalyst" in uploaded_content
    assert "samples.nyctaxi.trips" in uploaded_content


async def test_jobs_create_with_cron_schedule() -> None:
    client = MagicMock()
    client.jobs.create.return_value = MagicMock(job_id=102)
    store = MemorySessionStore()
    args: dict[str, object] = {
        "name": "daily_report",
        "task_type": "sql",
        "path": "/Workspace/Shared/report.sql",
        "cron_expression": "0 0 12 * * ?",
        "timezone_id": "UTC",
    }

    paused = await _turn(client, "jobs_create", args, store)
    assert paused.status == "pending_approval"
    assert paused.approval_id is not None
    resumed = await _approve(client, store, paused.approval_id)
    assert resumed.status == "ok"

    result = _tool_result(resumed)
    assert result["job_id"] == 102
    assert result["scheduled"] is True

    client.jobs.create.assert_called_once()
    sched = client.jobs.create.call_args.kwargs["schedule"]
    assert sched.quartz_cron_expression == "0 0 12 * * ?"
    assert sched.timezone_id == "UTC"
    assert sched.pause_status == PauseStatus.UNPAUSED


async def test_jobs_edit_schedule_and_name_updates_job_settings() -> None:
    client = MagicMock()
    store = MemorySessionStore()
    args: dict[str, object] = {
        "job_id": 5,
        "name": "nightly-renamed",
        "cron_expression": "0 0 18 * * ?",
        "pause_status": "PAUSED",
    }

    paused = await _turn(client, "jobs_edit", args, store)
    assert paused.status == "pending_approval"
    assert paused.approval_id is not None
    resumed = await _approve(client, store, paused.approval_id)
    assert resumed.status == "ok"
    assert _tool_result(resumed) == {"job_id": 5, "updated": True}

    client.jobs.update.assert_called_once()
    call = client.jobs.update.call_args
    assert call.kwargs["job_id"] == 5
    settings = call.kwargs["new_settings"]
    assert settings.name == "nightly-renamed"
    assert settings.schedule.quartz_cron_expression == "0 0 18 * * ?"
    assert settings.schedule.pause_status == PauseStatus.PAUSED


async def test_jobs_delete_waits_for_approval_then_deletes() -> None:
    client = MagicMock()
    store = MemorySessionStore()

    paused = await _turn(client, "jobs_delete", {"job_id": 55}, store)
    assert paused.status == "pending_approval"
    assert paused.approval_id is not None
    client.jobs.delete.assert_not_called()

    resumed = await _approve(client, store, paused.approval_id)
    assert resumed.status == "ok"
    assert _tool_result(resumed) == {"job_id": 55, "deleted": True}
    client.jobs.delete.assert_called_once_with(job_id=55)


async def test_jobs_get_run_output_returns_output_without_approval() -> None:
    client = MagicMock()
    client.jobs.get_run_output.return_value = RunOutput(
        logs="Analysis complete: found 12 outliers.",
        error=None,
    )

    result = await _turn(client, "jobs_get_run_output", {"run_id": 99})
    assert result.status == "ok"
    assert _tool_result(result) == {
        "run_id": 99,
        "logs": "Analysis complete: found 12 outliers.",
        "error": None,
        "sql_output": None,
    }
    client.jobs.get_run_output.assert_called_once_with(run_id=99)


async def test_jobs_get_run_output_resolves_single_task_parent_run() -> None:
    client = MagicMock()
    client.jobs.get_run_output.side_effect = [
        Exception("Retrieving the output of runs with multiple tasks is not supported."),
        RunOutput(logs="Analysis output from agent", error=None),
    ]
    client.jobs.get_run.return_value = Run(
        run_id=500,
        job_id=42,
        tasks=[RunTask(task_key="analyze_task", run_id=501)],
    )

    result = await _turn(client, "jobs_get_run_output", {"run_id": 500})
    assert result.status == "ok"
    assert _tool_result(result) == {
        "run_id": 500,
        "logs": "Analysis output from agent",
        "error": None,
        "sql_output": None,
        "tasks": [
            {
                "task_key": "analyze_task",
                "run_id": 501,
                "logs": "Analysis output from agent",
                "error": None,
                "sql_output": None,
            }
        ],
    }


async def test_jobs_get_run_output_resolves_multi_task_parent_run() -> None:
    client = MagicMock()
    client.jobs.get_run_output.side_effect = [
        Exception("Retrieving the output of runs with multiple tasks is not supported."),
        RunOutput(logs="Step 1 complete", error=None),
        RunOutput(logs="Step 2 complete", error=None),
    ]
    client.jobs.get_run.return_value = Run(
        run_id=600,
        job_id=42,
        tasks=[
            RunTask(task_key="step1", run_id=601),
            RunTask(task_key="step2", run_id=602),
        ],
    )

    result = await _turn(client, "jobs_get_run_output", {"run_id": 600})
    assert result.status == "ok"
    tool_res = _tool_result(result)
    assert tool_res["run_id"] == 600
    assert tool_res["logs"] == "[step1]: Step 1 complete\n\n[step2]: Step 2 complete"
    assert tool_res["error"] is None
    assert tool_res["tasks"] == [
        {
            "task_key": "step1",
            "run_id": 601,
            "logs": "Step 1 complete",
            "error": None,
            "sql_output": None,
        },
        {
            "task_key": "step2",
            "run_id": 602,
            "logs": "Step 2 complete",
            "error": None,
            "sql_output": None,
        },
    ]


async def test_jobs_wait_run_polls_until_terminated_and_returns_output() -> None:
    client = MagicMock()
    # First poll: RUNNING; second poll: TERMINATED
    client.jobs.get_run.side_effect = [
        Run(
            run_id=700,
            job_id=10,
            state=RunState(life_cycle_state=RunLifeCycleState.RUNNING),
            tasks=[RunTask(task_key="step", run_id=701)],
        ),
        Run(
            run_id=700,
            job_id=10,
            state=RunState(
                life_cycle_state=RunLifeCycleState.TERMINATED,
                result_state=RunResultState.SUCCESS,
            ),
            tasks=[RunTask(task_key="step", run_id=701)],
        ),
    ]
    client.jobs.get_run_output.return_value = RunOutput(logs="Run complete!", error=None)

    result = await _turn(
        client,
        "jobs_wait_run",
        {"run_id": 700, "timeout_seconds": 10, "poll_interval_seconds": 0},
    )
    assert result.status == "ok"
    tool_res = _tool_result(result)
    assert tool_res["run_id"] == 700
    assert tool_res["life_cycle_state"] == "TERMINATED"
    assert tool_res["result_state"] == "SUCCESS"
    out = tool_res.get("output")
    assert isinstance(out, dict)
    assert out.get("logs") == "Run complete!"


async def test_jobs_run_now_with_wait_flag_awaits_completion() -> None:
    client = MagicMock()
    client.jobs.run_now.return_value = MagicMock(run_id=888)
    client.jobs.get_run.return_value = Run(
        run_id=888,
        job_id=5,
        state=RunState(
            life_cycle_state=RunLifeCycleState.TERMINATED,
            result_state=RunResultState.SUCCESS,
        ),
        tasks=[RunTask(task_key="t1", run_id=889)],
    )
    client.jobs.get_run_output.return_value = RunOutput(logs="Done in one turn", error=None)
    store = MemorySessionStore()

    paused = await _turn(
        client,
        "jobs_run_now",
        {"job_id": 5, "wait": True, "timeout_seconds": 10},
        store,
    )
    assert paused.status == "pending_approval"
    assert paused.approval_id is not None

    resumed = await _approve(client, store, paused.approval_id)
    assert resumed.status == "ok"
    tool_res = _tool_result(resumed)
    assert tool_res["run_id"] == 888
    assert tool_res["life_cycle_state"] == "TERMINATED"
    res_out = tool_res.get("output")
    assert isinstance(res_out, dict)
    assert res_out.get("logs") == "Done in one turn"


async def test_system_ai_format_delivery_slack_and_sheets() -> None:
    client = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = "*NYC Taxi Outliers*\n- 7 trips > $100"
    client.serving_endpoints.query.return_value = MagicMock(choices=[mock_choice])

    result_slack = await _turn(
        client,
        "system_ai_format_delivery",
        {"content": "Found 7 outlier trips", "destination": "slack", "title": "NYC Taxi Outliers"},
    )
    assert result_slack.status == "ok"
    assert _tool_result(result_slack)["destination"] == "slack"
    assert "*NYC Taxi Outliers*" in str(_tool_result(result_slack)["formatted_text"])

    mock_choice.message.content = '{"sheet_name": "Outliers", "headers": ["Fare"], "rows": [[105]]}'
    result_sheets = await _turn(
        client,
        "system_ai_format_delivery",
        {"content": "Found 7 outlier trips", "destination": "sheets"},
    )
    assert result_sheets.status == "ok"
    assert _tool_result(result_sheets)["destination"] == "sheets"
    assert "Outliers" in str(_tool_result(result_sheets)["raw_json"])


async def test_delivery_send_webhook_requires_approval() -> None:
    client = MagicMock()
    store = MemorySessionStore()

    paused = await _turn(
        client,
        "delivery_send_webhook",
        {"url": "https://hooks.slack.com/services/test", "payload": {"text": "hello"}},
        store,
    )
    assert paused.status == "pending_approval"
    assert paused.approval_id is not None
