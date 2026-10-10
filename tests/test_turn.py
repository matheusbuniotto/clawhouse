"""The chat seam: one turn composes the prompt, dispatches the tool, and persists."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel

from crabriks.prompt import CLOCK_DESCRIPTION
from crabriks.shapes import TranscriptEntry
from crabriks.store import MemorySessionStore
from crabriks.turn import (
    FAILED_TURN,
    RunInProgress,
    SessionForbidden,
    Token,
    ToolCallNotice,
    ToolResultNotice,
    TurnContext,
    TurnNotice,
    run_turn,
)
from crabriks.workspace import WorkspacePaths, resolve_agent_workspace

SESSION = "11111111-1111-4111-8111-111111111111"
OWNER = "ada@example.com"
OTHER = "grace@example.com"
FROZEN = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
EXPECTED_TIME = "2026-10-10T12:00:00Z"
CALL_ID = "call-clock"


def _ctx(
    store: MemorySessionStore,
    model: FunctionModel,
    *,
    owner: str = OWNER,
    emit: list[TurnNotice] | None = None,
    workspace: WorkspacePaths | None = None,
) -> TurnContext:
    async def capture(notice: TurnNotice) -> None:
        if emit is not None:
            emit.append(notice)

    return TurnContext(
        owner_id=owner,
        store=store,
        model=model,
        now=lambda: FROZEN,
        emit=capture,
        workspace=workspace,
    )


def _parts(messages: list[ModelMessage]) -> list[str]:
    return [part.part_kind for message in messages for part in message.parts]


def _string_contents(messages: list[ModelMessage]) -> list[str]:
    found: list[str] = []
    for message in messages:
        for part in message.parts:
            content = getattr(part, "content", None)
            if isinstance(content, str):
                found.append(content)
    return found


async def _clock_then_reply(
    messages: list[ModelMessage], info: AgentInfo
) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
    assert [tool.name for tool in info.function_tools] == ["clock"]
    assert info.function_tools[0].description == CLOCK_DESCRIPTION
    assert info.instructions is not None
    assert info.instructions.startswith("# Identity\nYou are Crabriks, the platform agent main.")
    assert f"session_id: {SESSION}" in info.instructions
    assert "time: 2026-10-10T12:00:00Z" in info.instructions
    if "tool-return" not in _parts(messages):
        yield {0: DeltaToolCall(name="clock", json_args="{}", tool_call_id=CALL_ID)}
        return
    yield "The time is "
    yield EXPECTED_TIME


async def test_turn_persists_the_clock_exchange_and_streams_the_reply() -> None:
    store = MemorySessionStore()
    notices: list[TurnNotice] = []
    result = await run_turn(
        SESSION,
        "what time is it?",
        ctx=_ctx(store, FunctionModel(stream_function=_clock_then_reply), emit=notices),
    )

    expected = (
        TranscriptEntry(role="user", content="what time is it?"),
        TranscriptEntry(role="tool_call", content="{}", tool_name="clock", tool_call_id=CALL_ID),
        TranscriptEntry(
            role="tool_result",
            content=EXPECTED_TIME,
            tool_name="clock",
            tool_call_id=CALL_ID,
        ),
        TranscriptEntry(role="assistant", content=f"The time is {EXPECTED_TIME}"),
    )
    assert result.status == "ok"
    assert result.reply == f"The time is {EXPECTED_TIME}"
    assert result.error is None
    assert result.transcript == expected
    assert await store.transcript(SESSION, OWNER) == expected
    assert notices == [
        ToolCallNotice(name="clock", arguments="{}", tool_call_id=CALL_ID),
        ToolResultNotice(name="clock", content=EXPECTED_TIME, tool_call_id=CALL_ID),
        Token("The time is "),
        Token(EXPECTED_TIME),
    ]


async def test_a_second_inflight_run_on_the_same_session_errors() -> None:
    store = MemorySessionStore()
    started = asyncio.Event()
    release = asyncio.Event()

    async def block(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str]:
        del messages, info
        started.set()
        await release.wait()
        yield "done"

    first = asyncio.create_task(
        run_turn(SESSION, "first", ctx=_ctx(store, FunctionModel(stream_function=block)))
    )
    await started.wait()

    with pytest.raises(RunInProgress):
        await run_turn(SESSION, "second", ctx=_ctx(store, FunctionModel(stream_function=block)))

    release.set()
    result = await first
    assert result.status == "ok"
    assert result.reply == "done"
    assert [entry.content for entry in result.transcript] == ["first", "done"]


async def test_a_failed_turn_returns_an_empty_reply_and_keeps_the_tool_rows() -> None:
    store = MemorySessionStore()

    async def explode(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        del info
        if "tool-return" not in _parts(messages):
            yield {0: DeltaToolCall(name="clock", json_args="{}", tool_call_id=CALL_ID)}
            return
        raise RuntimeError("model exploded")

    result = await run_turn(
        SESSION,
        "what time is it?",
        ctx=_ctx(store, FunctionModel(stream_function=explode)),
    )

    assert result.status == "error"
    assert result.reply == ""
    assert result.error == FAILED_TURN
    assert result.transcript == (
        TranscriptEntry(role="user", content="what time is it?"),
        TranscriptEntry(role="tool_call", content="{}", tool_name="clock", tool_call_id=CALL_ID),
        TranscriptEntry(
            role="tool_result",
            content=EXPECTED_TIME,
            tool_name="clock",
            tool_call_id=CALL_ID,
        ),
    )
    assert not any(entry.role == "assistant" for entry in result.transcript)

    follow_up = await run_turn(
        SESSION,
        "try again",
        ctx=_ctx(store, FunctionModel(stream_function=_reply("ok"))),
    )
    assert follow_up.status == "ok"
    assert follow_up.reply == "ok"


async def test_reloading_returns_the_persisted_transcript() -> None:
    store = MemorySessionStore()
    await run_turn(
        SESSION,
        "hello",
        ctx=_ctx(store, FunctionModel(stream_function=_reply("HELLO"))),
    )

    reloaded = await store.transcript(SESSION, OWNER)

    async def continue_the_chat(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str]:
        del info
        assert "HELLO" in _string_contents(messages)
        yield "WORLD"

    again = await run_turn(
        SESSION,
        "world",
        ctx=_ctx(store, FunctionModel(stream_function=continue_the_chat)),
    )

    assert [entry.content for entry in reloaded] == ["hello", "HELLO"]
    assert again.status == "ok"
    assert [entry.content for entry in again.transcript] == ["hello", "HELLO", "world", "WORLD"]


async def test_another_user_cannot_continue_the_session() -> None:
    store = MemorySessionStore()
    await run_turn(
        SESSION,
        "hello",
        ctx=_ctx(store, FunctionModel(stream_function=_reply("HELLO"))),
    )

    with pytest.raises(SessionForbidden):
        await run_turn(
            SESSION,
            "intrusion",
            ctx=_ctx(store, FunctionModel(stream_function=_reply("no")), owner=OTHER),
        )

    assert [entry.content for entry in await store.transcript(SESSION, OWNER)] == ["hello", "HELLO"]


async def test_editing_the_git_folder_changes_the_next_turn(tmp_path: Path) -> None:
    paths = resolve_agent_workspace(tmp_path, "main")
    paths.directory.mkdir(parents=True)
    paths.agents.write_text("Agree to alpha.\n", encoding="utf-8")
    paths.agents.chmod(0o444)
    seen: list[str] = []

    async def capture(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str]:
        del messages
        seen.append(info.instructions or "")
        yield "ok"

    ctx = _ctx(MemorySessionStore(), FunctionModel(stream_function=capture), workspace=paths)
    first = await run_turn(SESSION, "hello", ctx=ctx)

    assert first.status == "ok"
    assert "Agree to alpha." in seen[0]
    assert "[MISSING] SOUL.md" in seen[0]
    assert f"session_id: {SESSION}" in seen[0]
    assert paths.agents.read_text(encoding="utf-8") == "Agree to alpha.\n"

    paths.agents.chmod(0o644)
    paths.agents.write_text("Agree to beta.\n", encoding="utf-8")
    paths.agents.chmod(0o444)
    second = await run_turn(SESSION, "again", ctx=ctx)

    assert second.status == "ok"
    assert "Agree to beta." in seen[1]
    assert "Agree to alpha." not in seen[1]
    assert paths.agents.read_text(encoding="utf-8") == "Agree to beta.\n"
    assert not paths.soul.exists()


def _reply(text: str):
    async def stream(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str]:
        del messages, info
        yield text

    return stream
