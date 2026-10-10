"""The Lakebase lock is a partial unique index on running runs."""

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import UUID

import asyncpg
import pytest
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models.function import AgentInfo, FunctionModel

from crabriks.shapes import TranscriptEntry
from crabriks.store import LakebaseSessionStore, RunInProgress
from crabriks.turn import TurnContext, run_turn

pytestmark = pytest.mark.skipif(
    not os.environ.get("CRABRIKS_TEST_DATABASE_URL"),
    reason="CRABRIKS_TEST_DATABASE_URL is not set",
)

SESSION = "33333333-3333-4333-8333-333333333333"
OWNER = "ada@example.com"
FROZEN = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)


async def _pool() -> asyncpg.Pool:
    url = os.environ["CRABRIKS_TEST_DATABASE_URL"]
    pool = await asyncpg.create_pool(url)
    if pool is None:
        raise RuntimeError("postgres pool was not created")
    return pool


async def _reply(text: str):
    async def stream(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str]:
        del messages, info
        yield text

    return stream


async def test_one_running_claim_per_session_and_a_reloadable_transcript() -> None:
    pool = await _pool()
    store = LakebaseSessionStore(pool)
    try:
        await _assert_lock_and_transcript(store, pool)
    finally:
        await store.close()


async def _assert_lock_and_transcript(store: LakebaseSessionStore, pool: asyncpg.Pool) -> None:
    await store.migrate()
    await pool.execute(
        "TRUNCATE crabriks.transcript_entries, crabriks.runs, crabriks.sessions CASCADE"
    )
    index = await pool.fetchval(
        "SELECT indexdef FROM pg_indexes WHERE indexname = 'runs_one_running_per_session'"
    )
    assert index is not None
    assert "UNIQUE" in index.upper()
    assert "(status = 'running'" in index or "status = 'running'" in index

    model = FunctionModel(stream_function=await _reply("saved"))
    result = await run_turn(
        SESSION,
        "hello",
        ctx=TurnContext(owner_id=OWNER, store=store, model=model, now=lambda: FROZEN),
    )
    await store.open_session(SESSION, OWNER)
    first = await store.claim_run(SESSION)
    with pytest.raises(RunInProgress):
        await store.claim_run(SESSION)
    await pool.execute(
        "UPDATE runs SET started_at = now() - make_interval(mins => 11) WHERE id = $1",
        UUID(first),
    )
    reclaimed = await store.claim_run(SESSION)
    assert reclaimed != first
    assert await pool.fetchval("SELECT status FROM runs WHERE id = $1", UUID(first)) == "error"
    await store.finish_run(SESSION, reclaimed, "ok")
    await store.claim_run(SESSION)

    assert result.transcript == (
        TranscriptEntry(role="user", content="hello"),
        TranscriptEntry(role="assistant", content="saved"),
    )
    assert await store.transcript(SESSION, OWNER) == result.transcript
