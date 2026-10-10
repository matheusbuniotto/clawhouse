"""The chat page, behind Databricks identity, streams a turn and keeps it."""

import asyncio
import json
from collections.abc import AsyncIterator
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel

from crabriks.app import create_app
from crabriks.identity import Caller
from crabriks.model import MissingAccessToken, ModelEntry, UnknownModel
from crabriks.settings import Settings
from crabriks.store import MemorySessionStore
from crabriks.turn import BUSY_TURN, FAILED_TURN

SESSION = "11111111-1111-4111-8111-111111111111"
HEADERS = {
    "x-forwarded-email": "ada@example.com",
    "x-forwarded-access-token": "dapi-secret",
}


def _parts(messages: list[ModelMessage]) -> list[str]:
    return [part.part_kind for message in messages for part in message.parts]


async def _clock(
    messages: list[ModelMessage], info: AgentInfo
) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
    del info
    if "tool-return" not in _parts(messages):
        yield {0: DeltaToolCall(name="clock", json_args="{}", tool_call_id="call-clock")}
        return
    yield "The time is "
    yield "2026-10-10T12:00:00Z"


def _reply(text: str):
    async def stream(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str]:
        del messages, info
        yield text

    return stream


def _app(store: MemorySessionStore, model: FunctionModel):
    settings = Settings(
        dev_user=None,
        dev_token=None,
        serving_endpoint=None,
        workspace_host=None,
    )

    def model_for(caller: Caller, model_id: str | None) -> FunctionModel:
        del model_id
        if not caller.access_token:
            raise MissingAccessToken
        return model

    return create_app(settings=settings, model_for=model_for, store=store)


def _client(app: object) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")  # type: ignore[arg-type]


def _entry(model_id: str, *, default: bool = False) -> ModelEntry:
    return ModelEntry(
        id=model_id,
        label=model_id,
        provider="openai_compatible",
        model="meta-llama/llama-3.3-70b-instruct",
        base_url="https://openrouter.ai/api/v1",
        api_key_env="OPENROUTER_API_KEY",
        is_default=default,
    )


def _catalog_settings(models: tuple[ModelEntry, ...]) -> Settings:
    return Settings(
        dev_user=None,
        dev_token=None,
        serving_endpoint=None,
        workspace_host=None,
        models=models,
    )


def _events(body: str) -> list[tuple[str, dict[str, str]]]:
    frames: list[tuple[str, dict[str, str]]] = []
    for raw in body.split("\n\n"):
        if not raw.strip():
            continue
        event = "message"
        data = ""
        for line in raw.split("\n"):
            if line.startswith("event:"):
                event = line.removeprefix("event:").strip()
            elif line.startswith("data:"):
                data = line.removeprefix("data:").strip()
        frames.append((event, json.loads(data)))
    return frames


async def test_chat_page_requires_a_signed_in_user() -> None:
    app = _app(MemorySessionStore(), FunctionModel(stream_function=_reply("hi")))
    async with _client(app) as client:
        missing = await client.get("/chat")
        page = await client.get("/chat", headers=HEADERS)
        me = await client.get("/api/me", headers=HEADERS)

    assert missing.status_code == 401
    assert page.status_code == 200
    assert "Crabriks" in page.text
    assert 'src="/chat.js"' in page.text
    assert "dapi-secret" not in page.text
    assert me.json() == {"user_id": "ada@example.com"}
    assert "dapi-secret" not in me.text


async def test_the_model_picker_lists_choices_and_forwards_the_selection() -> None:
    seen: list[str | None] = []
    settings = _catalog_settings((_entry("databricks", default=True), _entry("openrouter-llama")))

    def model_for(caller: Caller, model_id: str | None) -> FunctionModel:
        del caller
        seen.append(model_id)
        return FunctionModel(stream_function=_reply("ok"))

    app = create_app(settings=settings, model_for=model_for, store=MemorySessionStore())
    async with _client(app) as client:
        catalog = await client.get("/api/models", headers=HEADERS)
        chosen = await client.post(
            f"/api/sessions/{SESSION}/turns",
            headers=HEADERS,
            json={"message": "hello", "model": "openrouter-llama"},
        )

    assert catalog.json() == {
        "models": [
            {"id": "databricks", "label": "databricks", "default": True},
            {"id": "openrouter-llama", "label": "openrouter-llama", "default": False},
        ]
    }
    assert chosen.status_code == 200
    assert seen == ["openrouter-llama"]


async def test_an_unknown_model_is_refused() -> None:
    def model_for(caller: Caller, model_id: str | None) -> FunctionModel:
        del caller
        if model_id is not None and model_id != "databricks":
            raise UnknownModel(model_id)
        return FunctionModel(stream_function=_reply("ok"))

    app = create_app(
        settings=_catalog_settings((_entry("databricks", default=True),)),
        model_for=model_for,
        store=MemorySessionStore(),
    )
    async with _client(app) as client:
        response = await client.post(
            f"/api/sessions/{SESSION}/turns",
            headers=HEADERS,
            json={"message": "hello", "model": "nope"},
        )

    assert response.status_code == 422


async def test_a_turn_streams_over_sse_and_survives_reload() -> None:
    store = MemorySessionStore()
    app = _app(store, FunctionModel(stream_function=_clock))
    async with _client(app) as client:
        response = await client.post(
            f"/api/sessions/{SESSION}/turns",
            headers=HEADERS,
            json={"message": "what time is it?"},
        )
        reloaded = await client.get(
            f"/api/sessions/{SESSION}/transcript",
            headers=HEADERS,
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = _events(response.text)
    assert [event for event, _ in events] == ["tool_call", "tool_result", "token", "token", "done"]
    assert events[-1][1] == {"status": "ok", "reply": "The time is 2026-10-10T12:00:00Z"}
    assert "dapi-secret" not in response.text
    roles = [entry["role"] for entry in reloaded.json()["entries"]]
    assert roles == ["user", "tool_call", "tool_result", "assistant"]


async def test_a_second_inflight_turn_is_rejected() -> None:
    store = MemorySessionStore()
    started = asyncio.Event()
    release = asyncio.Event()

    async def block(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str]:
        del messages, info
        started.set()
        await release.wait()
        yield "done"

    app = _app(store, FunctionModel(stream_function=block))
    async with _client(app) as client:

        async def first() -> object:
            return await client.post(
                f"/api/sessions/{SESSION}/turns",
                headers=HEADERS,
                json={"message": "first"},
            )

        task = asyncio.create_task(first())
        await started.wait()
        second = await client.post(
            f"/api/sessions/{SESSION}/turns",
            headers=HEADERS,
            json={"message": "second"},
        )
        release.set()
        first_response = await task

    assert second.status_code == 409
    assert second.json() == {"error": BUSY_TURN}
    assert first_response.status_code == 200  # type: ignore[attr-defined]


async def test_a_failed_turn_streams_an_empty_reply() -> None:
    store = MemorySessionStore()

    async def explode(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str]:
        del messages, info
        raise RuntimeError("model exploded")
        yield ""

    app = _app(store, FunctionModel(stream_function=explode))
    async with _client(app) as client:
        response = await client.post(
            f"/api/sessions/{SESSION}/turns",
            headers=HEADERS,
            json={"message": "hello"},
        )
        reloaded = await client.get(f"/api/sessions/{SESSION}/transcript", headers=HEADERS)

    events = _events(response.text)
    assert events == [("error", {"status": "error", "reply": "", "error": FAILED_TURN})]
    assert [entry["role"] for entry in reloaded.json()["entries"]] == ["user"]


async def test_a_request_without_a_user_token_does_not_claim_the_session() -> None:
    store = MemorySessionStore()
    app = _app(store, FunctionModel(stream_function=_reply("ok")))
    headers = {"x-forwarded-email": "ada@example.com"}
    async with _client(app) as client:
        refused = await client.post(
            f"/api/sessions/{SESSION}/turns",
            headers=headers,
            json={"message": "hello"},
        )
        allowed = await client.post(
            f"/api/sessions/{SESSION}/turns",
            headers=HEADERS,
            json={"message": "hello"},
        )

    assert refused.status_code == 401
    assert allowed.status_code == 200


async def test_blank_and_foreign_sessions_are_refused() -> None:
    store = MemorySessionStore()
    app = _app(store, FunctionModel(stream_function=_reply("ok")))
    async with _client(app) as client:
        blank = await client.post(
            f"/api/sessions/{SESSION}/turns",
            headers=HEADERS,
            json={"message": "   "},
        )
        await client.post(
            f"/api/sessions/{SESSION}/turns",
            headers=HEADERS,
            json={"message": "hello"},
        )
        foreign = await client.get(
            f"/api/sessions/{SESSION}/transcript",
            headers={
                "x-forwarded-email": "grace@example.com",
                "x-forwarded-access-token": "dapi-other",
            },
        )
        bad_id = await client.post(
            "/api/sessions/not-a-uuid/turns",
            headers=HEADERS,
            json={"message": "hello"},
        )

    assert blank.status_code == 422
    assert foreign.status_code == 403
    assert bad_id.status_code == 422


async def test_the_sessions_list_is_scoped_to_the_caller() -> None:
    store = MemorySessionStore()
    app = _app(store, FunctionModel(stream_function=_reply("ok")))
    other = "22222222-2222-4222-8222-222222222222"
    async with _client(app) as client:
        await client.post(
            f"/api/sessions/{SESSION}/turns", headers=HEADERS, json={"message": "first"}
        )
        await client.post(
            f"/api/sessions/{other}/turns", headers=HEADERS, json={"message": "second"}
        )
        listed = await client.get("/api/sessions", headers=HEADERS)
        grace = await client.get(
            "/api/sessions",
            headers={
                "x-forwarded-email": "grace@example.com",
                "x-forwarded-access-token": "dapi-other",
            },
        )

    body = listed.json()["sessions"]
    assert [session["title"] for session in body] == ["second", "first"]
    assert {session["id"] for session in body} == {SESSION, other}
    assert grace.json() == {"sessions": []}


async def test_starting_a_session_creates_it_for_the_caller() -> None:
    store = MemorySessionStore()
    app = _app(store, FunctionModel(stream_function=_reply("ok")))
    async with _client(app) as client:
        created = await client.post("/api/sessions", headers=HEADERS)
        listed = await client.get("/api/sessions", headers=HEADERS)

    assert created.status_code == 201
    body = created.json()
    UUID(body["id"])
    assert body["title"] == ""
    assert [session["id"] for session in listed.json()["sessions"]] == [body["id"]]


@pytest.mark.parametrize("path", ["/sessions", "/new"])
async def test_the_sessions_and_new_pages_require_a_signed_in_user(path: str) -> None:
    app = _app(MemorySessionStore(), FunctionModel(stream_function=_reply("ok")))
    async with _client(app) as client:
        missing = await client.get(path)
        page = await client.get(path, headers=HEADERS)

    assert missing.status_code == 401
    assert page.status_code == 200


@pytest.mark.parametrize("path", ["/chat.js", "/chat.css", "/sessions.js", "/new.js"])
async def test_static_assets_are_served(path: str) -> None:
    app = _app(MemorySessionStore(), FunctionModel(stream_function=_reply("ok")))
    async with _client(app) as client:
        response = await client.get(path)
    assert response.status_code == 200
    assert response.text
