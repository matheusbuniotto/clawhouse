"""remember and recall, and the absence of silent writes."""

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel

from clawhouse.agent.turn import TurnContext, run_turn
from clawhouse.store.store import MemorySessionStore

SESSION = "00000000-0000-4000-8000-0000000000d1"
OWNER = "ada@example.com"


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


def _ctx(store: MemorySessionStore, model: FunctionModel) -> TurnContext:
    return TurnContext(
        owner_id=OWNER,
        store=store,
        model=model,
        now=lambda: datetime(2026, 10, 12, 12, 0, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_recall_returns_at_most_5_with_citation_fields() -> None:
    store = MemorySessionStore(now=lambda: datetime(2026, 10, 12, 12, 0, tzinfo=UTC))
    await store.open_session(SESSION, OWNER)
    for index in range(6):
        await store.save_memory(OWNER, f"refunds {index}", None, "main.sales.orders")
    result = await run_turn(
        SESSION, "look", ctx=_ctx(store, _calls("recall", {"query": "refunds"}))
    )
    tool = next(entry for entry in result.transcript if entry.role == "tool_result")
    rows = json.loads(tool.content)
    assert len(rows) == 5
    assert set(rows[0]) == {"id", "text", "table_fqn", "source_session_id", "created_at"}


@pytest.mark.asyncio
async def test_remember_persists_caller_row_and_returns_id() -> None:
    store = MemorySessionStore(now=lambda: datetime(2026, 10, 12, 12, 0, tzinfo=UTC))
    await store.open_session(SESSION, OWNER)
    result = await run_turn(
        SESSION,
        "save",
        ctx=_ctx(
            store, _calls("remember", {"text": "net of refunds", "table_fqn": "main.sales.orders"})
        ),
    )
    tool = next(entry for entry in result.transcript if entry.role == "tool_result")
    memory_id = json.loads(tool.content)["id"]
    stored = await store.list_memories(OWNER)
    assert stored[0].id == memory_id
    assert stored[0].owner_id == OWNER
    assert stored[0].text == "net of refunds"


@pytest.mark.asyncio
async def test_turn_without_remember_writes_zero_memory_rows() -> None:
    store = MemorySessionStore(now=lambda: datetime(2026, 10, 12, 12, 0, tzinfo=UTC))
    await store.open_session(SESSION, OWNER)

    async def reply(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str]:
        del messages, info
        yield "done"

    await run_turn(SESSION, "hello", ctx=_ctx(store, FunctionModel(stream_function=reply)))
    assert await store.list_memories(OWNER) == ()
