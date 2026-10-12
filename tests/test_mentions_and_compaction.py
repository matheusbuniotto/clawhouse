"""Tests for @ mentions context injection and /compact session compaction."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from crabriks.agent.turn import TurnContext, run_turn
from crabriks.capabilities.databricks import DatabricksCapability
from crabriks.capabilities.mentions import (
    extract_agent_mentions,
    extract_file_mentions,
    extract_table_mentions,
    resolve_mention_bundles,
)
from crabriks.capabilities.workspace import resolve_agent_workspace
from crabriks.store.shapes import CustomAgent, TranscriptEntry
from crabriks.store.store import MemorySessionStore

NOW = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)
OWNER = "ada@example.com"


def test_mention_extractors() -> None:
    text = "Check @samples.nyctaxi.trips and @file:SOUL.md with @sql_analyst"
    assert extract_table_mentions(text) == ["samples.nyctaxi.trips"]
    assert extract_file_mentions(text) == ["SOUL.md"]
    assert extract_agent_mentions(text) == ["sql_analyst"]


@pytest.mark.asyncio
async def test_resolve_mention_bundles_injects_table_and_file(tmp_path: Path) -> None:
    store = MemorySessionStore()
    workspace = resolve_agent_workspace(tmp_path, "main")
    workspace.directory.mkdir(parents=True, exist_ok=True)
    (workspace.directory / "SOUL.md").write_text("Be concise.", encoding="utf-8")

    mock_client = MagicMock()
    fake_table = MagicMock()
    col1 = MagicMock(name="trip_id")
    col1.name = "trip_id"
    col1.type_text = "BIGINT"
    col1.comment = None
    fake_table.columns = [col1]
    fake_table.comment = "Taxi trips"
    mock_client.tables.get.return_value = fake_table

    db_cap = DatabricksCapability(client_factory=lambda _token: mock_client)

    bundle = await resolve_mention_bundles(
        "Analyze @samples.nyctaxi.trips with @file:SOUL.md",
        store=store,
        owner_id=OWNER,
        workspace=workspace,
        databricks_cap=db_cap,
    )

    assert "samples.nyctaxi.trips" in bundle.injected_context
    assert "trip_id" in bundle.injected_context
    assert "Be concise." in bundle.injected_context


@pytest.mark.asyncio
async def test_agent_mention_routes_persona(tmp_path: Path) -> None:
    store = MemorySessionStore()
    await store.create_custom_agent(
        CustomAgent(
            id="agent-123",
            owner_id=OWNER,
            name="data_wizard",
            description="Wizard of data",
            system_prompt="You speak like a wizard analyzing datasets.",
            signature_emoji="🧙‍♂️",
        )
    )

    bundle = await resolve_mention_bundles(
        "Hey @data_wizard how are the numbers?",
        store=store,
        owner_id=OWNER,
        workspace=None,
        databricks_cap=None,
    )

    assert bundle.target_agent is not None
    assert bundle.target_agent.name == "data_wizard"
    assert "wizard" in bundle.target_agent.system_prompt


@pytest.mark.asyncio
async def test_compact_command_creates_summary_checkpoint() -> None:
    store = MemorySessionStore()
    session_id = "33333333-3333-4333-8333-333333333333"
    await store.open_session(session_id, OWNER)
    run_id = await store.claim_run(session_id)
    await store.append_entry(session_id, run_id, TranscriptEntry(role="user", content="Turn 1"))
    await store.append_entry(
        session_id, run_id, TranscriptEntry(role="assistant", content="Reply 1")
    )
    await store.finish_run(session_id, run_id, "ok")

    async def model_fn(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str]:
        del messages, info
        yield "This is a compacted summary."

    def sync_fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del messages, info
        return ModelResponse(parts=[TextPart(content="This is a compacted summary.")])

    ctx = TurnContext(
        owner_id=OWNER,
        store=store,
        model=FunctionModel(function=sync_fn, stream_function=model_fn),
        now=lambda: NOW,
    )

    result = await run_turn(session_id, "/compact", ctx=ctx)
    assert result.status == "ok"
    assert "compact" in result.reply.lower()

    # Verify transcript now has summary checkpoint
    transcript = await store.transcript(session_id, OWNER)
    assert any("compact" in e.content.lower() or "summary" in e.content.lower() for e in transcript)
