"""The Lakebase lock is a partial unique index on running runs."""

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import UUID

import asyncpg
import pytest
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models.function import AgentInfo, FunctionModel

from clawhouse.agent.turn import TurnContext, run_turn
from clawhouse.store.shapes import TranscriptEntry, UserProfile
from clawhouse.store.store import LakebaseSessionStore, RunInProgress, SessionForbidden

pytestmark = pytest.mark.skipif(
    not os.environ.get("CLAWHOUSE_TEST_DATABASE_URL"),
    reason="CLAWHOUSE_TEST_DATABASE_URL is not set",
)

SESSION = "33333333-3333-4333-8333-333333333333"
OWNER = "ada@example.com"
FROZEN = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)


async def _pool() -> asyncpg.Pool:
    url = os.environ["CLAWHOUSE_TEST_DATABASE_URL"]
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


async def test_sessions_are_listed_for_their_owner_with_a_title() -> None:
    pool = await _pool()
    store = LakebaseSessionStore(pool)
    try:
        await store.migrate()
        await pool.execute(
            "TRUNCATE clawhouse.transcript_entries, clawhouse.runs, clawhouse.sessions CASCADE"
        )
        first = await store.create_session(OWNER)
        second = await store.create_session(OWNER)
        other = await store.create_session("grace@example.com")
        model = FunctionModel(stream_function=await _reply("ok"))
        await run_turn(
            first.id,
            "hello there",
            ctx=TurnContext(owner_id=OWNER, store=store, model=model, now=lambda: FROZEN),
        )
        listed = await store.list_sessions(OWNER)
        foreign = await store.list_sessions("grace@example.com")
    finally:
        await store.close()

    assert [session.id for session in listed] == [second.id, first.id]
    assert listed[0].title == ""
    assert listed[1].title == "hello there"
    assert [session.id for session in foreign] == [other.id]


async def _assert_lock_and_transcript(store: LakebaseSessionStore, pool: asyncpg.Pool) -> None:
    await store.migrate()
    await pool.execute(
        "TRUNCATE clawhouse.transcript_entries, clawhouse.runs, clawhouse.sessions CASCADE"
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
        "UPDATE clawhouse.runs SET started_at = now() - make_interval(mins => 11) WHERE id = $1",
        UUID(first),
    )
    reclaimed = await store.claim_run(SESSION)
    assert reclaimed != first
    assert (
        await pool.fetchval("SELECT status FROM clawhouse.runs WHERE id = $1", UUID(first))
        == "error"
    )
    await store.finish_run(SESSION, reclaimed, "ok")
    await store.claim_run(SESSION)

    assert result.transcript == (
        TranscriptEntry(agent_id="main", role="user", content="hello"),
        TranscriptEntry(agent_id="main", role="assistant", content="saved"),
    )
    assert await store.transcript(SESSION, OWNER) == result.transcript


async def test_lakebase_clear_transcript_empties_history_and_guards_ownership() -> None:
    pool = await _pool()
    store = LakebaseSessionStore(pool)
    try:
        await store.migrate()
        await pool.execute(
            "TRUNCATE clawhouse.transcript_entries, clawhouse.runs, clawhouse.sessions CASCADE"
        )
        session = await store.create_session(OWNER)
        run_id = await store.claim_run(session.id)
        await store.append_entry(session.id, run_id, TranscriptEntry(role="user", content="hi"))
        await store.finish_run(session.id, run_id, "ok")

        await store.clear_transcript(session.id, OWNER)
        assert await store.transcript(session.id, OWNER) == ()
        with pytest.raises(SessionForbidden):
            await store.clear_transcript(session.id, "grace@example.com")
    finally:
        await store.close()


async def test_migration_upgrades_existing_runs_status_constraint() -> None:
    pool = await _pool()
    store = LakebaseSessionStore(pool)
    try:
        await store.migrate()
        # Simulate an existing database with the old 3-status constraint
        await pool.execute(
            """
            ALTER TABLE clawhouse.runs DROP CONSTRAINT IF EXISTS runs_status_known;
            ALTER TABLE clawhouse.runs ADD CONSTRAINT runs_status_known
                CHECK (status IN ('running', 'ok', 'error'));
            """
        )
        # Re-running migrate upgrades the constraint to include pending_approval
        await store.migrate()
        session = await store.create_session(OWNER)
        run_id = await store.claim_run(session.id)
        await store.finish_run(session.id, run_id, "pending_approval")
        status = await pool.fetchval(
            "SELECT status FROM clawhouse.runs WHERE id = $1", UUID(run_id)
        )
        assert status == "pending_approval"
    finally:
        await store.close()


async def test_lakebase_list_sessions_reports_run_state_lifecycle() -> None:
    pool = await _pool()
    store = LakebaseSessionStore(pool)
    try:
        await store.migrate()
        await pool.execute(
            "TRUNCATE clawhouse.transcript_entries, clawhouse.runs, clawhouse.sessions CASCADE"
        )
        idle_session = await store.create_session(OWNER)

        running_session = await store.create_session(OWNER)
        await store.claim_run(running_session.id)

        error_session = await store.create_session(OWNER)
        error_run = await store.claim_run(error_session.id)
        await store.finish_run(error_session.id, error_run, "error")

        summaries = await store.list_sessions(OWNER)
    finally:
        await store.close()

    assert len(summaries) == 3
    states_by_id = {s.id: s.run_state for s in summaries}
    assert states_by_id[idle_session.id] == "idle"
    assert states_by_id[running_session.id] == "running"
    assert states_by_id[error_session.id] == "error"


async def test_lakebase_user_profile_crud() -> None:
    pool = await _pool()
    store = LakebaseSessionStore(pool)
    try:
        await store.migrate()
        await pool.execute("TRUNCATE clawhouse.user_profiles CASCADE")
        assert await store.get_user_profile(OWNER) is None

        profile = UserProfile(
            user_id=OWNER,
            assistant_name="Jarvis",
            signature_emoji="🤖",
            user_directives="Data Engineer, be concise",
            hatched=True,
        )
        saved = await store.save_user_profile(profile)
        assert saved.user_id == OWNER
        assert saved.hatched is True

        retrieved = await store.get_user_profile(OWNER)
        assert retrieved is not None
        assert retrieved.user_id == OWNER
        assert retrieved.assistant_name == "Jarvis"
        assert retrieved.signature_emoji == "🤖"
        assert retrieved.user_directives == "Data Engineer, be concise"
        assert retrieved.hatched is True
    finally:
        await store.close()


async def test_lakebase_keeps_agent_ids_and_notices_and_upgrades_old_tables() -> None:
    pool = await _pool()
    store = LakebaseSessionStore(pool)
    try:
        await store.migrate()
        # A table from before #97: no agent_id column, and the old role constraint.
        await pool.execute("ALTER TABLE clawhouse.transcript_entries DROP COLUMN agent_id")
        await pool.execute(
            """
            ALTER TABLE clawhouse.transcript_entries DROP CONSTRAINT transcript_role_known;
            ALTER TABLE clawhouse.transcript_entries ADD CONSTRAINT transcript_role_known
                CHECK (role IN ('user', 'assistant', 'tool_call', 'tool_result'));
            """
        )
        await store.migrate()
        session = await store.create_session(OWNER)
        run_id = await store.claim_run(session.id)
        entries = (
            TranscriptEntry(role="user", content="@ghost hi", agent_id="main"),
            TranscriptEntry(role="notice", content="@ghost não encontrado.", agent_id="main"),
            TranscriptEntry(role="assistant", content="hello", agent_id="fraud"),
        )
        for entry in entries:
            await store.append_entry(session.id, run_id, entry)
        await store.finish_run(session.id, run_id, "ok")

        assert await store.transcript(session.id, OWNER) == entries
    finally:
        await store.close()
