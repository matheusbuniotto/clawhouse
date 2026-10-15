"""`report_progress` (#97): one card per task_id, streamed as a card, kept in the transcript."""

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from pydantic_ai.messages import ModelMessage, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel

from clawhouse.turn import (  # isort: skip
    ProgressNotice,
    ToolCallNotice,
    ToolResultNotice,
    TurnContext,
    TurnNotice,
    run_turn,
)
from clawhouse.api.app import _frame  # pyright: ignore[reportPrivateUsage]
from clawhouse.capabilities.interaction import parse_progress
from clawhouse.store import MemorySessionStore

SESSION = "55555555-5555-4555-8555-555555555555"
OWNER = "ada@example.com"
STEPS = [{"label": "Ler dados", "status": "done"}, {"label": "Gerar planilha", "status": "running"}]


class _Reporter:
    def __init__(self, args: str) -> None:
        self.args = args

    async def stream(
        self, messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        del info
        if any(isinstance(p, ToolReturnPart) for m in messages for p in m.parts):
            yield "ok"
            return
        yield {0: DeltaToolCall(name="report_progress", json_args=self.args, tool_call_id="p1")}


async def _run(args: str) -> tuple[list[TurnNotice], MemorySessionStore]:
    store = MemorySessionStore()
    notices: list[TurnNotice] = []

    async def capture(n: TurnNotice) -> None:
        notices.append(n)

    ctx = TurnContext(
        owner_id=OWNER,
        store=store,
        model=FunctionModel(stream_function=_Reporter(args).stream),
        now=lambda: datetime.now(UTC),
        emit=capture,
    )
    result = await run_turn(SESSION, "faz o relatório", ctx=ctx)
    assert result.status == "ok"
    return notices, store


async def test_progress_streams_as_a_card_not_tool_rows() -> None:
    notices, _ = await _run(json.dumps({"task_id": "t1", "steps": STEPS}))

    cards = [n for n in notices if isinstance(n, ProgressNotice)]
    assert cards == [
        ProgressNotice(task_id="t1", steps=(("Ler dados", "done"), ("Gerar planilha", "running")))
    ]
    tools = [n for n in notices if isinstance(n, ToolCallNotice | ToolResultNotice)]
    assert all(n.name != "report_progress" for n in tools)


async def test_progress_rows_stay_in_the_transcript_for_reload() -> None:
    _, store = await _run(json.dumps({"task_id": "t1", "steps": STEPS}))

    rows = [e for e in await store.transcript(SESSION, OWNER) if e.tool_name == "report_progress"]
    assert [r.role for r in rows] == ["tool_call", "tool_result"]
    assert "t1" in (rows[0].content or "")


def test_invalid_progress_arguments_are_ignored() -> None:
    assert parse_progress("{}") is None
    assert parse_progress('{"task_id": "x", "steps": [{"label": "a", "status": "?"}]}') is None
    assert parse_progress("not json") is None


def test_progress_sse_frame() -> None:
    event, data = _frame(ProgressNotice(task_id="t1", steps=(("Ler", "done"),)))
    assert event == "progress"
    assert data == {
        "type": "progress",
        "task_id": "t1",
        "steps": [{"label": "Ler", "status": "done"}],
    }
