"""Lovable UI stylesheet contract served from the SPA bundle."""

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

HEADERS = {
    "x-forwarded-email": "ada@example.com",
    "x-forwarded-access-token": "tok_" + "ada",
}

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


def _main_stylesheet_href(html: str) -> str:
    match = re.search(r'href="(/assets/styles-[^"]+\.css)"', html)
    assert match is not None, "shell missing main stylesheet link"
    return match.group(1)


async def test_main_stylesheet_defines_theme_tokens() -> None:
    async with _client(_app()) as client:
        page = await client.get("/chat", headers=HEADERS)
        href = _main_stylesheet_href(page.text)
        css = await client.get(href, headers=HEADERS)

    assert css.status_code == 200
    assert css.headers["content-type"].startswith("text/css")
    assert "--primary:" in css.text
    assert "--background:" in css.text


async def test_every_screen_links_the_bundled_stylesheet() -> None:
    async with _client(_app()) as client:
        for path in PAGES:
            page = await client.get(path, headers=HEADERS)
            assert page.status_code == 200
            assert "/assets/styles-" in page.text
