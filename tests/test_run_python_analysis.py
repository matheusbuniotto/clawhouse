"""Ad-hoc Python analysis submits one workspace Spark task as the caller."""

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from databricks.sdk.service.jobs import (
    Run,
    RunLifeCycleState,
    RunOutput,
    RunResultState,
    RunState,
    Source,
)
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel

from clawhouse.agent.turn import (
    DEFAULT_APPROVAL_REQUIRED_TOOLS,
    ToolCallNotice,
    TurnContext,
    resume_turn,
    run_turn,
)
from clawhouse.api.app import _stream_frame  # pyright: ignore[reportPrivateUsage]
from clawhouse.capabilities.databricks import DatabricksCapability, DatabricksTools
from clawhouse.settings import sensitive_tools_from_env
from clawhouse.store.store import MemorySessionStore

SESSION = "00000000-0000-4000-8000-0000000000b1"


def _tools(client: MagicMock, token: str = "user-token") -> DatabricksTools:
    return DatabricksTools(client, "wh-1", user_token=token)


def _run(
    *,
    life_cycle: RunLifeCycleState,
    result: RunResultState | None,
    run_id: int = 9,
) -> Run:
    return Run(
        run_id=run_id,
        run_page_url=f"https://example.cloud.databricks.com/#job/0/run/{run_id}",
        start_time=1_000,
        end_time=3_000,
        state=RunState(life_cycle_state=life_cycle, result_state=result, state_message=""),
        tasks=[],
    )


def _submitted(run: Run) -> MagicMock:
    waiter = MagicMock()
    waiter.run_id = None
    waiter.response = run
    return waiter


@pytest.mark.asyncio
async def test_uploads_shared_py_and_submits_spark_python_task() -> None:
    client = MagicMock()
    client.jobs.submit.return_value = _submitted(
        _run(life_cycle=RunLifeCycleState.TERMINATED, result=RunResultState.SUCCESS)
    )
    client.jobs.get_run.return_value = _run(
        life_cycle=RunLifeCycleState.TERMINATED, result=RunResultState.SUCCESS
    )
    client.jobs.get_run_output.return_value = RunOutput(logs="ok")

    await _tools(client).run_python_analysis("print(1)", execution_id="exec-1")

    client.workspace.mkdirs.assert_called_once_with("/Workspace/Shared/clawhouse/executions")
    upload = client.workspace.upload.call_args
    assert upload.args[0] == "/Workspace/Shared/clawhouse/executions/exec-1.py"
    assert upload.kwargs["overwrite"] is True
    assert upload.kwargs["format"].value == "AUTO"
    task = client.jobs.submit.call_args.kwargs["tasks"][0]
    assert task.spark_python_task.python_file.endswith("/exec-1.py")
    assert task.spark_python_task.source == Source.WORKSPACE
    assert client.jobs.submit.call_count == 1


@pytest.mark.asyncio
async def test_submitted_run_returns_run_id_state_and_page_url() -> None:
    client = MagicMock()
    run = _run(life_cycle=RunLifeCycleState.TERMINATED, result=RunResultState.SUCCESS)
    client.jobs.submit.return_value = _submitted(run)
    client.jobs.get_run.return_value = run
    client.jobs.get_run_output.return_value = RunOutput(logs="ok")

    result = await _tools(client).run_python_analysis("print(1)", execution_id="exec-2")

    assert result["run_id"] == 9
    assert result["life_cycle_state"] == "TERMINATED"
    assert result["run_page_url"] == "https://example.cloud.databricks.com/#job/0/run/9"


@pytest.mark.asyncio
async def test_polls_at_most_every_5_seconds_until_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = {"t": 0.0}
    sleeps: list[float] = []

    def monotonic() -> float:
        return clock["t"]

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock["t"] += seconds

    monkeypatch.setattr("clawhouse.capabilities.databricks.time.monotonic", monotonic)
    monkeypatch.setattr("clawhouse.capabilities.databricks.asyncio.sleep", sleep)
    client = MagicMock()
    running = _run(life_cycle=RunLifeCycleState.RUNNING, result=None)
    client.jobs.submit.return_value = _submitted(running)
    client.jobs.get_run.return_value = running

    result = await _tools(client).run_python_analysis(
        "print(1)", execution_id="exec-3", timeout_seconds=12
    )

    assert sleeps
    assert max(sleeps) <= 5
    assert result["status"] == "TIMED_OUT_WAITING"
    assert client.jobs.get_run.call_count == 3


@pytest.mark.asyncio
async def test_success_returns_logs_capped_at_20000_and_duration_ms() -> None:
    client = MagicMock()
    run = _run(life_cycle=RunLifeCycleState.TERMINATED, result=RunResultState.SUCCESS)
    client.jobs.submit.return_value = _submitted(run)
    client.jobs.get_run.return_value = run
    raw = "HEAD" + ("x" * 20_006) + "TAIL"
    client.jobs.get_run_output.return_value = RunOutput(logs=raw)

    result = await _tools(client).run_python_analysis("print(1)", execution_id="exec-4")

    assert result["result_state"] == "SUCCESS"
    assert result["duration_ms"] == 2_000
    logs = result["logs"]
    assert isinstance(logs, str)
    assert len(logs) == 20_000
    assert logs == raw[-20_000:]
    assert logs.endswith("TAIL")
    assert not logs.startswith("HEAD")


@pytest.mark.asyncio
async def test_failed_run_returns_error_and_page_url() -> None:
    client = MagicMock()
    run = _run(life_cycle=RunLifeCycleState.TERMINATED, result=RunResultState.FAILED)
    client.jobs.submit.return_value = _submitted(run)
    client.jobs.get_run.return_value = run
    client.jobs.get_run_output.return_value = RunOutput(logs="", error="boom")

    result = await _tools(client).run_python_analysis("print(1)", execution_id="exec-5")

    assert result["result_state"] == "FAILED"
    assert result["error"] == "boom"
    assert result["run_page_url"] == "https://example.cloud.databricks.com/#job/0/run/9"


@pytest.mark.asyncio
async def test_timeout_returns_timed_out_waiting_without_cancel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = {"t": 0.0}
    monkeypatch.setattr("clawhouse.capabilities.databricks.time.monotonic", lambda: clock["t"])

    async def sleep(seconds: float) -> None:
        clock["t"] += seconds

    monkeypatch.setattr("clawhouse.capabilities.databricks.asyncio.sleep", sleep)
    client = MagicMock()
    running = _run(life_cycle=RunLifeCycleState.RUNNING, result=None, run_id=11)
    client.jobs.submit.return_value = _submitted(running)
    client.jobs.get_run.return_value = running

    result = await _tools(client).run_python_analysis(
        "print(1)", execution_id="exec-6", timeout_seconds=1
    )

    assert result["status"] == "TIMED_OUT_WAITING"
    assert result["run_id"] == 11
    assert result["run_page_url"] == "https://example.cloud.databricks.com/#job/0/run/11"
    client.jobs.cancel_run.assert_not_called()


@pytest.mark.asyncio
async def test_missing_user_token_does_not_submit_or_use_jobs_sp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []

    class Guard(dict):
        def get(self, key: str, default: str | None = None) -> str | None:  # type: ignore[override]
            if key in {"CLAWHOUSE_JOBS_SP_CLIENT_ID", "CLAWHOUSE_JOBS_SP_CLIENT_SECRET"}:
                seen.append(key)
            return super().get(key, default)

    monkeypatch.setattr(
        "clawhouse.capabilities.databricks.os.environ", Guard(CLAWHOUSE_JOBS_SP_CLIENT_ID="sp")
    )
    client = MagicMock()

    result = await _tools(client, token="").run_python_analysis("print(1)")

    assert result == {"error": "user token required"}
    assert seen == []
    client.jobs.submit.assert_not_called()


def test_default_sensitive_set_includes_run_python_analysis() -> None:
    assert sensitive_tools_from_env({}) == ()
    assert "run_python_analysis" in DEFAULT_APPROVAL_REQUIRED_TOOLS


def test_timeout_seconds_defaults_to_120_and_honors_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CLAWHOUSE_EXECUTION_TIMEOUT_SECONDS", raising=False)
    client = MagicMock()
    run = _run(life_cycle=RunLifeCycleState.TERMINATED, result=RunResultState.SUCCESS)
    client.jobs.submit.return_value = _submitted(run)
    client.jobs.get_run.return_value = run
    client.jobs.get_run_output.return_value = RunOutput(logs="ok")

    asyncio.run(_tools(client).run_python_analysis("print(1)", execution_id="exec-7"))
    assert client.jobs.submit.call_args.kwargs["timeout_seconds"] == 120

    monkeypatch.setenv("CLAWHOUSE_EXECUTION_TIMEOUT_SECONDS", "45")
    asyncio.run(_tools(client).run_python_analysis("print(1)", execution_id="exec-8"))
    assert client.jobs.submit.call_args.kwargs["timeout_seconds"] == 45


def _calls(name: str, args: dict[str, object]) -> FunctionModel:
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
    client: MagicMock, store: MemorySessionStore, model: FunctionModel, token: str
) -> TurnContext:
    return TurnContext(
        owner_id="user-1",
        store=store,
        model=model,
        now=lambda: datetime(2026, 10, 12, 12, 0, tzinfo=UTC),
        user_token=token,
        headless=True,
        databricks_capability=DatabricksCapability(
            client_factory=lambda _token: client, warehouse_id="wh-1"
        ),
    )


@pytest.mark.asyncio
async def test_tool_call_frame_names_run_python_analysis_and_execution_id() -> None:
    client = MagicMock()
    store = MemorySessionStore()
    model = _calls("run_python_analysis", {"code": "print(1)", "execution_id": "exec-sse"})
    emitted: list[ToolCallNotice] = []

    async def capture(notice: object) -> None:
        if isinstance(notice, ToolCallNotice):
            emitted.append(notice)

    ctx = _ctx(client, store, model, "user-token")
    ctx = replace(ctx, emit=capture)
    paused = await run_turn(SESSION, "analyze", ctx=ctx)
    assert paused.status == "pending_approval"
    assert emitted, "turn emitted no tool_call notice"
    frame = _stream_frame(emitted[0])
    assert frame is not None
    event, payload = frame
    assert event == "tool_call"
    assert payload["name"] == "run_python_analysis"
    assert "exec-sse" in str(payload["arguments"])


@pytest.mark.asyncio
async def test_headless_turn_without_token_returns_user_token_required_and_continues() -> None:
    client = MagicMock()
    store = MemorySessionStore()
    model = _calls("run_python_analysis", {"code": "print(1)", "execution_id": "exec-9"})
    paused = await run_turn(SESSION, "analyze", ctx=_ctx(client, store, model, ""))
    assert paused.approval_id is not None
    finished = await resume_turn(
        SESSION,
        paused.approval_id,
        "approved",
        ctx=_ctx(client, store, _calls("run_python_analysis", {"code": "print(1)"}), ""),
    )
    assert finished.status == "ok"
    tool = next(entry for entry in finished.transcript if entry.role == "tool_result")
    assert json.loads(tool.content) == {"error": "user token required"}
    client.jobs.submit.assert_not_called()
