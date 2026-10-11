"""The design-token layer and the four stylesheets, observed through the app's routes."""

import re
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

HEADERS = {
    "x-forwarded-email": "ada@example.com",
    "x-forwarded-access-token": "tok_" + "ada",
}

PAGES = ("/chat", "/sessions", "/new", "/approvals", "/status")
SHEETS = ("/tokens.css", "/shell.css", "/transcript.css", "/screens.css")
COMPONENT_SHEETS = ("/shell.css", "/transcript.css", "/screens.css")

DARK_TOKENS: dict[str, str] = {
    "--bg": "#0e1015",
    "--bg-accent": "#13151b",
    "--card": "#161920",
    "--bg-elevated": "#191c24",
    "--popover": "#191c24",
    "--bg-hover": "#1f2330",
    "--bg-muted": "#1f2330",
    "--border": "#1e2028",
    "--border-strong": "#2e3040",
    "--border-hover": "#3e4050",
    "--text": "#bcbcc0",
    "--text-strong": "#f4f4f5",
    "--muted": "#8b8b94",
    "--accent": "#ff5c5c",
    "--accent-hover": "#ff7070",
    "--accent-subtle": "rgb(255 92 92 / 10%)",
    "--accent-ink": "#fff7f2",
    "--primary": "#d13c3c",
    "--ring": "#ff5c5c",
    "--focus-ring": "0 0 0 2px var(--bg), 0 0 0 4px var(--ring)",
    "--ok": "#22c55e",
    "--ok-subtle": "rgb(34 197 94 / 8%)",
    "--warn": "#f59e0b",
    "--warn-subtle": "rgb(245 158 11 / 8%)",
    "--danger": "#f87171",
    "--danger-subtle": "rgb(248 113 113 / 8%)",
    "--info": "#60a5fa",
    "--info-subtle": "rgb(96 165 250 / 8%)",
    "--syntax-keyword": "#c792ea",
    "--syntax-string": "#c3e88d",
    "--syntax-number": "#f78c6c",
    "--syntax-comment": "#8b8b94",
    "--syntax-key": "#82aaff",
    "--syntax-literal": "#ffcb6b",
    "--syntax-variable": "#89ddff",
    "--radius-sm": "6px",
    "--radius-md": "10px",
    "--radius-lg": "14px",
    "--radius-xl": "20px",
    "--radius-full": "9999px",
    "--radius": "var(--radius-md)",
    "--font-size-xs": "11px",
    "--font-size-sm": "12px",
    "--font-size-md": "14px",
    "--font-size-lg": "16px",
    "--font-body": '"IBM Plex Sans", "Segoe UI", system-ui, sans-serif',
    "--font-chat": "var(--font-body)",
    "--font-mono": '"IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo, monospace',
    "--shadow-sm": "0 1px 2px rgb(0 0 0 / 24%)",
    "--shadow": "0 8px 24px rgb(0 0 0 / 32%)",
    "--shadow-lg": "0 16px 40px rgb(0 0 0 / 40%)",
    "--duration-fast": "120ms",
    "--duration": "180ms",
    "--ease": "cubic-bezier(0.2, 0, 0, 1)",
}

LIGHT_TOKENS: dict[str, str] = {
    "--bg": "#f3efe6",
    "--bg-accent": "#ece5d9",
    "--card": "#fffdf9",
    "--bg-elevated": "#fffdf9",
    "--popover": "#fffdf9",
    "--bg-hover": "#efe8dc",
    "--bg-muted": "#efe8dc",
    "--border": "#e2d9cc",
    "--border-strong": "#cdc0ad",
    "--border-hover": "#b5a48d",
    "--text": "#463f38",
    "--text-strong": "#1f1a14",
    "--muted": "#6d645b",
    "--accent": "#c1352f",
    "--accent-hover": "#a02a26",
    "--accent-subtle": "rgb(193 53 47 / 10%)",
    "--accent-ink": "#fff7f2",
    "--primary": "#c1352f",
    "--ring": "#c1352f",
    "--ok": "#15803d",
    "--ok-subtle": "rgb(21 128 61 / 8%)",
    "--warn": "#b45309",
    "--warn-subtle": "rgb(180 83 9 / 8%)",
    "--danger": "#b91c1c",
    "--danger-subtle": "rgb(185 28 28 / 8%)",
    "--info": "#1d4ed8",
    "--info-subtle": "rgb(29 78 216 / 8%)",
    "--syntax-keyword": "#7c3aed",
    "--syntax-string": "#15803d",
    "--syntax-number": "#b45309",
    "--syntax-comment": "#6d645b",
    "--syntax-key": "#1d4ed8",
    "--syntax-literal": "#b45309",
    "--syntax-variable": "#0e7490",
    "--shadow-sm": "0 1px 2px rgb(31 26 20 / 6%)",
    "--shadow": "0 8px 24px rgb(31 26 20 / 8%)",
    "--shadow-lg": "0 16px 40px rgb(31 26 20 / 10%)",
}


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


def _rule(css: str, selector: str) -> str:
    match = re.search(re.escape(selector) + r"\s*\{([^{}]*)\}", css)
    assert match is not None, f"no rule for {selector}"
    return match.group(1)


def _tokens(block: str) -> dict[str, str]:
    tokens: dict[str, str] = {}
    for line in block.splitlines():
        stripped = line.strip()
        if not stripped.startswith("--") or ":" not in stripped:
            continue
        name, _, value = stripped.partition(":")
        tokens[name.strip()] = value.strip().rstrip(";").strip()
    return tokens


async def test_tokens_stylesheet_pins_the_dark_contract() -> None:
    async with _client(_app()) as client:
        response = await client.get("/tokens.css")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/css")
    root = _rule(response.text, ":root")
    assert _tokens(root) == DARK_TOKENS
    assert "color-scheme: dark" in root


async def test_light_mode_is_a_pure_token_override() -> None:
    async with _client(_app()) as client:
        response = await client.get("/tokens.css")

    css = response.text
    assert "prefers-color-scheme" not in css
    assert css.count('data-theme-mode="light"') == 1
    assert 'data-theme-mode="dark"' not in css
    light = _rule(css, ':root[data-theme-mode="light"]')
    assert _tokens(light) == LIGHT_TOKENS
    assert "color-scheme: light" in light


async def test_the_default_document_is_dark() -> None:
    async with _client(_app()) as client:
        page = await client.get("/chat", headers=HEADERS)

    assert page.status_code == 200
    assert 'data-theme-mode="light"' not in page.text
    assert 'href="/tokens.css"' in page.text


@pytest.mark.parametrize("page", PAGES)
async def test_every_screen_links_all_four_stylesheets(page: str) -> None:
    async with _client(_app()) as client:
        response = await client.get(page, headers=HEADERS)

    assert response.status_code == 200
    for sheet in SHEETS:
        assert f'href="{sheet}"' in response.text


@pytest.mark.parametrize("sheet", SHEETS)
async def test_every_stylesheet_is_served(sheet: str) -> None:
    async with _client(_app()) as client:
        response = await client.get(sheet)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/css")
    assert response.text.strip()


def _declaration_text(css: str) -> str:
    return " ".join(re.findall(r"\{([^{}]*)\}", css))


def _values(declarations: str, prop: str) -> list[str]:
    return [value.strip() for value in re.findall(rf"{prop}:\s*([^;}}]+)", declarations)]


@pytest.mark.parametrize("sheet", COMPONENT_SHEETS)
async def test_component_sheets_resolve_style_through_tokens(sheet: str) -> None:
    async with _client(_app()) as client:
        response = await client.get(sheet)

    declarations = _declaration_text(response.text)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", declarations), "literal hex colour"
    assert not re.search(r"\brgba?\(", declarations), "literal colour function"
    for radius in _values(declarations, "border-radius"):
        assert radius.startswith("var("), f"literal radius: {radius}"
    for family in _values(declarations, "font-family"):
        assert family.startswith("var("), f"literal font family: {family}"


SCREEN_SELECTORS = (
    ".status-section",
    ".status-card",
    ".status-grid",
    ".status-badge.running",
    ".status-badge.idle",
    ".status-badge.error",
    ".status-badge.approved",
    ".status-badge.denied",
    ".approvals-section",
    ".approvals-list",
    ".approval-card",
    ".approval-header",
    ".approval-actions",
    ".tool-name",
    ".args-json",
    ".btn-approve",
    ".btn-deny",
    ".approval-history-row",
    ".resolver",
)


async def test_screens_stylesheet_covers_approvals_and_status() -> None:
    async with _client(_app()) as client:
        response = await client.get("/screens.css")

    css = response.text
    for selector in SCREEN_SELECTORS:
        assert selector in css, f"missing rule for {selector}"
