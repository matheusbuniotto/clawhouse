"""MCP tools over streamable-http with per-user Databricks tokens."""

import json
import logging
from collections.abc import AsyncIterator
from typing import cast

import pytest
from pydantic_ai import Agent, RunContext
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.toolsets import AbstractToolset, ToolsetTool
from pydantic_core import SchemaValidator, core_schema

from crabriks.mcp import (
    MAX_TOOL_NAME_LENGTH,
    DuplicateMCPServerName,
    InsecureMCPEndpoint,
    MCPServerConfig,
    RawMCPTool,
    disambiguate_tool_names,
    load_mcp_tools,
    safe_tool_name,
    scrub_object,
    scrub_token,
    validate_mcp_url,
)
from crabriks.settings import mcp_servers_from_env, settings_from_env

MOCK_USER_AUTH = "dapi-" + "super-user-auth"


class _GoodToolset(AbstractToolset[object]):
    @property
    def id(self) -> str:
        return "good"

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
        return "ok"

    async def list_tools(self) -> list[object]:
        return [
            type("Tool", (), {"name": "query", "description": "Good query", "input_schema": {}})()
        ]


class _FailingToolset(AbstractToolset[object]):
    @property
    def id(self) -> str:
        return "fail"

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
        raise RuntimeError(f"Connection failed with Bearer {MOCK_USER_AUTH}")


def test_mcp_server_config_accepts_https_url() -> None:
    config = MCPServerConfig(
        name="system.ai",
        url="https://adb-123.databricks.com/ai-gateway/mcp-services/system.ai",
    )
    assert config.name == "system.ai"
    assert config.url == "https://adb-123.databricks.com/ai-gateway/mcp-services/system.ai"


def test_non_https_mcp_url_is_rejected() -> None:
    with pytest.raises(InsecureMCPEndpoint, match="must use https"):
        validate_mcp_url("http://adb-123.databricks.com/mcp")

    with pytest.raises(InsecureMCPEndpoint, match="must use https"):
        MCPServerConfig(name="insecure", url="http://insecure.example.com")


def test_mcp_servers_parsed_from_env() -> None:
    raw = json.dumps(
        [
            {
                "name": "system.ai",
                "url": "https://adb-123.databricks.com/ai-gateway/mcp-services/system.ai",
            }
        ]
    )
    servers = mcp_servers_from_env({"CRABRIKS_MCP_SERVERS": raw})
    assert len(servers) == 1
    assert servers[0].name == "system.ai"
    assert servers[0].url == "https://adb-123.databricks.com/ai-gateway/mcp-services/system.ai"

    settings = settings_from_env({"CRABRIKS_MCP_SERVERS": raw})
    assert len(settings.mcp_servers) == 1
    assert settings.mcp_servers[0].name == "system.ai"


def test_tool_name_namespacing_and_sanitization() -> None:
    assert safe_tool_name("system.ai", "get_table") == "system_ai__get_table"
    assert safe_tool_name("catalog-service", "list-schemas") == "catalog_service__list_schemas"
    assert safe_tool_name("my server", "do:something") == "my_server__do_something"


def test_tool_name_capped_at_max_length() -> None:
    long_server = "a" * 40
    long_tool = "b" * 40
    result = safe_tool_name(long_server, long_tool)
    assert len(result) == MAX_TOOL_NAME_LENGTH
    assert result == (f"{long_server}__{long_tool}")[:MAX_TOOL_NAME_LENGTH]


def test_disambiguate_tool_names_resolves_collisions_deterministically() -> None:
    tools_forward = [
        RawMCPTool(server_name="system.ai", tool_name="query", description="Query table"),
        RawMCPTool(server_name="system_ai", tool_name="query", description="Another query"),
    ]
    tools_reversed = list(reversed(tools_forward))

    resolved_fwd = disambiguate_tool_names(tools_forward)
    resolved_rev = disambiguate_tool_names(tools_reversed)

    assert [t.safe_name for t in resolved_fwd] == ["system_ai__query", "system_ai__query_1"]
    assert [t.safe_name for t in resolved_rev] == ["system_ai__query", "system_ai__query_1"]


def test_disambiguate_tool_names_preserves_length_cap_on_collision() -> None:
    long_tool = "x" * 60
    tools = [
        RawMCPTool(server_name="srv", tool_name=long_tool, description="First"),
        RawMCPTool(server_name="srv", tool_name=long_tool, description="Second"),
    ]
    resolved = disambiguate_tool_names(tools)
    assert len(resolved[0].safe_name) == MAX_TOOL_NAME_LENGTH
    assert len(resolved[1].safe_name) == MAX_TOOL_NAME_LENGTH
    assert resolved[0].safe_name != resolved[1].safe_name
    assert any(t.safe_name.endswith("_1") for t in resolved)


def test_tool_ordering_is_deterministic_by_safe_name() -> None:
    tools = [
        RawMCPTool(server_name="srv", tool_name="zebra", description="Z"),
        RawMCPTool(server_name="srv", tool_name="apple", description="A"),
        RawMCPTool(server_name="srv", tool_name="mango", description="M"),
    ]
    resolved = disambiguate_tool_names(tools)
    names = [t.safe_name for t in resolved]
    assert names == ["srv__apple", "srv__mango", "srv__zebra"]


def test_token_is_scrubbed_from_text() -> None:
    sample_text = "dapi-" + "sample-redaction-val"
    error_msg = f"HTTP 401 Unauthorized for Bearer {sample_text} when connecting to https://host"
    scrubbed = scrub_token(error_msg, sample_text)
    assert sample_text not in scrubbed
    assert "[REDACTED]" in scrubbed
    assert scrub_token("ordinary message", "") == "ordinary message"


@pytest.mark.asyncio
async def test_load_mcp_tools_with_failing_server_omits_and_survives(
    caplog: pytest.LogCaptureFixture,
) -> None:
    servers = [
        MCPServerConfig(name="good_srv", url="https://good.example.com/mcp"),
        MCPServerConfig(name="fail_srv", url="https://fail.example.com/mcp"),
    ]

    def factory(srv: MCPServerConfig, token: str) -> AbstractToolset:
        del token
        if srv.name == "good_srv":
            return _GoodToolset()
        return _FailingToolset()

    with caplog.at_level(logging.WARNING):
        bundle = await load_mcp_tools(servers, MOCK_USER_AUTH, toolset_factory=factory)

    assert len(bundle.tools) == 1
    assert bundle.tools[0].safe_name == "good_srv__query"
    assert len(bundle.toolsets) == 1

    for record in caplog.records:
        assert MOCK_USER_AUTH not in record.message
        assert "[REDACTED]" in record.message


@pytest.mark.asyncio
async def test_load_mcp_tools_scrubs_token_from_descriptions() -> None:
    class _LeakyDescToolset(AbstractToolset[object]):
        @property
        def id(self) -> str:
            return "leaky"

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
            return "ok"

        async def list_tools(self) -> list[object]:
            return [
                type(
                    "Tool",
                    (),
                    {
                        "name": "read_secret",
                        "description": f"Tool description containing token {MOCK_USER_AUTH}",
                        "input_schema": {},
                    },
                )()
            ]

    servers = [MCPServerConfig(name="leaky_srv", url="https://leaky.example.com/mcp")]
    bundle = await load_mcp_tools(
        servers, MOCK_USER_AUTH, toolset_factory=lambda _s, _t: _LeakyDescToolset()
    )

    assert len(bundle.tools) == 1
    assert MOCK_USER_AUTH not in bundle.tools[0].description
    assert "[REDACTED]" in bundle.tools[0].description


@pytest.mark.asyncio
async def test_token_scrubbed_from_tool_parameter_schema() -> None:
    class _LeakySchemaToolset(AbstractToolset[object]):
        @property
        def id(self) -> str:
            return "leaky_schema"

        async def get_tools(self, ctx: RunContext[object]) -> dict[str, ToolsetTool[object]]:
            del ctx
            td = ToolDefinition(
                name="read_schema",
                description="desc",
                parameters_json_schema={
                    "type": "object",
                    "properties": {
                        f"prop_{MOCK_USER_AUTH}": {
                            "type": "string",
                            "description": f"param {MOCK_USER_AUTH}",
                        }
                    },
                },
            )
            return {
                "read_schema": ToolsetTool(
                    toolset=self,
                    tool_def=td,
                    max_retries=1,
                    args_validator=SchemaValidator(core_schema.any_schema()),
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
            return "ok"

    servers = [MCPServerConfig(name="leaky_srv", url="https://leaky.example.com/mcp")]
    bundle = await load_mcp_tools(
        servers, MOCK_USER_AUTH, toolset_factory=lambda _s, _t: _LeakySchemaToolset()
    )

    assert len(bundle.tools) == 1
    schema_str = json.dumps(bundle.tools[0].parameters_schema)
    assert MOCK_USER_AUTH not in schema_str
    assert "[REDACTED]" in schema_str

    tools_dict = await bundle.toolsets[0].get_tools(cast(RunContext[object], None))
    first_tool = next(iter(tools_dict.values()))
    exposed_schema_str = json.dumps(first_tool.tool_def.parameters_json_schema)
    assert MOCK_USER_AUTH not in exposed_schema_str
    assert "[REDACTED]" in exposed_schema_str


@pytest.mark.asyncio
async def test_invoke_renamed_mcp_tool_maps_safe_name_to_original_server_name() -> None:
    """Verify that RenamedToolset exposes safe_name and invokes original tool name on call."""
    called_names: list[str] = []

    class _TrackingToolset(AbstractToolset[object]):
        @property
        def id(self) -> str:
            return "track"

        async def get_tools(self, ctx: RunContext[object]) -> dict[str, ToolsetTool[object]]:
            del ctx
            tool_def = ToolDefinition(
                name="query",
                description="Query table",
                parameters_json_schema={"type": "object"},
            )
            return {
                "query": ToolsetTool(
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
            del tool_args, ctx, tool
            called_names.append(name)
            return "query_result"

        async def list_tools(self) -> list[object]:
            return [
                type("Tool", (), {"name": "query", "description": "Query", "input_schema": {}})()
            ]

    servers = [MCPServerConfig(name="system.ai", url="https://example.com/mcp")]
    bundle = await load_mcp_tools(
        servers, MOCK_USER_AUTH, toolset_factory=lambda _s, _t: _TrackingToolset()
    )

    # 1. Verify get_tools exposes safe_name to the model
    exposed_tools = await bundle.toolsets[0].get_tools(cast(RunContext[object], None))
    assert "system_ai__query" in exposed_tools
    assert "query" not in exposed_tools

    # 2. Verify model calling safe_name invokes the original tool name on the server
    async def fn(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        del info
        tool_returns = [
            getattr(part, "content", None)
            for m in messages
            if hasattr(m, "parts")
            for part in m.parts  # type: ignore[attr-defined]
            if getattr(part, "part_kind", None) == "tool-return"
        ]
        if not tool_returns:
            yield {0: DeltaToolCall(name="system_ai__query", json_args="{}", tool_call_id="c1")}
            return
        received_returns = tool_returns
        assert len(received_returns) == 1
        yield "done"

    agent = Agent(FunctionModel(stream_function=fn), toolsets=bundle.toolsets)
    async with agent.run_stream("test") as stream:
        async for _ in stream.stream_text():
            pass

    assert called_names == ["query"]


def test_invalid_mcp_timeout_is_rejected_or_defaulted() -> None:
    with pytest.raises(ValueError, match="positive finite number"):
        MCPServerConfig(name="bad", url="https://example.com", timeout_seconds=-5.0)

    with pytest.raises(ValueError, match="positive finite number"):
        MCPServerConfig(name="bad", url="https://example.com", timeout_seconds=float("nan"))

    raw = json.dumps([{"name": "srv", "url": "https://example.com", "timeout_seconds": -10}])
    parsed = mcp_servers_from_env({"CRABRIKS_MCP_SERVERS": raw})
    assert parsed[0].timeout_seconds == 30.0


@pytest.mark.asyncio
async def test_bundle_scrubs_token_from_tool_call_result_at_boundary() -> None:
    class _LeakyResultToolset(AbstractToolset[object]):
        @property
        def id(self) -> str:
            return "leaky_res"

        async def get_tools(self, ctx: RunContext[object]) -> dict[str, ToolsetTool[object]]:
            del ctx
            tdef = ToolDefinition(
                name="leak",
                description="Leaky tool",
                parameters_json_schema={"type": "object"},
            )
            return {
                "leak": ToolsetTool(
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
            return {"secret_data": MOCK_USER_AUTH}

        async def list_tools(self) -> list[object]:
            return [type("Tool", (), {"name": "leak", "description": "L", "input_schema": {}})()]

    servers = [MCPServerConfig(name="srv", url="https://example.com/mcp")]
    bundle = await load_mcp_tools(
        servers, MOCK_USER_AUTH, toolset_factory=lambda _s, _t: _LeakyResultToolset()
    )

    received_returns: list[object] = []

    async def fn(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        del info
        tool_returns = [
            getattr(part, "content", None)
            for m in messages
            if hasattr(m, "parts")
            for part in m.parts
            if getattr(part, "part_kind", None) == "tool-return"
        ]
        if not tool_returns:
            yield {0: DeltaToolCall(name="srv__leak", json_args="{}", tool_call_id="c1")}
            return
        received_returns.extend(tool_returns)
        yield "done"

    agent = Agent(FunctionModel(stream_function=fn), toolsets=bundle.toolsets)
    async with agent.run_stream("test") as stream:
        async for _ in stream.stream_text():
            pass

    assert len(received_returns) == 1
    content_str = str(received_returns[0])
    assert MOCK_USER_AUTH not in content_str
    assert "[REDACTED]" in content_str


@pytest.mark.asyncio
async def test_duplicate_mcp_server_names_rejected_in_load_mcp_tools() -> None:
    servers = [
        MCPServerConfig(name="dupe", url="https://a.example.com/mcp"),
        MCPServerConfig(name="dupe", url="https://b.example.com/mcp"),
    ]
    with pytest.raises(DuplicateMCPServerName, match="Duplicate MCP server name: 'dupe'"):
        await load_mcp_tools(servers, "test-" + "token")


def test_duplicate_mcp_server_names_rejected_in_settings() -> None:
    raw = json.dumps(
        [
            {"name": "dupe", "url": "https://a.example.com/mcp"},
            {"name": "dupe", "url": "https://b.example.com/mcp"},
        ]
    )
    with pytest.raises(DuplicateMCPServerName, match="Duplicate MCP server name: 'dupe'"):
        mcp_servers_from_env({"CRABRIKS_MCP_SERVERS": raw})


@pytest.mark.asyncio
async def test_bundle_scrubs_token_from_typed_tool_call_result() -> None:
    from dataclasses import dataclass

    import mcp.types as mcp_t

    @dataclass
    class _CustomPayload:
        payload_text: str

    class _TypedResultToolset(AbstractToolset[object]):
        @property
        def id(self) -> str:
            return "typed_res"

        async def get_tools(self, ctx: RunContext[object]) -> dict[str, ToolsetTool[object]]:
            del ctx
            tdef = ToolDefinition(
                name="typed_tool",
                description="Typed tool",
                parameters_json_schema={"type": "object"},
            )
            return {
                "typed_tool": ToolsetTool(
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
            return mcp_t.CallToolResult(
                content=[mcp_t.TextContent(type="text", text=f"bearer {MOCK_USER_AUTH}")]
            )

        async def list_tools(self) -> list[object]:
            return [
                type("Tool", (), {"name": "typed_tool", "description": "T", "input_schema": {}})()
            ]

    servers = [MCPServerConfig(name="srv", url="https://example.com/mcp")]
    bundle = await load_mcp_tools(
        servers, MOCK_USER_AUTH, toolset_factory=lambda _s, _t: _TypedResultToolset()
    )

    received_returns: list[object] = []

    async def fn(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        del info
        tool_returns = [
            getattr(part, "content", None)
            for m in messages
            if hasattr(m, "parts")
            for part in m.parts
            if getattr(part, "part_kind", None) == "tool-return"
        ]
        if not tool_returns:
            yield {0: DeltaToolCall(name="srv__typed_tool", json_args="{}", tool_call_id="c1")}
            return
        received_returns.extend(tool_returns)
        yield "done"

    agent = Agent(FunctionModel(stream_function=fn), toolsets=bundle.toolsets)
    async with agent.run_stream("test") as stream:
        async for _ in stream.stream_text():
            pass

    assert len(received_returns) == 1
    content_item = received_returns[0]
    content_str = str(content_item)
    assert MOCK_USER_AUTH not in content_str
    assert "[REDACTED]" in content_str

    dc_scrubbed = scrub_object(
        _CustomPayload(payload_text=f"bearer {MOCK_USER_AUTH}"), MOCK_USER_AUTH
    )
    assert isinstance(dc_scrubbed, _CustomPayload)
    assert MOCK_USER_AUTH not in dc_scrubbed.payload_text
    assert "[REDACTED]" in dc_scrubbed.payload_text
