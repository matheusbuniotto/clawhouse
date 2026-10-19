"""`make demo`: a scripted, keyless model drives the whole turn UX end to end."""

import json

import pytest
from httpx import ASGITransport, AsyncClient

from clawhouse.agent import demo
from clawhouse.api.app import _production_model, create_app
from clawhouse.api.routes.sessions import NO_MODEL_DETAIL
from clawhouse.settings import settings_from_env
from clawhouse.store.store import MemorySessionStore

DEMO_ENV = {"CLAWHOUSE_DEMO": "1", "CLAWHOUSE_DEV_USER": "demo@example.com"}


@pytest.fixture(autouse=True)
def _no_typing_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(demo, "TOKEN_DELAY_SECONDS", 0)


def _client(env: dict[str, str]) -> tuple[AsyncClient, MemorySessionStore]:
    settings = settings_from_env(env)
    store = MemorySessionStore()
    app = create_app(settings=settings, model_for=_production_model(settings, env), store=store)
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    return client, store


def _events(body: str) -> list[tuple[str, dict[str, object]]]:
    events: list[tuple[str, dict[str, object]]] = []
    for block in body.strip().split("\n\n"):
        lines = block.splitlines()
        name = lines[0].removeprefix("event: ")
        events.append((name, json.loads(lines[1].removeprefix("data: "))))
    return events


async def _start_tour(client: AsyncClient) -> tuple[str, list[tuple[str, dict[str, object]]]]:
    created = await client.post("/api/sessions", json={})
    session_id = created.json()["id"]
    turn = await client.post(f"/api/sessions/{session_id}/turns", json={"message": "hi"})
    assert turn.status_code == 200
    return session_id, _events(turn.text)


def test_demo_env_offers_only_the_scripted_model_and_gates_remember() -> None:
    settings = settings_from_env({"CLAWHOUSE_DEMO": "1", "SERVING_ENDPOINT": "real-endpoint"})

    assert settings.demo is True
    assert [entry.id for entry in settings.models] == ["demo"]
    assert settings.models[0].is_default
    assert demo.DEMO_APPROVAL_TOOL in settings.sensitive_tools


def test_demo_is_off_unless_asked_for() -> None:
    assert settings_from_env({}).demo is False
    assert settings_from_env({"CLAWHOUSE_DEMO": "0"}).models == ()


async def test_first_turn_streams_text_then_a_progress_card_and_a_question() -> None:
    client, _ = _client(DEMO_ENV)
    async with client:
        models = (await client.get("/api/models")).json()["models"]
        _, events = await _start_tour(client)

    assert models == [{"id": "demo", "label": "Demo · scripted, no keys", "default": True}]
    names = [name for name, _ in events]
    assert names.count("token") > 3
    assert "progress" in names
    assert names.index("progress") < names.index("question")
    question = dict(events)["question"]
    assert question["options"] == list(demo.DEMO_OPTIONS)
    assert events[-1] == (
        "done",
        {"status": "pending_approval", "reply": "", "approval_id": question["question_id"]},
    )


async def _answer(client: AsyncClient, session_id: str, choice: str) -> dict[str, object]:
    questions = (await client.get(f"/api/sessions/{session_id}/questions")).json()
    answered = await client.post(
        f"/api/questions/{questions[0]['id']}/answer", json={"selected": [choice]}
    )
    assert answered.status_code == 200
    return answered.json()


async def _pending_approval(client: AsyncClient) -> dict[str, object]:
    pending = (await client.get("/api/approvals")).json()["pending"]
    assert len(pending) == 1
    return pending[0]


async def test_approving_the_demo_tool_writes_a_memory_and_finishes_the_tour() -> None:
    client, store = _client(DEMO_ENV)
    async with client:
        session_id, _ = await _start_tour(client)
        answered = await _answer(client, session_id, demo.DEMO_OPTIONS[0])
        assert answered["status"] == "pending_approval"
        approval = await _pending_approval(client)
        assert approval["tool_name"] == demo.DEMO_APPROVAL_TOOL

        resolved = await client.post(f"/api/approvals/{approval['id']}/approve")
        transcript = (await client.get(f"/api/sessions/{session_id}/transcript")).json()

    assert resolved.json()["status"] == "ok"
    assert "You approved" in resolved.json()["reply"]
    assert len(await store.list_memories("demo@example.com")) == 1
    progress = [
        e
        for e in transcript["entries"]
        if e["role"] == "tool_call" and e["tool_name"] == "report_progress"
    ]
    final_steps = json.loads(progress[-1]["content"])["steps"]
    assert {step["status"] for step in final_steps} == {"done"}


async def test_denying_the_demo_tool_never_runs_it() -> None:
    client, store = _client(DEMO_ENV)
    async with client:
        session_id, _ = await _start_tour(client)
        await _answer(client, session_id, demo.DEMO_OPTIONS[0])
        approval = await _pending_approval(client)
        resolved = await client.post(f"/api/approvals/{approval['id']}/deny")

    assert "You denied" in resolved.json()["reply"]
    assert await store.list_memories("demo@example.com") == ()


async def test_skipping_the_approval_finishes_without_one() -> None:
    client, _ = _client(DEMO_ENV)
    async with client:
        session_id, _ = await _start_tour(client)
        answered = await _answer(client, session_id, demo.DEMO_OPTIONS[1])
        pending = (await client.get("/api/approvals")).json()["pending"]

    assert answered["status"] == "ok"
    assert "You skipped the approval" in str(answered["reply"])
    assert pending == []


async def test_without_a_model_the_turn_says_how_to_connect_one_or_run_the_demo() -> None:
    client, _ = _client({"CLAWHOUSE_DEV_USER": "you@example.com"})
    async with client:
        created = await client.post("/api/sessions", json={})
        turn = await client.post(
            f"/api/sessions/{created.json()['id']}/turns", json={"message": "hi"}
        )

    assert turn.status_code == 503
    assert turn.json()["detail"] == NO_MODEL_DETAIL
    assert "make demo" in NO_MODEL_DETAIL
