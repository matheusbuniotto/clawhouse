"""The chat seam: one turn composes the prompt, dispatches the tool, and persists."""

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic_ai import RunContext
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.toolsets import AbstractToolset, ToolsetTool
from pydantic_core import SchemaValidator, core_schema

from crabriks.mcp import MCPServerConfig
from crabriks.prompt import (
    CLOCK_DESCRIPTION,
    SKILLS_READ_DESCRIPTION,
    SKILLS_SEARCH_DESCRIPTION,
)
from crabriks.shapes import TranscriptEntry
from crabriks.skills import SkillsCache
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


def _ctx(  # noqa: PLR0913
    store: MemorySessionStore,
    model: FunctionModel,
    *,
    owner: str = OWNER,
    emit: list[TurnNotice] | None = None,
    workspace: WorkspacePaths | None = None,
    mcp_servers: tuple[MCPServerConfig, ...] = (),
    user_token: str = "",
    mcp_toolset_factory: object = None,
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
        mcp_servers=mcp_servers,
        user_token=user_token,
        mcp_toolset_factory=mcp_toolset_factory,  # type: ignore[arg-type]
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
    assert [tool.name for tool in info.function_tools] == [
        "clock",
        "skills_search",
        "skills_read",
    ]
    assert info.function_tools[0].description == CLOCK_DESCRIPTION
    assert info.function_tools[1].description == SKILLS_SEARCH_DESCRIPTION
    assert info.function_tools[2].description == SKILLS_READ_DESCRIPTION
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


async def test_turn_with_skills_in_workspace(tmp_path: Path) -> None:
    paths = resolve_agent_workspace(tmp_path, "main")
    paths.skills.mkdir(parents=True)
    sql_dir = paths.skills / "sql"
    sql_dir.mkdir()
    (sql_dir / "SKILL.md").write_text(
        "---\nname: sql\ndescription: Run a warehouse query.\n---\n# SQL\nFull instructions.\n",
        encoding="utf-8",
    )
    seen: list[str] = []

    async def capture(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str]:
        del messages
        seen.append(info.instructions or "")
        yield "ok"

    ctx = _ctx(MemorySessionStore(), FunctionModel(stream_function=capture), workspace=paths)
    result = await run_turn(SESSION, "hello", ctx=ctx)

    assert result.status == "ok"
    assert "# Skills\n- sql: Run a warehouse query." in seen[0]
    assert "Full instructions." not in seen[0]


async def test_turn_dispatches_skills_search_and_skills_read(tmp_path: Path) -> None:
    paths = resolve_agent_workspace(tmp_path, "main")
    paths.skills.mkdir(parents=True)
    sql_dir = paths.skills / "sql"
    sql_dir.mkdir()
    (sql_dir / "SKILL.md").write_text(
        "---\nname: sql\ndescription: Run a warehouse query.\n---\n# SQL\nFull instructions here.",
        encoding="utf-8",
    )

    async def search_and_read(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        del info
        parts = _parts(messages)
        if "tool-return" not in parts:
            yield {
                0: DeltaToolCall(
                    name="skills_search",
                    json_args=json.dumps({"query": "warehouse"}),
                    tool_call_id="call-search",
                )
            }
            return
        tool_returns = [
            getattr(p, "content", "")
            for m in messages
            for p in m.parts
            if p.part_kind == "tool-return"
        ]
        if len(tool_returns) == 1:
            assert "- sql: Run a warehouse query." in tool_returns[0]
            yield {
                0: DeltaToolCall(
                    name="skills_read",
                    json_args=json.dumps({"name": "sql"}),
                    tool_call_id="call-read",
                )
            }
            return
        if len(tool_returns) == 2:
            assert "# SQL\nFull instructions here." in tool_returns[1]
            yield "Loaded skill sql successfully"

    ctx = _ctx(
        MemorySessionStore(),
        FunctionModel(stream_function=search_and_read),
        workspace=paths,
    )
    result = await run_turn(SESSION, "help me query", ctx=ctx)

    assert result.status == "ok"
    assert result.reply == "Loaded skill sql successfully"
    transcript_roles = [e.role for e in result.transcript]
    assert transcript_roles == [
        "user",
        "tool_call",
        "tool_result",
        "tool_call",
        "tool_result",
        "assistant",
    ]
    assert result.transcript[2].content == "- sql: Run a warehouse query."
    assert result.transcript[4].content == "# SQL\nFull instructions here."


async def test_turn_skills_read_oversize_rejects_with_error(tmp_path: Path) -> None:
    paths = resolve_agent_workspace(tmp_path, "main")
    paths.skills.mkdir(parents=True)
    big_dir = paths.skills / "big"
    big_dir.mkdir()
    oversize = "x" * 33_000
    (big_dir / "SKILL.md").write_text(
        f"---\nname: big\ndescription: Big skill.\n---\n{oversize}",
        encoding="utf-8",
    )

    async def call_read(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        del messages, info
        yield {
            0: DeltaToolCall(
                name="skills_read",
                json_args=json.dumps({"name": "big"}),
                tool_call_id="call-big",
            )
        }

    ctx = _ctx(MemorySessionStore(), FunctionModel(stream_function=call_read), workspace=paths)
    result = await run_turn(SESSION, "load big", ctx=ctx)

    assert result.status == "error"
    assert result.error == FAILED_TURN


async def test_turn_skills_discovery_is_cached_per_session(tmp_path: Path) -> None:
    paths = resolve_agent_workspace(tmp_path, "main")
    paths.skills.mkdir(parents=True)
    sql_dir = paths.skills / "sql"
    sql_dir.mkdir()
    (sql_dir / "SKILL.md").write_text(
        "---\nname: sql\ndescription: Initial description.\n---\nbody",
        encoding="utf-8",
    )
    seen: list[str] = []

    async def capture(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str]:
        del messages
        seen.append(info.instructions or "")
        yield "ok"

    ctx = TurnContext(
        owner_id=OWNER,
        store=MemorySessionStore(),
        model=FunctionModel(stream_function=capture),
        now=lambda: FROZEN,
        workspace=paths,
        skills_cache=SkillsCache(),
    )
    first = await run_turn(SESSION, "first turn", ctx=ctx)
    assert first.status == "ok"
    assert "- sql: Initial description." in seen[0]

    # Modify on disk
    (sql_dir / "SKILL.md").write_text(
        "---\nname: sql\ndescription: Modified description.\n---\nbody",
        encoding="utf-8",
    )

    # Second turn on same session uses cached skills
    second = await run_turn(SESSION, "second turn", ctx=ctx)
    assert second.status == "ok"
    assert "- sql: Initial description." in seen[1]
    assert "- sql: Modified description." not in seen[1]

    # Turn on different session discovers modified skills
    other_session = "22222222-2222-4222-8222-222222222222"
    third = await run_turn(other_session, "third turn", ctx=ctx)
    assert third.status == "ok"
    assert "- sql: Modified description." in seen[2]


class _MockUCToolset(AbstractToolset[object]):
    @property
    def id(self) -> str:
        return "system_ai_srv"

    async def get_tools(self, ctx: RunContext[object]) -> dict[str, ToolsetTool[object]]:
        del ctx
        tool_def = ToolDefinition(
            name="describe_table",
            description="Describe columns of a Unity Catalog table",
            parameters_json_schema={
                "type": "object",
                "properties": {"table": {"type": "string"}},
                "required": ["table"],
            },
        )
        return {
            "describe_table": ToolsetTool(
                toolset=self,
                tool_def=tool_def,
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
    ) -> object:
        del name, ctx, tool
        table = str(tool_args.get("table", ""))
        return json.dumps(
            {
                "table": table,
                "columns": ["trip_id", "pickup_time", "fare_amount"],
            }
        )

    async def list_tools(self) -> list[object]:
        return [
            type(
                "Tool",
                (),
                {
                    "name": "describe_table",
                    "description": "Describe columns of a Unity Catalog table",
                    "input_schema": {
                        "type": "object",
                        "properties": {"table": {"type": "string"}},
                    },
                },
            )()
        ]


class _MockSecondaryToolset(AbstractToolset[object]):
    @property
    def id(self) -> str:
        return "billing_srv"

    async def get_tools(self, ctx: RunContext[object]) -> dict[str, ToolsetTool[object]]:
        del ctx
        tool_def = ToolDefinition(
            name="get_balance",
            description="Get billing balance",
            parameters_json_schema={"type": "object"},
        )
        return {
            "get_balance": ToolsetTool(
                toolset=self,
                tool_def=tool_def,
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
    ) -> object:
        del name, tool_args, ctx, tool
        return '{"balance": 100}'

    async def list_tools(self) -> list[object]:
        return [
            type(
                "Tool",
                (),
                {
                    "name": "get_balance",
                    "description": "Get billing balance",
                    "input_schema": {"type": "object"},
                },
            )()
        ]


class _MockFailingServerToolset(AbstractToolset[object]):
    @property
    def id(self) -> str:
        return "fail_srv"

    async def get_tools(self, ctx: RunContext[object]) -> dict[str, ToolsetTool[object]]:
        del ctx
        return {}

    async def call_tool(
        self,
        name: str,
        tool_args: dict[str, object],
        ctx: RunContext[object],
        tool: ToolsetTool[object],
    ) -> object:
        del name, tool_args, ctx, tool
        return "err"

    async def list_tools(self) -> list[object]:
        raise RuntimeError("Server unavailable")


async def test_turn_includes_mcp_tools_in_prompt_ordered_deterministically() -> None:
    seen_instructions: list[str] = []

    async def capture(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str]:
        del messages
        seen_instructions.append(info.instructions or "")
        yield "ok"

    servers = (
        MCPServerConfig(name="system.ai", url="https://adb-1.databricks.com/mcp"),
        MCPServerConfig(name="billing", url="https://billing.databricks.com/mcp"),
    )

    def factory(srv: MCPServerConfig, token: str) -> AbstractToolset[object]:
        del token
        if srv.name == "billing":
            return _MockSecondaryToolset()
        return _MockUCToolset()

    ctx = _ctx(
        MemorySessionStore(),
        FunctionModel(stream_function=capture),
        mcp_servers=servers,
        mcp_toolset_factory=factory,
    )

    result = await run_turn(SESSION, "hello", ctx=ctx)
    assert result.status == "ok"
    assert len(seen_instructions) == 1
    prompt = seen_instructions[0]

    billing_pos = prompt.find("- billing__get_balance: Get billing balance")
    uc_pos = prompt.find("- system_ai__describe_table: Describe columns of a Unity Catalog table")
    assert billing_pos != -1
    assert uc_pos != -1
    # billing alphabetically precedes system_ai
    assert billing_pos < uc_pos


async def test_turn_survives_when_mcp_server_tools_list_fails() -> None:
    seen_instructions: list[str] = []

    async def capture(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str]:
        del messages
        seen_instructions.append(info.instructions or "")
        yield "survived"

    servers = (
        MCPServerConfig(name="fail", url="https://fail.databricks.com/mcp"),
        MCPServerConfig(name="system.ai", url="https://adb-1.databricks.com/mcp"),
    )

    def factory(srv: MCPServerConfig, token: str) -> AbstractToolset[object]:
        del token
        if srv.name == "fail":
            return _MockFailingServerToolset()
        return _MockUCToolset()

    ctx = _ctx(
        MemorySessionStore(),
        FunctionModel(stream_function=capture),
        mcp_servers=servers,
        mcp_toolset_factory=factory,
    )

    result = await run_turn(SESSION, "hello", ctx=ctx)
    assert result.status == "ok"
    assert result.reply == "survived"
    prompt = seen_instructions[0]
    assert "- system_ai__describe_table:" in prompt
    assert "fail__" not in prompt


async def test_turn_demo_agent_answers_unity_catalog_question_through_mcp_tool() -> None:
    uc_tool_call_id = "call-uc-describe"

    async def uc_assistant(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        del info
        tool_returns = [
            getattr(part, "content", None)
            for message in messages
            for part in message.parts
            if getattr(part, "part_kind", None) == "tool-return"
        ]
        if not tool_returns:
            yield {
                0: DeltaToolCall(
                    name="system_ai__describe_table",
                    json_args=json.dumps({"table": "main.default.trips"}),
                    tool_call_id=uc_tool_call_id,
                )
            }
            return

        assert "trip_id" in str(tool_returns[0])
        yield "Table main.default.trips has columns: trip_id, pickup_time, fare_amount."

    emitted_notices: list[TurnNotice] = []
    servers = (MCPServerConfig(name="system.ai", url="https://adb-1.databricks.com/mcp"),)

    def factory(srv: MCPServerConfig, token: str) -> AbstractToolset[object]:
        assert token == "dapi-user-test-token"
        return _MockUCToolset()

    ctx = _ctx(
        MemorySessionStore(),
        FunctionModel(stream_function=uc_assistant),
        emit=emitted_notices,
        mcp_servers=servers,
        user_token="dapi-user-test-token",
        mcp_toolset_factory=factory,
    )

    result = await run_turn(
        SESSION,
        "What are the columns of the unity catalog table main.default.trips?",
        ctx=ctx,
    )

    assert result.status == "ok"
    assert "trip_id, pickup_time, fare_amount" in result.reply

    # Assert transcript entries
    roles = [entry.role for entry in result.transcript]
    assert roles == ["user", "tool_call", "tool_result", "assistant"]
    assert result.transcript[1].tool_name == "system_ai__describe_table"
    assert result.transcript[1].tool_call_id == uc_tool_call_id
    assert "main.default.trips" in result.transcript[1].content
    assert "trip_id" in result.transcript[2].content

    # Assert streamed notices
    call_notices = [n for n in emitted_notices if isinstance(n, ToolCallNotice)]
    result_notices = [n for n in emitted_notices if isinstance(n, ToolResultNotice)]
    assert len(call_notices) == 1
    assert call_notices[0].name == "system_ai__describe_table"
    assert len(result_notices) == 1
    assert result_notices[0].name == "system_ai__describe_table"
    assert "trip_id" in result_notices[0].content
