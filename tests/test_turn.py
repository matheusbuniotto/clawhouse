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
from crabriks.prompt import CLOCK_DESCRIPTION
from crabriks.shapes import TranscriptEntry
from crabriks.skills import loaded_skill_text
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
    user_token: str = "dapi-" + "turn-user-token",
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


def _tool_return_text(messages: list[ModelMessage]) -> str:
    for message in messages:
        for part in message.parts:
            if part.part_kind != "tool-return":
                continue
            content = getattr(part, "content", None)
            loaded = loaded_skill_text(content)
            if loaded is not None:
                return loaded
            if isinstance(content, str):
                return content
    return ""


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


_CATALOG = (
    "The following capabilities are deferred and can be loaded using the `load_capability` tool. "
    "A capability's tools stay hidden until it is loaded:\n"
    "- sql: Run a warehouse query."
)
_SKILL_BODY = "# Skill: sql\n\n# SQL\nFull instructions here."
_FILE_TOOLS = (
    "read_file",
    "write_file",
    "edit_file",
    "shell",
    "run_code",
    "skills_search",
    "skills_read",
)


def _write_skill(skills_dir: Path, folder: str, frontmatter: str, body: str) -> Path:
    package = skills_dir / folder
    package.mkdir(parents=True)
    path = package / "SKILL.md"
    path.write_text(f"---\n{frontmatter}\n---\n{body}", encoding="utf-8")
    return path


async def test_turn_shows_the_skill_catalog_without_the_body(tmp_path: Path) -> None:
    paths = resolve_agent_workspace(tmp_path, "main")
    paths.skills.mkdir(parents=True)
    _write_skill(
        paths.skills,
        "sql",
        "name: sql\ndescription: Run a warehouse query.",
        "# SQL\nFull instructions here.\n",
    )
    seen: list[str] = []
    offered: list[list[str]] = []

    async def capture(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str]:
        del messages
        seen.append(info.instructions or "")
        offered.append([tool.name for tool in info.function_tools])
        yield "ok"

    result = await run_turn(
        SESSION,
        "hello",
        ctx=_ctx(MemorySessionStore(), FunctionModel(stream_function=capture), workspace=paths),
    )

    assert result.status == "ok"
    assert seen[0].count(_CATALOG) == 1
    assert "# Skills" not in seen[0]
    assert "Full instructions here." not in seen[0]
    assert "# Identity\nYou are Crabriks, the platform agent main." in seen[0]
    assert f"# Workspace\n{paths.directory.as_posix()}" in seen[0]
    assert offered[0] == ["load_capability", "clock"]
    assert not any(name in offered[0] for name in _FILE_TOOLS)


async def test_turn_loads_a_skill_body_into_the_transcript(tmp_path: Path) -> None:
    paths = resolve_agent_workspace(tmp_path, "main")
    paths.skills.mkdir(parents=True)
    _write_skill(
        paths.skills,
        "sql",
        "name: sql\ndescription: Run a warehouse query.",
        "# SQL\nFull instructions here.\n",
    )

    async def load_then_reply(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        del info
        if "tool-return" not in _parts(messages):
            yield {
                0: DeltaToolCall(
                    name="load_capability",
                    json_args=json.dumps({"id": "sql"}),
                    tool_call_id="call-sql",
                )
            }
            return
        assert _tool_return_text(messages) == _SKILL_BODY
        yield "Loaded skill sql successfully"

    result = await run_turn(
        SESSION,
        "help me query",
        ctx=_ctx(
            MemorySessionStore(),
            FunctionModel(stream_function=load_then_reply),
            workspace=paths,
        ),
    )

    assert result.status == "ok"
    assert result.reply == "Loaded skill sql successfully"
    assert [entry.role for entry in result.transcript] == [
        "user",
        "tool_call",
        "tool_result",
        "assistant",
    ]
    assert result.transcript[1].tool_name == "load_capability"
    assert result.transcript[2].content == _SKILL_BODY


async def test_turn_loads_a_skill_body_larger_than_32kb(tmp_path: Path) -> None:
    paths = resolve_agent_workspace(tmp_path, "main")
    paths.skills.mkdir(parents=True)
    oversize = "x" * 33_000
    _write_skill(paths.skills, "big", "name: big\ndescription: Big skill.", oversize)

    async def load_big(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        del info
        if "tool-return" not in _parts(messages):
            yield {
                0: DeltaToolCall(
                    name="load_capability",
                    json_args=json.dumps({"id": "big"}),
                    tool_call_id="call-big",
                )
            }
            return
        assert oversize in _tool_return_text(messages)
        yield "loaded"

    result = await run_turn(
        SESSION,
        "load big",
        ctx=_ctx(MemorySessionStore(), FunctionModel(stream_function=load_big), workspace=paths),
    )

    assert result.status == "ok"
    assert result.reply == "loaded"
    assert result.transcript[2].content == f"# Skill: big\n\n{oversize}"


async def test_turn_rereads_a_skill_edited_in_the_same_session(tmp_path: Path) -> None:
    paths = resolve_agent_workspace(tmp_path, "main")
    paths.skills.mkdir(parents=True)
    skill = _write_skill(
        paths.skills,
        "sql",
        "name: sql\ndescription: Initial description.",
        "body",
    )
    seen: list[str] = []

    async def capture(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str]:
        del messages
        seen.append(info.instructions or "")
        yield "ok"

    ctx = _ctx(MemorySessionStore(), FunctionModel(stream_function=capture), workspace=paths)
    first = await run_turn(SESSION, "first turn", ctx=ctx)
    assert first.status == "ok"
    assert "- sql: Initial description." in seen[0]

    skill.write_text(
        "---\nname: sql\ndescription: Modified description.\n---\nbody",
        encoding="utf-8",
    )
    second = await run_turn(SESSION, "second turn", ctx=ctx)

    assert second.status == "ok"
    assert "- sql: Modified description." in seen[1]
    assert "- sql: Initial description." not in seen[1]


async def test_turn_omits_blank_and_mismatched_skills_and_defaults_the_name(
    tmp_path: Path,
) -> None:
    paths = resolve_agent_workspace(tmp_path, "main")
    paths.skills.mkdir(parents=True)
    _write_skill(paths.skills, "blank", "name: blank\ndescription: '   '", "secret blank")
    _write_skill(
        paths.skills,
        "mismatch",
        "name: other\ndescription: Should omit.",
        "secret mismatch",
    )
    _write_skill(paths.skills, "noname", "description: Directory name used.", "body of noname")
    seen: list[str] = []

    async def capture(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str]:
        del messages
        seen.append(info.instructions or "")
        yield "ok"

    with pytest.warns(UserWarning, match="Skipping"):
        result = await run_turn(
            SESSION,
            "hello",
            ctx=_ctx(MemorySessionStore(), FunctionModel(stream_function=capture), workspace=paths),
        )

    assert result.status == "ok"
    assert "- noname: Directory name used." in seen[0]
    assert "- blank:" not in seen[0]
    assert "Should omit." not in seen[0]
    assert "secret blank" not in seen[0]
    assert "secret mismatch" not in seen[0]
    assert "other" not in seen[0]


async def test_turn_duplicate_skill_names_fail_before_an_assistant_reply(tmp_path: Path) -> None:
    paths = resolve_agent_workspace(tmp_path, "main")
    paths.skills.mkdir(parents=True)
    # NFKC folds these fullwidth letters onto "sql"; the disk keeps both directories.
    wide = "".join(chr(ord(char) + 0xFEE0) for char in "sql")
    _write_skill(paths.skills, "sql", "name: sql\ndescription: Plain.", "plain")
    _write_skill(paths.skills, wide, f"name: {wide}\ndescription: Wide.", "wide")

    async def reply(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str]:
        del messages, info
        yield "should not run"

    result = await run_turn(
        SESSION,
        "hello",
        ctx=_ctx(MemorySessionStore(), FunctionModel(stream_function=reply), workspace=paths),
    )

    assert result.status == "error"
    assert result.reply == ""
    assert result.error == FAILED_TURN
    assert [entry.role for entry in result.transcript] == ["user"]


async def test_empty_skill_library_offers_only_builtin_tools(tmp_path: Path) -> None:
    paths = resolve_agent_workspace(tmp_path, "main")
    paths.skills.mkdir(parents=True)
    offered: list[list[str]] = []

    async def capture(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str]:
        del messages
        offered.append([tool.name for tool in info.function_tools])
        yield "ok"

    result = await run_turn(
        SESSION,
        "hello",
        ctx=_ctx(MemorySessionStore(), FunctionModel(stream_function=capture), workspace=paths),
    )

    assert result.status == "ok"
    assert offered == [["clock"]]


class _StubServerToolset(AbstractToolset[object]):
    def __init__(
        self,
        server_id: str,
        name: str = "stub",
        description: str = "",
        result: str = "",
        *,
        fails: bool = False,
    ) -> None:
        self._id = server_id
        self._name = name
        self._desc = description
        self._result = result
        self._fails = fails

    @property
    def id(self) -> str:
        return self._id

    async def get_tools(self, ctx: RunContext[object]) -> dict[str, ToolsetTool[object]]:
        del ctx
        tdef = ToolDefinition(
            name=self._name,
            description=self._desc,
            parameters_json_schema={"type": "object"},
        )
        return {
            self._name: ToolsetTool(
                toolset=self,
                tool_def=tdef,
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
        return self._result

    async def list_tools(self) -> list[object]:
        if self._fails:
            raise RuntimeError("Server unavailable")
        return [
            type(
                "Tool",
                (),
                {"name": self._name, "description": self._desc, "input_schema": {}},
            )()
        ]


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
            return _StubServerToolset(
                "billing_srv", "get_balance", "Get billing balance", '{"balance": 100}'
            )
        return _StubServerToolset(
            "uc_srv", "describe_table", "Describe columns of a Unity Catalog table"
        )

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
            return _StubServerToolset("fail_srv", "fail_tool", fails=True)
        return _StubServerToolset(
            "uc_srv", "describe_table", "Describe columns of a Unity Catalog table"
        )

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
    caller_token = "dapi-" + "user-test-auth"

    def factory(srv: MCPServerConfig, token: str) -> AbstractToolset[object]:
        assert token == caller_token
        return _StubServerToolset(
            "system_ai_srv",
            "describe_table",
            "Describe columns of a Unity Catalog table",
            json.dumps({"columns": ["trip_id", "pickup_time", "fare_amount"]}),
        )

    ctx = _ctx(
        MemorySessionStore(),
        FunctionModel(stream_function=uc_assistant),
        emit=emitted_notices,
        mcp_servers=servers,
        user_token=caller_token,
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


@pytest.mark.asyncio
async def test_error_path_scrubs_token_from_transcript_and_notices() -> None:
    caller_token = "dapi-" + "leak-err-auth"

    async def failing_stream(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        del messages, info
        raise RuntimeError(f"Model backend exploded with auth {caller_token}")
        yield ""  # pragma: no cover

    emitted: list[TurnNotice] = []
    ctx = _ctx(
        MemorySessionStore(),
        FunctionModel(stream_function=failing_stream),
        emit=emitted,
        user_token=caller_token,
    )

    result = await run_turn(SESSION, f"query with token {caller_token}", ctx=ctx)

    assert result.status == "error"
    assert result.error is not None
    assert caller_token not in result.error
    for entry in result.transcript:
        assert caller_token not in entry.content
        if entry.tool_name:
            assert caller_token not in entry.tool_name
    for notice in emitted:
        if isinstance(notice, Token):
            assert caller_token not in notice.text
