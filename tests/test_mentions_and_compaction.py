"""Tests for @ mentions context injection and /compact session compaction."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from clawhouse.agent.history import to_model_messages
from clawhouse.agent.turn import TurnContext, run_turn
from clawhouse.capabilities.databricks import DatabricksCapability
from clawhouse.capabilities.mentions import (
    CompactionResult,
    execute_compaction,
    extract_agent_mentions,
    extract_file_mentions,
    extract_skill_mentions,
    extract_table_mentions,
    resolve_mention_bundles,
)
from clawhouse.capabilities.workspace import resolve_agent_workspace
from clawhouse.store.shapes import CustomAgent, TranscriptEntry
from clawhouse.store.store import MemorySessionStore

NOW = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)
OWNER = "ada@example.com"


def test_mention_extractors() -> None:
    text = (
        "Check @samples.nyctaxi.trips and @file:SOUL.md with @sql_analyst using /skill:code-review"
    )
    assert extract_table_mentions(text) == ["samples.nyctaxi.trips"]
    assert extract_file_mentions(text) == ["SOUL.md"]
    assert extract_agent_mentions(text) == ["sql_analyst"]
    assert extract_skill_mentions(text) == ["code-review"]


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

    # The tiered policy replaces the old history with the summary checkpoint...
    transcript = await store.transcript(session_id, OWNER)
    assert any(entry.content == "This is a compacted summary." for entry in transcript)
    assert all(
        "Turn 1" not in entry.content and "Reply 1" not in entry.content for entry in transcript
    )


@pytest.mark.asyncio
async def test_compact_empty_session_reports_nothing_to_compact() -> None:
    store = MemorySessionStore()
    session_id = "55555555-5555-4555-8555-555555555555"
    await store.open_session(session_id, OWNER)

    def explode(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del messages, info
        raise AssertionError("an empty transcript must not call the summarizer")

    result = await execute_compaction(store, session_id, OWNER, FunctionModel(function=explode))

    assert result == CompactionResult(summary="No session history to compact.", entries=())


@pytest.mark.asyncio
async def test_compact_rewrites_tool_history_into_a_replayable_checkpoint() -> None:
    store = MemorySessionStore()
    session_id = "66666666-6666-4666-8666-666666666666"
    await store.open_session(session_id, OWNER)
    run_id = await store.claim_run(session_id)
    for entry in (
        TranscriptEntry(role="user", content="what time is it?"),
        TranscriptEntry(role="tool_call", content="{}", tool_name="clock", tool_call_id="c1"),
        TranscriptEntry(role="tool_result", content="12:00", tool_name="clock", tool_call_id="c1"),
        TranscriptEntry(role="assistant", content="The time is 12:00"),
    ):
        await store.append_entry(session_id, run_id, entry)
    await store.finish_run(session_id, run_id, "ok")

    def sync_fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del messages, info
        return ModelResponse(parts=[TextPart(content="Compacted tool history.")])

    result = await run_turn(
        session_id,
        "/compact",
        ctx=TurnContext(
            owner_id=OWNER,
            store=store,
            model=FunctionModel(function=sync_fn),
            now=lambda: NOW,
        ),
    )

    assert result.status == "ok"
    assert any(entry.content == "Compacted tool history." for entry in result.transcript)
    assert all(entry.role != "tool_call" for entry in result.transcript)
    # The rewritten transcript replays as valid model messages (no orphaned tool pair).
    assert to_model_messages(result.transcript)


@pytest.mark.asyncio
async def test_resolve_mention_bundles_injects_skill_instructions(tmp_path: Path) -> None:
    store = MemorySessionStore()
    workspace = resolve_agent_workspace(tmp_path, "main")
    skill_dir = workspace.skills / "sql_optimizer"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text("Optimize all SELECT queries.", encoding="utf-8")

    bundle = await resolve_mention_bundles(
        "/skill:sql_optimizer help optimize this query",
        store=store,
        owner_id=OWNER,
        workspace=workspace,
        databricks_cap=None,
    )

    assert "### Skill Instructions: sql_optimizer" in bundle.injected_context
    assert "Optimize all SELECT queries." in bundle.injected_context


@pytest.mark.asyncio
async def test_resolve_mention_bundles_missing_skill(tmp_path: Path) -> None:
    store = MemorySessionStore()
    workspace = resolve_agent_workspace(tmp_path, "main")
    workspace.directory.mkdir(parents=True, exist_ok=True)

    bundle = await resolve_mention_bundles(
        "/skill:nonexistent_skill please help",
        store=store,
        owner_id=OWNER,
        workspace=workspace,
        databricks_cap=None,
    )

    assert "### Skill: nonexistent_skill (not found)" in bundle.injected_context


@pytest.mark.asyncio
async def test_turn_with_skill_command_injects_instructions_into_turn(tmp_path: Path) -> None:
    store = MemorySessionStore()
    session_id = "44444444-4444-4444-8444-444444444444"
    await store.open_session(session_id, OWNER)

    workspace = resolve_agent_workspace(tmp_path, "main")
    skill_dir = workspace.skills / "code_review"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text("Always check for edge cases and types.", encoding="utf-8")

    received_prompts: list[str] = []

    async def model_fn(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str]:
        del info
        for m in messages:
            for p in getattr(m, "parts", []):
                content = getattr(p, "content", None)
                if isinstance(content, str):
                    received_prompts.append(content)
        yield "Review complete."

    ctx = TurnContext(
        owner_id=OWNER,
        store=store,
        workspace=workspace,
        model=FunctionModel(stream_function=model_fn),
        now=lambda: NOW,
    )

    result = await run_turn(session_id, "/skill:code_review please review my code", ctx=ctx)
    assert result.status == "ok"
    assert result.reply == "Review complete."

    # Verify that the injected context with skill instructions was passed to the agent
    assert any("### Skill Instructions: code_review" in p for p in received_prompts)
    assert any("Always check for edge cases and types." in p for p in received_prompts)
