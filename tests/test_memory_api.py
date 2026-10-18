"""Memory and transcript search routes."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic_ai.models.function import FunctionModel

from clawhouse.api.app import create_app
from clawhouse.settings import Settings
from clawhouse.store.shapes import TranscriptEntry
from clawhouse.store.store import MemorySessionStore

OWNER = "ada@example.com"
OTHER = "grace@example.com"
HEADERS = {"x-forwarded-email": OWNER, "x-forwarded-access-token": "tok"}


def _app(store: MemorySessionStore, tmp_path: Path):
    async def _stream(_msgs: object, _info: object) -> AsyncIterator[str]:
        if False:
            yield ""

    return create_app(
        store=store,
        settings=Settings(
            dev_user=None,
            dev_token=None,
            serving_endpoint=None,
            workspace_host=None,
            agent_root=tmp_path,
        ),
        model_for=lambda _c, _m: FunctionModel(stream_function=_stream),  # type: ignore[arg-type]
    )


async def _seed(store: MemorySessionStore) -> tuple[str, str]:
    clock = {"n": 0}

    def now() -> datetime:
        clock["n"] += 1
        return datetime(2026, 10, 12, 12, 0, clock["n"], tzinfo=UTC)

    store._now = now  # type: ignore[method-assign]
    own = await store.create_session(OWNER)
    other = await store.create_session(OTHER)
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
    await store.finish_run(other.id, other_run, "ok")
    own_run_2 = await store.claim_run(own.id)
    await store.append_entry(
        own.id, own_run_2, TranscriptEntry(role="assistant", content="older refunds note")
    )
    return own.id, other.id


@pytest.mark.asyncio
async def test_search_returns_at_most_limit_newest_first(tmp_path: Path) -> None:
    store = MemorySessionStore()
    session_id, _other = await _seed(store)
    async with AsyncClient(
        transport=ASGITransport(app=_app(store, tmp_path)), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/search", params={"q": "refunds", "limit": 2}, headers=HEADERS
        )
    assert response.status_code == 200
    results = response.json()["results"]
    assert len(results) <= 2
    assert list(results[0]) == ["session_id", "role", "excerpt", "created_at"] or set(
        results[0]
    ) >= {
        "session_id",
        "role",
        "excerpt",
        "created_at",
    }
    assert all(len(row["excerpt"]) <= 240 for row in results)
    assert results[0]["session_id"] == session_id
    assert results[0]["created_at"] >= results[-1]["created_at"]


@pytest.mark.asyncio
async def test_search_excludes_other_owners(tmp_path: Path) -> None:
    store = MemorySessionStore()
    own, other = await _seed(store)
    async with AsyncClient(
        transport=ASGITransport(app=_app(store, tmp_path)), base_url="http://test"
    ) as client:
        response = await client.get("/api/search", params={"q": "refunds"}, headers=HEADERS)
    results = response.json()["results"]
    ids = {row["session_id"] for row in results}
    assert store._sessions[own].owner_id == OWNER
    assert store._sessions[other].owner_id == OTHER
    assert own in ids
    assert other not in ids
    assert all(store._sessions[row["session_id"]].owner_id == OWNER for row in results)


@pytest.mark.asyncio
async def test_search_empty_q_returns_422(tmp_path: Path) -> None:
    store = MemorySessionStore()
    async with AsyncClient(
        transport=ASGITransport(app=_app(store, tmp_path)), base_url="http://test"
    ) as client:
        empty = await client.get("/api/search", params={"q": ""}, headers=HEADERS)
        blank = await client.get("/api/search", params={"q": " "}, headers=HEADERS)
    assert empty.status_code == 422
    assert blank.status_code == 422


@pytest.mark.asyncio
async def test_search_no_match_returns_empty_results(tmp_path: Path) -> None:
    store = MemorySessionStore()
    await _seed(store)
    async with AsyncClient(
        transport=ASGITransport(app=_app(store, tmp_path)), base_url="http://test"
    ) as client:
        response = await client.get("/api/search", params={"q": "missing-term"}, headers=HEADERS)
    assert response.status_code == 200
    assert response.json()["results"] == []


@pytest.mark.asyncio
async def test_memory_routes_without_identity_return_401(tmp_path: Path) -> None:
    store = MemorySessionStore()
    async with AsyncClient(
        transport=ASGITransport(app=_app(store, tmp_path)), base_url="http://test"
    ) as client:
        responses = [
            await client.get("/api/search", params={"q": "refunds"}),
            await client.get("/api/memory"),
            await client.post("/api/memory", json={"text": "fact"}),
            await client.delete("/api/memory/00000000-0000-4000-8000-000000000001"),
        ]
    assert [response.status_code for response in responses] == [401, 401, 401, 401]


@pytest.mark.asyncio
async def test_post_memory_returns_201_and_persists_owner(tmp_path: Path) -> None:
    store = MemorySessionStore()
    session = await store.create_session(OWNER)
    async with AsyncClient(
        transport=ASGITransport(app=_app(store, tmp_path)), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/memory",
            headers=HEADERS,
            json={
                "text": "net of refunds",
                "source_session_id": session.id,
                "table_fqn": "main.sales.orders",
            },
        )
    assert response.status_code == 201
    body = response.json()
    assert body["text"] == "net of refunds"
    assert body["id"]
    assert body["created_at"]
    stored = await store.list_memories(OWNER)
    assert stored[0].owner_id == OWNER
    assert stored[0].source_session_id == session.id
    assert stored[0].table_fqn == "main.sales.orders"


@pytest.mark.asyncio
async def test_post_memory_foreign_session_returns_404(tmp_path: Path) -> None:
    store = MemorySessionStore()
    other = await store.create_session(OTHER)
    async with AsyncClient(
        transport=ASGITransport(app=_app(store, tmp_path)), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/memory",
            headers=HEADERS,
            json={"text": "fact", "source_session_id": other.id},
        )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_post_memory_blank_text_returns_422(tmp_path: Path) -> None:
    store = MemorySessionStore()
    async with AsyncClient(
        transport=ASGITransport(app=_app(store, tmp_path)), base_url="http://test"
    ) as client:
        missing = await client.post("/api/memory", headers=HEADERS, json={})
        blank = await client.post("/api/memory", headers=HEADERS, json={"text": "  "})
    assert missing.status_code == 422
    assert blank.status_code == 422


@pytest.mark.asyncio
async def test_delete_owned_memory_returns_204_and_omits_it(tmp_path: Path) -> None:
    store = MemorySessionStore()
    async with AsyncClient(
        transport=ASGITransport(app=_app(store, tmp_path)), base_url="http://test"
    ) as client:
        created = await client.post("/api/memory", headers=HEADERS, json={"text": "keep"})
        memory_id = created.json()["id"]
        deleted = await client.delete(f"/api/memory/{memory_id}", headers=HEADERS)
        listed = await client.get("/api/memory", headers=HEADERS)
    assert deleted.status_code == 204
    assert memory_id not in {row["id"] for row in listed.json()["entries"]}


@pytest.mark.asyncio
async def test_delete_missing_memory_returns_404(tmp_path: Path) -> None:
    store = MemorySessionStore()
    async with AsyncClient(
        transport=ASGITransport(app=_app(store, tmp_path)), base_url="http://test"
    ) as client:
        missing = await client.delete(
            "/api/memory/00000000-0000-4000-8000-000000000099",
            headers=HEADERS,
        )
        foreign = await store.save_memory(OTHER, "hidden", None, None)
        other_owner = await client.delete(f"/api/memory/{foreign.id}", headers=HEADERS)
    assert missing.status_code == 404
    assert other_owner.status_code == 404
    assert (await store.list_memories(OTHER))[0].id == foreign.id


@pytest.mark.asyncio
async def test_get_memory_returns_only_caller_entries(tmp_path: Path) -> None:
    store = MemorySessionStore()
    await store.save_memory(OTHER, "hidden", None, None)
    async with AsyncClient(
        transport=ASGITransport(app=_app(store, tmp_path)), base_url="http://test"
    ) as client:
        await client.post("/api/memory", headers=HEADERS, json={"text": "visible"})
        response = await client.get("/api/memory", headers=HEADERS)
    assert response.status_code == 200
    entries = response.json()["entries"]
    assert [row["text"] for row in entries] == ["visible"]
    assert set(entries[0]) >= {"id", "text", "table_fqn", "source_session_id", "created_at"}
