"""Tests for Clawhouse runtime telemetry, OTel GenAI spans, and Logfire setup."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import patch

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic_ai.messages import ModelMessage, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel

from clawhouse.agent.turn import TurnContext, run_turn
from clawhouse.api.app import create_app
from clawhouse.settings import Settings, settings_from_env
from clawhouse.store.store import MemorySessionStore
from clawhouse.telemetry import (
    parse_otlp_headers,
    setup_telemetry,
)

SESSION = "11111111-1111-4111-8111-111111111111"
OWNER = "ada@example.com"


@pytest.fixture
def memory_exporter() -> Iterator[tuple[TracerProvider, InMemorySpanExporter]]:
    provider = trace.get_tracer_provider()
    if not isinstance(provider, TracerProvider):
        provider = TracerProvider()
        trace.set_tracer_provider(provider)
    exporter = InMemorySpanExporter()
    processor = SimpleSpanProcessor(exporter)
    provider.add_span_processor(processor)
    yield provider, exporter
    exporter.clear()


class _Echo:
    async def stream(self, messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str]:
        del messages, info
        yield "Hello telemetry!"


class _FailingModel:
    async def stream(self, messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str]:
        del messages, info
        raise RuntimeError("simulated model explosion")
        yield "never"


class _ToolCaller:
    async def stream(
        self, messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        del info
        returns = sum(isinstance(p, ToolReturnPart) for m in messages for p in m.parts)
        if returns == 0:
            yield {0: DeltaToolCall(name="clock", json_args="{}", tool_call_id="call_1")}
            return
        yield "tool executed"


def _make_ctx(store: MemorySessionStore, model_handler: Any, **kwargs: Any) -> TurnContext:
    defaults: dict[str, Any] = {
        "store": store,
        "owner_id": OWNER,
        "model": FunctionModel(stream_function=model_handler.stream),
        "now": lambda: datetime(2026, 10, 16, 12, 0, 0, tzinfo=UTC),
    }
    defaults.update(kwargs)
    return TurnContext(**defaults)


# ---------------------------------------------------------------------------
# S1: Telemetry Settings and Setup Seam (C1 - C5)
# ---------------------------------------------------------------------------


def test_settings_telemetry_defaults_and_env() -> None:
    # Default without telemetry env
    empty = settings_from_env({})
    assert empty.telemetry_enabled is True
    assert empty.otel_endpoint is None
    assert empty.otel_headers is None
    assert empty.logfire_token is None

    # Populated from standard env keys
    env = {
        "OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4318/v1/traces",
        "OTEL_EXPORTER_OTLP_HEADERS": "Authorization=Bearer test_token,x-tenant=123",
        "LOGFIRE_TOKEN": "logfire_secret_abc",
        "CLAWHOUSE_TELEMETRY": "1",
    }
    s = settings_from_env(env)
    assert s.telemetry_enabled is True
    assert s.otel_endpoint == "http://localhost:4318/v1/traces"
    assert s.otel_headers == "Authorization=Bearer test_token,x-tenant=123"
    assert s.logfire_token == "logfire_secret_abc"


@pytest.mark.parametrize("val", ["0", "false", "no", "False", "NO", "0 "])
def test_settings_telemetry_disabled(val: str) -> None:
    s = settings_from_env({"CLAWHOUSE_TELEMETRY": val})
    assert s.telemetry_enabled is False


def test_setup_telemetry_disabled_noop() -> None:
    settings = Settings(
        dev_user=None,
        dev_token=None,
        serving_endpoint=None,
        workspace_host=None,
        telemetry_enabled=False,
    )
    with (
        patch("clawhouse.telemetry.logfire.configure") as mock_logfire,
        patch("clawhouse.telemetry.Agent.instrument_all") as mock_instrument,
    ):
        setup_telemetry(settings)
        mock_logfire.assert_not_called()
        mock_instrument.assert_not_called()


def test_setup_telemetry_logfire_token() -> None:
    settings = Settings(
        dev_user=None,
        dev_token=None,
        serving_endpoint=None,
        workspace_host=None,
        telemetry_enabled=True,
        logfire_token="secret_token",
    )
    with (
        patch("clawhouse.telemetry.logfire.configure") as mock_logfire,
        patch("clawhouse.telemetry.Agent.instrument_all") as mock_instrument,
    ):
        setup_telemetry(settings)
        mock_logfire.assert_called_once_with(
            send_to_logfire="if-token-present",
            token="secret_token",
            service_name="clawhouse",
        )
        mock_instrument.assert_called_once_with(True)


def test_setup_telemetry_otlp_endpoint() -> None:
    settings = Settings(
        dev_user=None,
        dev_token=None,
        serving_endpoint=None,
        workspace_host=None,
        telemetry_enabled=True,
        otel_endpoint="http://collector:4318/v1/traces",
        otel_headers="Authorization=Bearer abc,Key=Value",
    )
    assert parse_otlp_headers(settings.otel_headers) == {
        "Authorization": "Bearer abc",
        "Key": "Value",
    }
    with (
        patch("clawhouse.telemetry.OTLPSpanExporter") as mock_exporter,
        patch("clawhouse.telemetry.Agent.instrument_all") as mock_instrument,
    ):
        setup_telemetry(settings)
        mock_exporter.assert_called_once_with(
            endpoint="http://collector:4318/v1/traces",
            headers={"Authorization": "Bearer abc", "Key": "Value"},
        )
        mock_instrument.assert_called_once_with(True)


# ---------------------------------------------------------------------------
# S2: Turn Span & Session Attributes (C6 - C10)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_turn_span_lifecycle_ok(
    memory_exporter: tuple[TracerProvider, InMemorySpanExporter],
) -> None:
    _, exporter = memory_exporter
    store = MemorySessionStore()
    ctx = _make_ctx(store, _Echo())

    res = await run_turn(SESSION, "Hello", ctx=ctx)
    assert res.status == "ok"

    spans = exporter.get_finished_spans()
    turn_spans = [s for s in spans if s.name == "clawhouse.turn"]
    assert len(turn_spans) == 1
    span = turn_spans[0]
    attrs = dict(span.attributes or {})

    assert attrs.get("clawhouse.session_id") == SESSION
    assert attrs.get("clawhouse.owner_id") == OWNER
    assert "clawhouse.run_id" in attrs
    assert attrs.get("clawhouse.turn_status") == "ok"


@pytest.mark.asyncio
async def test_turn_span_records_agent_id(
    memory_exporter: tuple[TracerProvider, InMemorySpanExporter],
) -> None:
    _, exporter = memory_exporter
    store = MemorySessionStore()
    ctx = _make_ctx(store, _Echo(), default_agent="data-analyst")

    res = await run_turn(SESSION, "Hello", ctx=ctx)
    assert res.status == "ok"

    spans = exporter.get_finished_spans()
    turn_spans = [s for s in spans if s.name == "clawhouse.turn"]
    assert len(turn_spans) == 1
    attrs = dict(turn_spans[0].attributes or {})
    assert "clawhouse.agent_id" in attrs


@pytest.mark.asyncio
async def test_turn_span_lifecycle_error(
    memory_exporter: tuple[TracerProvider, InMemorySpanExporter],
) -> None:
    _, exporter = memory_exporter
    store = MemorySessionStore()
    ctx = _make_ctx(store, _FailingModel())

    res = await run_turn(SESSION, "Boom", ctx=ctx)
    assert res.status == "error"

    spans = exporter.get_finished_spans()
    turn_spans = [s for s in spans if s.name == "clawhouse.turn"]
    assert len(turn_spans) == 1
    span = turn_spans[0]
    attrs = dict(span.attributes or {})
    assert attrs.get("clawhouse.turn_status") == "error"
    # Exception event recorded
    assert any(ev.name == "exception" for ev in span.events)


@pytest.mark.asyncio
async def test_turn_span_lifecycle_pending_approval(
    memory_exporter: tuple[TracerProvider, InMemorySpanExporter],
) -> None:
    _, exporter = memory_exporter
    store = MemorySessionStore()
    # Sensitive tool guard triggers pending_approval
    ctx = _make_ctx(store, _ToolCaller(), sensitive_tools=("clock",))

    res = await run_turn(SESSION, "What time is it?", ctx=ctx)
    assert res.status == "pending_approval"

    spans = exporter.get_finished_spans()
    turn_spans = [s for s in spans if s.name == "clawhouse.turn"]
    assert len(turn_spans) == 1
    span = turn_spans[0]
    attrs = dict(span.attributes or {})
    assert attrs.get("clawhouse.turn_status") == "pending_approval"


# ---------------------------------------------------------------------------
# S3: Pydantic AI Native Model and Tool Instrumentation (C11 - C14)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_telemetry_genai_spans(
    memory_exporter: tuple[TracerProvider, InMemorySpanExporter],
) -> None:
    _, exporter = memory_exporter
    store = MemorySessionStore()
    ctx = _make_ctx(store, _Echo())

    settings = Settings(
        dev_user=None,
        dev_token=None,
        serving_endpoint=None,
        workspace_host=None,
        telemetry_enabled=True,
    )
    setup_telemetry(settings)

    await run_turn(SESSION, "Hello", ctx=ctx)

    spans = exporter.get_finished_spans()
    # Check for GenAI chat / model span
    genai_chat = [
        s
        for s in spans
        if s.name.startswith("chat") or (s.attributes or {}).get("gen_ai.operation.name") == "chat"
    ]
    assert len(genai_chat) >= 1
    attrs = dict(genai_chat[0].attributes or {})
    assert attrs.get("gen_ai.operation.name") == "chat"
    assert "gen_ai.usage.input_tokens" in attrs or "gen_ai.client.token.usage" in attrs


@pytest.mark.asyncio
async def test_agent_telemetry_tool_spans(
    memory_exporter: tuple[TracerProvider, InMemorySpanExporter],
) -> None:
    _, exporter = memory_exporter
    store = MemorySessionStore()
    ctx = _make_ctx(store, _ToolCaller())

    settings = Settings(
        dev_user=None,
        dev_token=None,
        serving_endpoint=None,
        workspace_host=None,
        telemetry_enabled=True,
    )
    setup_telemetry(settings)

    await run_turn(SESSION, "Use clock", ctx=ctx)

    spans = exporter.get_finished_spans()
    # Tool execution span
    tool_spans = [
        s
        for s in spans
        if s.name.startswith("execute_tool")
        or s.name.startswith("tool:")
        or (s.attributes or {}).get("gen_ai.operation.name") == "execute_tool"
    ]
    assert len(tool_spans) >= 1
    tool_span = tool_spans[0]
    attrs = dict(tool_span.attributes or {})
    assert (
        attrs.get("gen_ai.tool.name") == "clock"
        or "clock" in tool_span.name
        or "gen_ai.tool.call.arguments" in attrs
    )


@pytest.mark.asyncio
async def test_app_lifespan_telemetry_setup() -> None:
    settings = Settings(
        dev_user=None,
        dev_token=None,
        serving_endpoint=None,
        workspace_host=None,
        telemetry_enabled=True,
        logfire_token="lifespan_token",
    )
    store = MemorySessionStore()
    with patch("clawhouse.api.app.setup_telemetry") as mock_setup:
        app = create_app(
            settings=settings,
            model_for=lambda caller, model_id: FunctionModel(stream_function=_Echo().stream),
            store=store,
        )
        async with app.router.lifespan_context(app):
            pass
        mock_setup.assert_called_once_with(settings)
