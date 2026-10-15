"""A turn outlives its request (#97 browser bugs): reloads must not leave a session stuck."""

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from httpx import ASGITransport, AsyncClient
from pydantic_ai.messages import ModelMessage, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel

from clawhouse.agent.turn import TurnContext, cancel_turn, iter_turn, run_turn
from clawhouse.api.app import create_app
from clawhouse.api.identity import Caller
from clawhouse.settings import Settings
from clawhouse.store.store import MemorySessionStore

SESSION = "88888888-8888-4888-8888-888888888888"
OWNER = "ada@example.com"
HEADERS = {"x-forwarded-email": OWNER, "x-forwarded-access-token": "dapi-secret"}


def _steps(done: int) -> str:
    labels = ["Ler", "Calcular", "Gerar"]
    steps = [
        {"label": x, "status": "done" if i < done else "running"} for i, x in enumerate(labels)
    ]
    return json.dumps({"task_id": "t", "steps": steps})


class _Slow:
    """Reports progress, waits on `gate`, reports the final state, then answers."""

    def __init__(self) -> None:
        self.gate = asyncio.Event()

    async def stream(
        self, messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        del info
        returns = sum(isinstance(p, ToolReturnPart) for m in messages for p in m.parts)
        if returns == 0:
            yield {0: DeltaToolCall(name="report_progress", json_args=_steps(2), tool_call_id="a")}
            return
        if returns == 1:
            await self.gate.wait()
            yield {0: DeltaToolCall(name="report_progress", json_args=_steps(3), tool_call_id="b")}
            return
        yield "pronto"


class _Echo:
    async def stream(self, messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str]:
        del messages, info
        yield "oi"


def _ctx(store: MemorySessionStore, stream: Any) -> TurnContext:
    return TurnContext(
        owner_id=OWNER,
        store=store,
        model=FunctionModel(stream_function=stream, model_name="test-model"),
        now=lambda: datetime.now(UTC),
    )


async def _state(store: MemorySessionStore) -> str:
    return next(s.run_state for s in await store.list_sessions(OWNER) if s.id == SESSION)


async def _settle(store: MemorySessionStore) -> None:
    for _ in range(200):
        if await _state(store) != "running":
            return
        await asyncio.sleep(0.01)
    raise AssertionError("run never finished")


async def test_dropping_the_stream_lets_the_turn_finish_and_persist() -> None:
    store = MemorySessionStore()
    slow = _Slow()
    stream = iter_turn(SESSION, "relatório", ctx=_ctx(store, slow.stream))
    await anext(stream)
    await stream.aclose()  # the browser reloaded
    assert await _state(store) == "running"

    slow.gate.set()
    await _settle(store)

    entries = await store.transcript(SESSION, OWNER)
    progress = [e for e in entries if e.role == "tool_call" and e.tool_name == "report_progress"]
    assert json.loads(progress[-1].content)["steps"][-1]["status"] == "done"
    assert entries[-1].role == "assistant" and entries[-1].content == "pronto"
    again = await run_turn(SESSION, "oi", ctx=_ctx(store, _Echo().stream))
    assert again.status == "ok"


async def test_cancel_turn_stops_the_run_and_frees_the_session() -> None:
    store = MemorySessionStore()
    slow = _Slow()
    stream = iter_turn(SESSION, "relatório", ctx=_ctx(store, slow.stream))
    await anext(stream)
    await stream.aclose()

    assert await cancel_turn(SESSION) is True
    assert await _state(store) != "running"
    again = await run_turn(SESSION, "oi", ctx=_ctx(store, _Echo().stream))
    assert again.status == "ok"
    assert await cancel_turn(SESSION) is False


async def test_assistant_rows_keep_the_model_for_reloaded_headers() -> None:
    store = MemorySessionStore()
    await run_turn(SESSION, "oi", ctx=_ctx(store, _Echo().stream))

    settings = Settings(dev_user=None, dev_token=None, serving_endpoint=None, workspace_host=None)

    def model_for(caller: Caller, model_id: str | None) -> Any:
        del caller, model_id

    app = create_app(settings=settings, model_for=model_for, store=store)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t", headers=HEADERS) as client:
        body = (await client.get(f"/api/sessions/{SESSION}/transcript")).json()

    assert body["run_state"] == "idle"
    by_role = {e["role"]: e for e in body["entries"]}
    assert by_role["assistant"]["model"] == "test-model"
    assert by_role["user"]["model"] is None
