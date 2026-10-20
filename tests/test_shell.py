"""The Lovable SPA shell: same document on every app route, hashed assets, cache headers."""

import re
from collections.abc import AsyncIterator

from httpx import ASGITransport, AsyncClient
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models.function import AgentInfo, FunctionModel

from clawhouse.agent.model import MissingAccessToken
from clawhouse.api.app import create_app
from clawhouse.api.identity import Caller
from clawhouse.settings import Settings
from clawhouse.store.store import MemorySessionStore

OWNER = "ada@example.com"
HEADERS = {"x-forwarded-email": OWNER, "x-forwarded-access-token": "tok_" + "ada"}
PAGES = ("/chat", "/sessions", "/agents", "/new", "/approvals", "/status", "/jobs")


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
    assert "Clawhouse" in documents[0]
    assert 'href="/agents"' in documents[0]
    assert "/assets/" in documents[0]


async def test_assets_ask_the_browser_to_revalidate() -> None:
    async with _client(_app()) as client:
        page = await client.get("/chat", headers=HEADERS)
        assert page.status_code == 200
        assert page.headers["cache-control"] == "no-cache"
        match = re.search(r'href="(/assets/styles-[^"]+\.css)"', page.text)
        assert match is not None
        asset = await client.get(match.group(1), headers=HEADERS)
        assert asset.status_code == 200
        assert asset.headers["cache-control"] == "no-cache"


async def test_shell_chrome_is_present_on_every_route() -> None:
    async with _client(_app()) as client:
        for path in PAGES:
            text = await _page(client, path)
            assert "New session" in text
            assert "Filter sessions" in text
