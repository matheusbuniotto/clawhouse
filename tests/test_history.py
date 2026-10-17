"""Transcript replay and native ModelMessages lifecycle tests."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic_ai import RunContext
from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter, ToolCallPart
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.toolsets import AbstractToolset, ToolsetTool
from pydantic_core import SchemaValidator, core_schema

from clawhouse.agent.history import to_model_messages
from clawhouse.agent.turn import TurnContext, resume_turn, run_turn
from clawhouse.capabilities.mcp import MCPServerConfig
from clawhouse.store.shapes import TranscriptEntry
from clawhouse.store.store import LakebaseSessionStore, MemorySessionStore, SessionNotFound

OWNER = "ada@example.com"
NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)


def _texts(messages: list[ModelMessage]) -> list[str]:
    found: list[str] = []
    for message in messages:
        for part in message.parts:
            content = getattr(part, "content", None)
            if isinstance(content, str):
                found.append(content)
            args = getattr(part, "args", None)
            if isinstance(args, str):
                found.append(args)
    return found


def test_a_tool_pair_is_replayed_between_the_user_and_the_reply() -> None:
    messages = to_model_messages(
        (
            TranscriptEntry(role="user", content="hi"),
            TranscriptEntry(role="tool_call", content="{}", tool_name="clock", tool_call_id="c1"),
            TranscriptEntry(
                role="tool_result",
                content="2026-10-10T12:00:00Z",
                tool_name="clock",
                tool_call_id="c1",
            ),
            TranscriptEntry(role="assistant", content="noon"),
        )
    )
    assert _texts(messages) == ["hi", "{}", "2026-10-10T12:00:00Z", "noon"]


def test_an_unpaired_tool_call_does_not_drop_later_turns() -> None:
    messages = to_model_messages(
        (
            TranscriptEntry(role="user", content="first"),
            TranscriptEntry(role="tool_call", content="{}", tool_name="clock", tool_call_id="c1"),
            TranscriptEntry(role="user", content="second"),
            TranscriptEntry(role="assistant", content="later"),
        )
    )
    assert _texts(messages) == ["first", "second", "later"]


@pytest.mark.asyncio
async def test_session_store_native_messages_lifecycle() -> None:
    # 1. MemorySessionStore lifecycle
    mem_store = MemorySessionStore()
    session = await mem_store.create_session(OWNER)
    assert await mem_store.messages(session.id) is None

    payload = b'[{"role": "user", "parts": [{"part_kind": "user-prompt", "content": "hi"}]}]'
    await mem_store.save_messages(session.id, payload)
    assert await mem_store.messages(session.id) == payload

    await mem_store.clear_transcript(session.id, OWNER)
    assert await mem_store.messages(session.id) is None

    with pytest.raises(SessionNotFound):
        await mem_store.messages("00000000-0000-4000-8000-000000000000")

    with pytest.raises(SessionNotFound):
        await mem_store.save_messages("00000000-0000-4000-8000-000000000000", payload)

    # 2. LakebaseSessionStore lifecycle
    mock_pool = AsyncMock()
    lake_store = LakebaseSessionStore(mock_pool)
    session_id = "11111111-1111-4111-8111-111111111111"

    # messages: when row exists with messages text
    mock_pool.fetchrow = AsyncMock(return_value={"messages": '{"test": 1}'})
    assert await lake_store.messages(session_id) == b'{"test": 1}'

    # messages: when row exists with None
    mock_pool.fetchrow = AsyncMock(return_value={"messages": None})
    assert await lake_store.messages(session_id) is None

    # messages: when session row does not exist
    mock_pool.fetchrow = AsyncMock(return_value=None)
    with pytest.raises(SessionNotFound):
        await lake_store.messages(session_id)

    # save_messages: update succeeds
    mock_pool.execute = AsyncMock(return_value="UPDATE 1")
    await lake_store.save_messages(session_id, b'{"test": 2}')

    # save_messages: session not found
    mock_pool.execute = AsyncMock(return_value="UPDATE 0")
    with pytest.raises(SessionNotFound):
        await lake_store.save_messages(session_id, b'{"test": 2}')

    # clear_transcript: deletes transcript and resets messages to NULL
    mock_conn = AsyncMock()
    mock_pool.acquire = MagicMock()
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
    mock_conn.transaction = MagicMock()
    mock_pool.fetchval = AsyncMock(return_value=OWNER)

    await lake_store.clear_transcript(session_id, OWNER)
    assert any(
        "UPDATE clawhouse.sessions SET messages = NULL" in call[0][0]
        for call in mock_conn.execute.call_args_list
    )
    assert any(
        "DELETE FROM clawhouse.transcript_entries" in call[0][0]
        for call in mock_conn.execute.call_args_list
    )


@pytest.mark.asyncio
async def test_chat_turn_persists_native_messages() -> None:
    store = MemorySessionStore()
    session = await store.create_session(OWNER)

    async def normal_stream(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str]:
        del messages, info
        yield "Hello there!"

    ctx = TurnContext(
        owner_id=OWNER,
        store=store,
        model=FunctionModel(stream_function=normal_stream),
        now=lambda: NOW,
    )

    # 1. Normal turn persists native ModelMessages
    result = await run_turn(session.id, "Hi agent", ctx=ctx)
    assert result.status == "ok"
    raw = await store.messages(session.id)
    assert raw is not None
    loaded = ModelMessagesTypeAdapter.validate_json(raw)
    assert len(loaded) >= 2

    # 2. Paused turn also persists native ModelMessages
    session_paused = await store.create_session(OWNER)

    async def sensitive_stream(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        del messages, info
        yield {
            0: DeltaToolCall(
                name="clock",
                json_args="{}",
                tool_call_id="call-clk-1",
            )
        }

    paused_ctx = TurnContext(
        owner_id=OWNER,
        store=store,
        model=FunctionModel(stream_function=sensitive_stream),
        now=lambda: NOW,
        sensitive_tools=("clock",),
    )

    paused_result = await run_turn(session_paused.id, "what time is it?", ctx=paused_ctx)
    assert paused_result.status == "pending_approval"
    raw_paused = await store.messages(session_paused.id)
    assert raw_paused is not None
    loaded_paused = ModelMessagesTypeAdapter.validate_json(raw_paused)
    assert any(
        isinstance(p, ToolCallPart) and p.tool_call_id == "call-clk-1"
        for m in loaded_paused
        for p in getattr(m, "parts", [])
    )


class _SecretToolset(AbstractToolset[object]):
    def __init__(self, executed: list[dict[str, object]]) -> None:
        self.executed = executed

    @property
    def id(self) -> str:
        return "notes"

    async def get_tools(self, ctx: RunContext[object]) -> dict[str, ToolsetTool[object]]:
        del ctx
        name = "lookup"
        definition = ToolDefinition(
            name=name,
            description="Look up a note.",
            parameters_json_schema={"type": "object"},
        )
        return {
            name: ToolsetTool(
                toolset=self,
                tool_def=definition,
                max_retries=1,
                args_validator=SchemaValidator(core_schema.dict_schema()),
            )
        }

    async def call_tool(
        self,
        name: str,
        tool_args: dict[str, object],
        ctx: RunContext[object],
        tool: ToolsetTool[object],
    ) -> str:
        del name, ctx, tool
        self.executed.append(tool_args)
        return "found note"

    async def list_tools(self) -> list[object]:
        return [type("Tool", (), {"name": "lookup", "description": "Look up a note."})()]


@pytest.mark.asyncio
async def test_resume_turn_uses_native_messages_without_redaction_replacement() -> None:
    store = MemorySessionStore()
    session = await store.create_session(OWNER)
    user_token = "secret-token-xyz"
    executed_records: list[dict[str, object]] = []
    toolset = _SecretToolset(executed_records)

    def factory(cfg: MCPServerConfig, token: str) -> AbstractToolset[object]:
        del cfg, token
        return toolset

    async def call_with_secret(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        del messages, info
        yield {
            0: DeltaToolCall(
                name="notes__lookup",
                json_args=f'{{"key": "{user_token}"}}',
                tool_call_id="call-sec-1",
            )
        }

    ctx = TurnContext(
        owner_id=OWNER,
        store=store,
        model=FunctionModel(stream_function=call_with_secret),
        now=lambda: NOW,
        sensitive_tools=("notes__lookup",),
        user_token=user_token,
        mcp_servers=(MCPServerConfig(name="notes", url="https://notes.example/mcp"),),
        mcp_toolset_factory=factory,
    )

    paused = await run_turn(session.id, "find secret note", ctx=ctx)
    assert paused.status == "pending_approval"
    approval_id = paused.approval_id
    assert approval_id is not None

    # Check that in store.messages (native messages), user_token was preserved as-is
    raw = await store.messages(session.id)
    assert raw is not None
    assert user_token.encode("utf-8") in raw
    assert b"[REDACTED]" not in raw

    # Approval table arguments are redacted for safety
    approval = await store.get_approval(approval_id)
    assert "[REDACTED]" in approval.arguments

    # Resume with approval
    async def reply_after_approval(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str]:
        del messages, info
        yield "Note found."

    resume_ctx = TurnContext(
        owner_id=OWNER,
        store=store,
        model=FunctionModel(stream_function=reply_after_approval),
        now=lambda: NOW,
        sensitive_tools=("notes__lookup",),
        user_token=user_token,
        mcp_servers=(MCPServerConfig(name="notes", url="https://notes.example/mcp"),),
        mcp_toolset_factory=factory,
    )

    resumed = await resume_turn(session.id, approval_id, "approved", ctx=resume_ctx)
    assert resumed.status == "ok"
    assert resumed.reply == "Note found."
    assert len(executed_records) == 1
    assert executed_records[0] == {"key": user_token}

    # Also test denial path
    session_deny = await store.create_session(OWNER)
    deny_records: list[dict[str, object]] = []
    deny_toolset = _SecretToolset(deny_records)

    def deny_factory(cfg: MCPServerConfig, token: str) -> AbstractToolset[object]:
        del cfg, token
        return deny_toolset

    paused_deny = await run_turn(
        session_deny.id,
        "find secret note",
        ctx=TurnContext(
            owner_id=OWNER,
            store=store,
            model=FunctionModel(stream_function=call_with_secret),
            now=lambda: NOW,
            sensitive_tools=("notes__lookup",),
            user_token=user_token,
            mcp_servers=(MCPServerConfig(name="notes", url="https://notes.example/mcp"),),
            mcp_toolset_factory=deny_factory,
        ),
    )
    assert paused_deny.status == "pending_approval"
    deny_approval_id = paused_deny.approval_id
    assert deny_approval_id is not None

    async def reply_after_deny(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str]:
        del messages, info
        yield "Operation cancelled."

    deny_ctx = TurnContext(
        owner_id=OWNER,
        store=store,
        model=FunctionModel(stream_function=reply_after_deny),
        now=lambda: NOW,
        sensitive_tools=("notes__lookup",),
        user_token=user_token,
        mcp_servers=(MCPServerConfig(name="notes", url="https://notes.example/mcp"),),
        mcp_toolset_factory=deny_factory,
    )

    denied = await resume_turn(session_deny.id, deny_approval_id, "denied", ctx=deny_ctx)
    assert denied.status == "ok"
    assert denied.reply == "Operation cancelled."
    assert len(deny_records) == 0


@pytest.mark.asyncio
async def test_turn_history_fallback_for_legacy_sessions() -> None:
    store = MemorySessionStore()
    session = await store.create_session(OWNER)

    # Simulate legacy session: transcript entries exist, but store.messages is None
    run_id = await store.claim_run(session.id)
    await store.append_entry(
        session.id, run_id, TranscriptEntry(role="user", content="Legacy turn 1")
    )
    await store.append_entry(
        session.id, run_id, TranscriptEntry(role="assistant", content="Legacy reply 1")
    )
    await store.finish_run(session.id, run_id, "ok")

    assert await store.messages(session.id) is None

    received_messages: list[ModelMessage] = []

    async def stream_fn(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str]:
        del info
        received_messages.extend(messages)
        yield "Turn 2 reply"

    ctx = TurnContext(
        owner_id=OWNER,
        store=store,
        model=FunctionModel(stream_function=stream_fn),
        now=lambda: NOW,
    )

    result = await run_turn(session.id, "Turn 2 prompt", ctx=ctx)
    assert result.status == "ok"
    assert result.reply == "Turn 2 reply"

    # Verify model received the reconstructed messages from the legacy transcript
    texts = _texts(received_messages)
    assert "Legacy turn 1" in texts
    assert "Legacy reply 1" in texts
    assert "Turn 2 prompt" in texts

    # Verify native ModelMessages were saved after the turn
    raw_saved = await store.messages(session.id)
    assert raw_saved is not None
    loaded = ModelMessagesTypeAdapter.validate_json(raw_saved)
    assert len(loaded) >= 4
