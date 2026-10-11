"""Status screen and endpoint tests.

Tests cover:
1. SessionStore run state tracking per session (running / idle / error).
2. Status API (/api/status) connection/auth snapshot, session run states, and log tail link.
3. Status page (/status) and 5-screen navigation parity.
"""

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models.function import AgentInfo, FunctionModel

from crabriks.app import create_app
from crabriks.identity import Caller
from crabriks.model import MissingAccessToken
from crabriks.settings import Settings
from crabriks.store import MemorySessionStore

OWNER = "ada@example.com"
OTHER = "grace@example.com"
HEADERS = {
    "x-forwarded-email": OWNER,
    "x-forwarded-access-token": "dapi-token-ada",
}
OTHER_HEADERS = {
    "x-forwarded-email": OTHER,
    "x-forwarded-access-token": "dapi-token-grace",
}


def _reply(text: str):
    async def stream(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str]:
        del messages, info
        yield text

    return stream


def _app(
    store: MemorySessionStore,
    model: object,
    *,
    workspace_host: str | None = "https://adb-123.azuredatabricks.net",
    serving_endpoint: str | None = "databricks-meta-llama-3-3-70b-instruct",
    log_tail_url: str | None = None,
) -> object:
    settings = Settings(
        dev_user=None,
        dev_token=None,
        serving_endpoint=serving_endpoint,
        workspace_host=workspace_host,
        log_tail_url=log_tail_url,
    )

    def model_for(caller: Caller, model_id: str | None) -> object:
        del model_id
        if not caller.access_token:
            raise MissingAccessToken
        return model

    return create_app(settings=settings, model_for=model_for, store=store)  # type: ignore[arg-type]


def _client(app: object) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")  # type: ignore[arg-type]


async def test_store_tracks_session_run_state_lifecycle() -> None:
    store = MemorySessionStore()
    session = await store.create_session(OWNER)

    # 1. New session has idle run state
    summaries = await store.list_sessions(OWNER)
    assert len(summaries) == 1
    assert summaries[0].run_state == "idle"

    # 2. Claiming a run transitions session to running
    run_id = await store.claim_run(session.id)
    summaries = await store.list_sessions(OWNER)
    assert summaries[0].run_state == "running"

    # 3. Finishing with error transitions session to error
    await store.finish_run(session.id, run_id, "error")
    summaries = await store.list_sessions(OWNER)
    assert summaries[0].run_state == "error"

    # 4. Starting a new run transitions back to running
    run_id_2 = await store.claim_run(session.id)
    summaries = await store.list_sessions(OWNER)
    assert summaries[0].run_state == "running"

    # 5. Finishing with ok transitions back to idle
    await store.finish_run(session.id, run_id_2, "ok")
    summaries = await store.list_sessions(OWNER)
    assert summaries[0].run_state == "idle"


async def test_status_api_requires_authentication() -> None:
    store = MemorySessionStore()
    app = _app(store, FunctionModel(stream_function=_reply("ok")))
    async with _client(app) as client:
        resp = await client.get("/api/status")
    assert resp.status_code == 401


async def test_status_api_returns_connection_and_auth_snapshot() -> None:
    store = MemorySessionStore()
    app = _app(
        store,
        FunctionModel(stream_function=_reply("ok")),
        workspace_host="https://adb-test.azuredatabricks.net",
        serving_endpoint="databricks-meta-llama-3-3-70b-instruct",
    )
    async with _client(app) as client:
        resp = await client.get("/api/status", headers=HEADERS)

    assert resp.status_code == 200
    data = resp.json()
    assert data["auth"]["user_id"] == OWNER
    assert data["auth"]["token_present"] is True
    assert data["auth"]["auth_type"] == "oauth"
    assert data["connection"]["workspace_host"] == "https://adb-test.azuredatabricks.net"
    assert data["connection"]["serving_endpoint"] == "databricks-meta-llama-3-3-70b-instruct"
    assert data["connection"]["store_type"] == "memory"
    assert "log_tail_url" in data
    assert data["log_tail_url"] != ""


async def test_status_api_reports_run_state_per_session() -> None:
    store = MemorySessionStore()
    # Session 1: idle
    s1 = await store.create_session(OWNER)
    # Session 2: running
    s2 = await store.create_session(OWNER)
    await store.claim_run(s2.id)
    # Session 3: error
    s3 = await store.create_session(OWNER)
    r3 = await store.claim_run(s3.id)
    await store.finish_run(s3.id, r3, "error")

    # Another user's session
    s_other = await store.create_session(OTHER)
    await store.claim_run(s_other.id)

    app = _app(store, FunctionModel(stream_function=_reply("ok")))
    async with _client(app) as client:
        resp = await client.get("/api/status", headers=HEADERS)
        other_resp = await client.get("/api/status", headers=OTHER_HEADERS)

    assert resp.status_code == 200
    sessions = resp.json()["sessions"]
    # Should only contain owner's sessions (3 sessions)
    assert len(sessions) == 3
    states_by_id = {s["id"]: s["run_state"] for s in sessions}
    assert states_by_id[s1.id] == "idle"
    assert states_by_id[s2.id] == "running"
    assert states_by_id[s3.id] == "error"

    # Other user only sees their own session
    other_sessions = other_resp.json()["sessions"]
    assert len(other_sessions) == 1
    assert other_sessions[0]["id"] == s_other.id
    assert other_sessions[0]["run_state"] == "running"


async def test_status_api_log_tail_url_resolution() -> None:
    store = MemorySessionStore()
    app_custom = _app(
        store,
        FunctionModel(stream_function=_reply("ok")),
        log_tail_url="https://adb-test.azuredatabricks.net/apps/crabriks/logs",
    )
    app_default = _app(
        store,
        FunctionModel(stream_function=_reply("ok")),
        workspace_host="https://adb-test.azuredatabricks.net",
        log_tail_url=None,
    )
    async with _client(app_custom) as client:
        resp_custom = await client.get("/api/status", headers=HEADERS)
    async with _client(app_default) as client:
        resp_default = await client.get("/api/status", headers=HEADERS)

    assert resp_custom.status_code == 200
    assert (
        resp_custom.json()["log_tail_url"]
        == "https://adb-test.azuredatabricks.net/apps/crabriks/logs"
    )
    assert resp_default.status_code == 200
    assert resp_default.json()["log_tail_url"] == "https://adb-test.azuredatabricks.net/#job/logs"


async def test_status_api_dev_user_auth_snapshot() -> None:
    store = MemorySessionStore()
    settings_with_token = Settings(
        dev_user="dev@local",
        dev_token="dev-secret",
        serving_endpoint=None,
        workspace_host=None,
    )
    settings_without_token = Settings(
        dev_user="dev@local",
        dev_token=None,
        serving_endpoint=None,
        workspace_host=None,
    )
    app_with = create_app(
        settings=settings_with_token,
        model_for=lambda caller, model_id: FunctionModel(stream_function=_reply("ok")),
        store=store,
    )
    app_without = create_app(
        settings=settings_without_token,
        model_for=lambda caller, model_id: FunctionModel(stream_function=_reply("ok")),
        store=store,
    )
    async with _client(app_with) as client:
        resp_with = await client.get("/api/status")
    async with _client(app_without) as client:
        resp_without = await client.get("/api/status")

    assert resp_with.status_code == 200
    data_with = resp_with.json()
    assert data_with["auth"]["user_id"] == "dev@local"
    assert data_with["auth"]["auth_type"] == "dev"
    assert data_with["auth"]["token_present"] is True

    assert resp_without.status_code == 200
    data_without = resp_without.json()
    assert data_without["auth"]["user_id"] == "dev@local"
    assert data_without["auth"]["auth_type"] == "dev"
    assert data_without["auth"]["token_present"] is False


async def test_status_page_requires_auth_and_serves_html() -> None:
    store = MemorySessionStore()
    app = _app(store, FunctionModel(stream_function=_reply("ok")))
    async with _client(app) as client:
        unauth = await client.get("/status")
        auth = await client.get("/status", headers=HEADERS)

    assert unauth.status_code == 401
    assert auth.status_code == 200
    assert "Crabriks" in auth.text
    assert "Status" in auth.text
    assert 'src="/status.js"' in auth.text
    assert 'id="log-tail-link"' in auth.text


async def test_status_asset_route() -> None:
    store = MemorySessionStore()
    app = _app(store, FunctionModel(stream_function=_reply("ok")))
    async with _client(app) as client:
        resp = await client.get("/status.js")

    assert resp.status_code == 200
    assert "javascript" in resp.headers.get("content-type", "")


@pytest.mark.parametrize("path", ["/chat", "/sessions", "/new", "/approvals", "/status"])
async def test_navigation_parity_across_all_five_screens(path: str) -> None:
    store = MemorySessionStore()
    app = _app(store, FunctionModel(stream_function=_reply("ok")))
    async with _client(app) as client:
        resp = await client.get(path, headers=HEADERS)

    assert resp.status_code == 200
    for target in ["/chat", "/sessions", "/new", "/approvals", "/status"]:
        assert f'href="{target}"' in resp.text
