"""Slash commands reset or schedule a session without invoking the model."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models.function import AgentInfo, FunctionModel

from crabriks.agent.turn import TurnContext, run_turn
from crabriks.store.shapes import TranscriptEntry
from crabriks.store.store import MemorySessionStore, SessionForbidden

SESSION = "22222222-2222-4222-8222-222222222222"
OWNER = "ada@example.com"
OTHER = "grace@example.com"
NOW = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)


def _exploding_model() -> FunctionModel:
    def explode(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del messages, info
        raise AssertionError("a command must never reach the model")

    return FunctionModel(function=explode)


def _ctx(store: MemorySessionStore, *, owner: str = OWNER) -> TurnContext:
    return TurnContext(owner_id=owner, store=store, model=_exploding_model(), now=lambda: NOW)


async def _seed(store: MemorySessionStore) -> None:
    await store.open_session(SESSION, OWNER)
    run_id = await store.claim_run(SESSION)
    await store.append_entry(SESSION, run_id, TranscriptEntry(role="user", content="hello"))
    await store.append_entry(SESSION, run_id, TranscriptEntry(role="assistant", content="hi there"))
    await store.finish_run(SESSION, run_id, "ok")


async def test_clear_resets_the_transcript_and_confirms() -> None:
    store = MemorySessionStore()
    await _seed(store)

    result = await run_turn(SESSION, "/clear", ctx=_ctx(store))

    assert result.status == "ok"
    assert "clear" in result.reply.lower()
    transcript = await store.transcript(SESSION, OWNER)
    assert [entry.role for entry in transcript] == ["assistant"]
    assert transcript[0].content == result.reply
    assert [summary.id for summary in await store.list_sessions(OWNER)] == [SESSION]


async def test_clear_starts_the_next_turn_from_empty_history() -> None:
    store = MemorySessionStore()
    await _seed(store)
    await run_turn(SESSION, "/clear", ctx=_ctx(store))

    seen: list[str] = []

    async def reply(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str]:
        del info
        for message in messages:
            for part in message.parts:
                content = getattr(part, "content", None)
                if isinstance(content, str):
                    seen.append(content)
        yield "fresh"

    ctx = TurnContext(
        owner_id=OWNER,
        store=store,
        model=FunctionModel(stream_function=reply),
        now=lambda: NOW,
    )
    result = await run_turn(SESSION, "new question", ctx=ctx)

    assert result.status == "ok"
    assert all("hello" not in text and "hi there" not in text for text in seen)


async def test_clear_rejects_a_foreign_session() -> None:
    store = MemorySessionStore()
    await _seed(store)

    with pytest.raises(SessionForbidden):
        await run_turn(SESSION, "/clear", ctx=_ctx(store, owner=OTHER))


async def test_malformed_schedule_replies_with_usage_instead_of_failing() -> None:
    store = MemorySessionStore()

    result = await run_turn(SESSION, "/schedule not-a-real-form", ctx=_ctx(store))

    assert result.status == "ok"
    assert "Usage:" in result.reply
    assert [entry.role for entry in await store.transcript(SESSION, OWNER)] == [
        "user",
        "assistant",
    ]


async def test_clear_transcript_keeps_the_session_and_rejects_foreign_owners() -> None:
    store = MemorySessionStore()
    await _seed(store)

    await store.clear_transcript(SESSION, OWNER)
    assert await store.transcript(SESSION, OWNER) == ()

    with pytest.raises(SessionForbidden):
        await store.clear_transcript(SESSION, OTHER)
