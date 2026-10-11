"""The persistent shell: chrome on every route, deep links, and rail endpoints."""

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
HEADERS = {"x-forwarded-email": OWNER, "x-forwarded-access-token": "tok_" + "ada"}
PAGES = ("/chat", "/sessions", "/new", "/approvals", "/status")


def _reply(text: str):
    async def stream(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str]:
        del messages, info
        yield text

    return stream


def _app() -> object:
    settings = Settings(
        dev_user=None,
        dev_token=None,
        serving_endpoint=None,
        workspace_host=None,
    )

    def model_for(caller: Caller, model_id: str | None) -> object:
        del model_id
        if not caller.access_token:
            raise MissingAccessToken
        return FunctionModel(stream_function=_reply("ok"))

    return create_app(settings=settings, model_for=model_for, store=MemorySessionStore())  # type: ignore[arg-type]


def _client(app: object) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")  # type: ignore[arg-type]


async def _page(client: AsyncClient, path: str) -> str:
    response = await client.get(path, headers=HEADERS)
    assert response.status_code == 200
    return response.text


async def test_every_route_serves_the_same_shell_document() -> None:
    async with _client(_app()) as client:
        documents = [await _page(client, path) for path in PAGES]

    assert len(set(documents)) == 1


async def test_assets_ask_the_browser_to_revalidate() -> None:
    async with _client(_app()) as client:
        for path in ("/chat", "/tokens.css", "/shell.css", "/boot.js", "/chat.js"):
            response = await client.get(path, headers=HEADERS)
            assert response.status_code == 200
            assert response.headers["cache-control"] == "no-cache"


async def test_shell_chrome_is_present_on_every_route() -> None:
    async with _client(_app()) as client:
        for path in PAGES:
            text = await _page(client, path)
            assert 'id="shell"' in text
            assert 'id="rail"' in text
            assert 'id="rail-sessions"' in text
            assert 'id="rail-user"' in text
            assert 'id="theme-toggle"' in text
            assert 'id="screen"' in text
            assert 'src="/boot.js"' in text


async def test_deep_links_serve_full_documents() -> None:
    async with _client(_app()) as client:
        for path in PAGES:
            text = await _page(client, path)
            assert text.lstrip().lower().startswith("<!doctype html>")
            assert text.rstrip().endswith("</html>")


async def test_in_place_switching_uses_the_session_endpoints() -> None:
    async with _client(_app()) as client:
        created = await client.post("/api/sessions", headers=HEADERS)
        session_id = created.json()["id"]

        listed = await client.get("/api/sessions", headers=HEADERS)
        assert session_id in [session["id"] for session in listed.json()["sessions"]]

        turn = await client.post(
            f"/api/sessions/{session_id}/turns",
            headers=HEADERS,
            json={"message": "hello"},
        )
        assert turn.status_code == 200

        transcript = await client.get(f"/api/sessions/{session_id}/transcript", headers=HEADERS)
        assert [entry["role"] for entry in transcript.json()["entries"]] == ["user", "assistant"]

        status = await client.get("/api/status", headers=HEADERS)
        assert status.status_code == 200
        assert status.json()["sessions"][0]["id"] == session_id


@pytest.mark.parametrize("path", PAGES)
async def test_every_route_requires_a_signed_in_user(path: str) -> None:
    async with _client(_app()) as client:
        missing = await client.get(path)

    assert missing.status_code == 401
