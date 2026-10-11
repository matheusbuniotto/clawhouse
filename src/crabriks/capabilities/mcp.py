import logging
import math
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import asdict, dataclass, is_dataclass, replace
from typing import Any, cast
from urllib.parse import urlparse

from fastmcp.client.transports import StreamableHttpTransport
from pydantic import BaseModel, ValidationError
from pydantic_ai import RunContext
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.mcp import MCPToolset
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.toolsets import AbstractToolset, AgentToolset, CombinedToolset, ToolsetTool
from pydantic_ai.toolsets.wrapper import WrapperToolset

logger = logging.getLogger("crabriks.mcp")


class InsecureMCPEndpoint(ValueError):
    """MCP server endpoints must use https in v1."""


class DuplicateMCPServerName(ValueError):
    """MCP server names must be unique."""


def validate_mcp_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme.lower() != "https":
        raise InsecureMCPEndpoint(f"MCP server URL must use https: {url}")


@dataclass(frozen=True, slots=True)
class MCPServerConfig:
    name: str
    url: str
    timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        validate_mcp_url(self.url)
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError(
                f"timeout_seconds must be a positive finite number, got {self.timeout_seconds}"
            )


MAX_TOOL_NAME_LENGTH = 64


def sanitize_identifier(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_]", "_", value)
    return cleaned.strip("_") or "tool"


def safe_tool_name(server_name: str, tool_name: str) -> str:
    safe_srv = sanitize_identifier(server_name)
    safe_tool = sanitize_identifier(tool_name)
    combined = f"{safe_srv}__{safe_tool}"
    return combined[:MAX_TOOL_NAME_LENGTH]


@dataclass(frozen=True, slots=True)
class RawMCPTool:
    server_name: str
    tool_name: str
    description: str
    parameters_schema: dict[str, object] | None = None


@dataclass(frozen=True, slots=True)
class DisambiguatedTool:
    server_name: str
    original_name: str
    safe_name: str
    description: str
    parameters_schema: dict[str, object] | None = None


def disambiguate_tool_names(
    tools: Sequence[RawMCPTool],
    max_length: int = MAX_TOOL_NAME_LENGTH,
) -> list[DisambiguatedTool]:
    used_names: set[str] = set()
    results: list[DisambiguatedTool] = []
    # Sort deterministically by (server_name, tool_name) prior to suffix disambiguation
    sorted_tools = sorted(tools, key=lambda t: (t.server_name, t.tool_name))

    for raw in sorted_tools:
        base = safe_tool_name(raw.server_name, raw.tool_name)[:max_length]
        if base not in used_names:
            assigned = base
        else:
            counter = 1
            while True:
                suffix = f"_{counter}"
                prefix = base[: max_length - len(suffix)]
                candidate = f"{prefix}{suffix}"
                if candidate not in used_names:
                    assigned = candidate
                    break
                counter += 1
        used_names.add(assigned)
        results.append(
            DisambiguatedTool(
                server_name=raw.server_name,
                original_name=raw.tool_name,
                safe_name=assigned,
                description=raw.description,
                parameters_schema=raw.parameters_schema,
            )
        )

    # Sort deterministically by safe name
    results.sort(key=lambda t: t.safe_name)
    return results


def scrub_token(text: str, token: str) -> str:
    if not token or not text:
        return text
    return text.replace(token, "[REDACTED]")


def _scrub_pydantic(obj: BaseModel, token: str) -> object:
    dumped = scrub_object(obj.model_dump(), token)
    with suppress(ValidationError, TypeError, ValueError):
        return type(obj).model_validate(dumped)
    return dumped


def _scrub_dataclass(obj: object, token: str) -> object:
    dumped = scrub_object(asdict(obj), token)  # type: ignore[arg-type]
    with suppress(TypeError, ValueError):
        return type(obj)(**dumped)  # type: ignore[call-arg]
    return dumped


def _scrub_dict_object(obj: object, token: str) -> object:
    with suppress(AttributeError, TypeError):
        for k, v in list(vars(obj).items()):
            if not k.startswith("_"):
                scrubbed_v = scrub_object(v, token)
                if scrubbed_v != v:
                    setattr(obj, k, scrubbed_v)
    return obj


def _scrub_typed_object(obj: object, token: str) -> object:
    if isinstance(obj, BaseModel):
        return _scrub_pydantic(obj, token)
    if is_dataclass(obj) and not isinstance(obj, type):
        return _scrub_dataclass(obj, token)
    if hasattr(obj, "__dict__"):
        return _scrub_dict_object(obj, token)
    return obj


def scrub_object(obj: object, token: str) -> object:
    if not token or obj is None:
        return obj
    if isinstance(obj, str):
        return scrub_token(obj, token)
    if isinstance(obj, dict):
        return {
            (scrub_token(k, token) if isinstance(k, str) else k): scrub_object(v, token)
            for k, v in obj.items()
        }
    if isinstance(obj, list | tuple):
        items = [scrub_object(v, token) for v in obj]
        return tuple(items) if isinstance(obj, tuple) else items
    return _scrub_typed_object(obj, token)


def _scrub_tool_def(tool_def: ToolDefinition, token: str) -> ToolDefinition:
    if not token:
        return tool_def
    desc = (
        scrub_token(tool_def.description, token) if tool_def.description else tool_def.description
    )
    raw_schema = tool_def.parameters_json_schema
    scrubbed_schema = (
        cast(dict[str, object], scrub_object(raw_schema, token))
        if isinstance(raw_schema, dict)
        else raw_schema
    )
    return replace(
        tool_def,
        description=desc,
        parameters_json_schema=scrubbed_schema,
    )


@dataclass
class ScrubbingToolset(WrapperToolset[object]):
    token: str

    async def get_tools(self, ctx: RunContext[object]) -> dict[str, ToolsetTool[object]]:
        tools = await self.wrapped.get_tools(ctx)
        if not self.token:
            return tools
        return {
            name: replace(t, tool_def=_scrub_tool_def(t.tool_def, self.token))
            for name, t in tools.items()
        }

    async def call_tool(
        self,
        name: str,
        tool_args: dict[str, object],
        ctx: RunContext[object],
        tool: ToolsetTool[object],
    ) -> object:
        try:
            res = await self.wrapped.call_tool(name, tool_args, ctx, tool)
        except Exception as exc:
            if self.token:
                raise RuntimeError(scrub_token(str(exc), self.token)) from None
            raise
        return scrub_object(res, self.token)


@dataclass(frozen=True, slots=True)
class MCPBundle:
    tools: tuple[DisambiguatedTool, ...]
    toolsets: tuple[AbstractToolset, ...]


def create_mcp_toolset(server: MCPServerConfig, token: str) -> MCPToolset:
    validate_mcp_url(server.url)
    headers = {"Authorization": f"Bearer {token}"} if token else None
    transport = StreamableHttpTransport(server.url, headers=headers)
    return MCPToolset(
        transport,
        init_timeout=server.timeout_seconds,
        read_timeout=server.timeout_seconds,
    )


async def _fetch_server_tools(
    toolset: AbstractToolset[object],
    server_name: str,
    token: str = "",
) -> list[RawMCPTool]:
    list_tools_fn = getattr(toolset, "list_tools", None)
    if callable(list_tools_fn):
        res = list_tools_fn()
        raw_items = (await res) if isinstance(res, Awaitable) else res
        items = list(raw_items) if isinstance(raw_items, list | tuple) else []
    else:
        dict_tools = await toolset.get_tools(None)  # type: ignore[arg-type]
        items = list(dict_tools.values())
    return [_raw_tool_from_item(item, server_name, token) for item in items if _item_name(item)]


def _item_name(item: object) -> str:
    name = getattr(item, "name", None)
    tool_def = getattr(item, "tool_def", None)
    if name is None and tool_def is not None:
        name = getattr(tool_def, "name", None)
    return str(name or "")


def _raw_tool_from_item(item: object, server_name: str, token: str = "") -> RawMCPTool:
    name = _item_name(item)
    desc = getattr(item, "description", None) or ""
    schema = getattr(item, "input_schema", None)
    tool_def = getattr(item, "tool_def", None)
    if not desc and tool_def is not None:
        desc = getattr(tool_def, "description", "") or ""
    if schema is None and tool_def is not None:
        schema = getattr(tool_def, "parameters_json_schema", None)
    scrubbed_schema = (
        cast(dict[str, object], scrub_object(schema, token)) if isinstance(schema, dict) else None
    )
    return RawMCPTool(
        server_name=server_name,
        tool_name=name,
        description=scrub_token(desc, token),
        parameters_schema=scrubbed_schema,
    )


def _validate_unique_servers(servers: Sequence[MCPServerConfig]) -> None:
    seen_names: set[str] = set()
    for server in servers:
        validate_mcp_url(server.url)
        if server.name in seen_names:
            raise DuplicateMCPServerName(f"Duplicate MCP server name: {server.name!r}")
        seen_names.add(server.name)


def _build_active_toolsets(
    server_toolsets: Mapping[str, AbstractToolset[object]],
    disambiguated: Sequence[DisambiguatedTool],
    token: str,
) -> tuple[AbstractToolset[object], ...]:
    active: list[AbstractToolset[object]] = []
    for server_name, toolset in server_toolsets.items():
        # Pydantic AI RenamedToolset contract:
        # RenamedToolset(name_map) expects `dict[str, str]` mapping new safe names to
        # original tool names:
        #   - get_tools() flips it ({v: k for k, v in name_map.items()}) to expose safe names.
        #   - call_tool(name) resolves `self.name_map.get(name, name)` to invoke original names.
        new_to_original_name_map = {
            t.safe_name: t.original_name for t in disambiguated if t.server_name == server_name
        }
        if new_to_original_name_map:
            renamed = toolset.renamed(new_to_original_name_map)
            active.append(ScrubbingToolset(renamed, token=token) if token else renamed)
    return tuple(active)


async def load_mcp_tools(
    servers: Sequence[MCPServerConfig],
    token: str,
    *,
    toolset_factory: Callable[[MCPServerConfig, str], AbstractToolset[object]] | None = None,
) -> MCPBundle:
    if not servers:
        return MCPBundle(tools=(), toolsets=())
    _validate_unique_servers(servers)
    if not token:
        logger.warning("No user token provided; omitting MCP servers for turn")
        return MCPBundle(tools=(), toolsets=())
    raw_tools: list[RawMCPTool] = []
    server_toolsets: dict[str, AbstractToolset[object]] = {}

    for server in servers:
        try:
            toolset = (
                toolset_factory(server, token)
                if toolset_factory is not None
                else create_mcp_toolset(server, token)
            )
            tools = await _fetch_server_tools(toolset, server.name, token)
            raw_tools.extend(tools)
            server_toolsets[server.name] = toolset
        except Exception as exc:  # noqa: BLE001
            scrubbed = scrub_token(str(exc), token)
            logger.warning(
                "MCP server %r omitted; tools/list failed: %s",
                server.name,
                scrubbed,
            )
            continue

    disambiguated = disambiguate_tool_names(raw_tools)
    active_toolsets = _build_active_toolsets(server_toolsets, disambiguated, token)
    return MCPBundle(
        tools=tuple(disambiguated),
        toolsets=active_toolsets,
    )


@dataclass
class MCPCapability(AbstractCapability[Any]):
    """Attached per-turn caller MCP tools as a capability."""

    tools: tuple[DisambiguatedTool, ...] = ()
    toolsets: tuple[AbstractToolset[object], ...] = ()
    id: str | None = "mcp"

    def get_toolset(self) -> AgentToolset[Any] | None:
        if not self.toolsets:
            return None
        if len(self.toolsets) == 1:
            return self.toolsets[0]
        return CombinedToolset(self.toolsets)


async def mcp_capability(
    servers: Sequence[MCPServerConfig],
    token: str,
    *,
    toolset_factory: Callable[[MCPServerConfig, str], AbstractToolset[object]] | None = None,
) -> MCPCapability | None:
    """Attach the caller's MCP tools for this turn, or nothing when absent."""
    bundle = await load_mcp_tools(servers, token, toolset_factory=toolset_factory)
    if not bundle.tools and not bundle.toolsets:
        return None
    return MCPCapability(tools=bundle.tools, toolsets=bundle.toolsets)
