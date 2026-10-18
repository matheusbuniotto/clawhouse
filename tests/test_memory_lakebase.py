"""Lakebase memory table and transcript FTS."""

import os

import asyncpg
import pytest

from clawhouse.store.shapes import TranscriptEntry
from clawhouse.store.store import LakebaseSessionStore

pytestmark = pytest.mark.skipif(
    not os.environ.get("CLAWHOUSE_TEST_DATABASE_URL"),
    reason="CLAWHOUSE_TEST_DATABASE_URL is not set",
)


async def _pool() -> asyncpg.Pool:
    pool = await asyncpg.create_pool(os.environ["CLAWHOUSE_TEST_DATABASE_URL"])
    if pool is None:
        raise RuntimeError("postgres pool was not created")
    return pool


@pytest.mark.asyncio
async def test_memory_entries_and_transcript_search_idx() -> None:
    pool = await _pool()
    store = LakebaseSessionStore(pool)
    try:
        await store.migrate()
        columns = await pool.fetch(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'clawhouse' AND table_name = 'memory_entries'
            """
        )
        index = await pool.fetchval(
            """
            SELECT indexdef FROM pg_indexes
            WHERE schemaname = 'clawhouse' AND indexname = 'transcript_search_idx'
            """
        )
    finally:
        await store.close()
    names = {row["column_name"] for row in columns}
    assert names >= {"id", "owner_id", "text", "source_session_id", "table_fqn", "created_at"}
    assert index is not None
    assert "gin" in index.lower()
    assert "to_tsvector('english', content)" in index


@pytest.mark.asyncio
async def test_fts_returns_owner_match_only() -> None:
    pool = await _pool()
    store = LakebaseSessionStore(pool)
    try:
        await store.migrate()
        own = await store.create_session("ada@example.com")
        other = await store.create_session("grace@example.com")
        await store.open_session(own.id, "ada@example.com")
        own_run = await store.claim_run(own.id)
        await store.append_entry(
            own.id,
            own_run,
            TranscriptEntry(role="user", content="revenue is net of refunds"),
        )
        await store.finish_run(own.id, own_run, "ok")
        other_run = await store.claim_run(other.id)
        await store.append_entry(
            other.id,
            other_run,
            TranscriptEntry(role="user", content="revenue is net of refunds"),
        )
        hits = await store.search_transcripts("ada@example.com", "refunds", 10)
    finally:
        await store.close()
    assert hits
    assert all(hit.session_id == own.id for hit in hits)
    assert "refunds" in hits[0].excerpt
    assert all(hit.session_id != other.id for hit in hits)
