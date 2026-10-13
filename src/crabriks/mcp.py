"""Backward-compatible facade for crabriks.capabilities.mcp."""

from crabriks.capabilities.mcp import (
    MAX_TOOL_NAME_LENGTH,
    DuplicateMCPServerName,
    InsecureMCPEndpoint,
    MCPCapability,
    MCPServerConfig,
    RawMCPTool,
    ScrubbingToolset,
    disambiguate_tool_names,
    load_mcp_tools,
    mcp_capability,
    safe_tool_name,
    scrub_object,
    scrub_token,
    validate_mcp_url,
)

__all__ = [
    "MAX_TOOL_NAME_LENGTH",
    "DuplicateMCPServerName",
    "InsecureMCPEndpoint",
    "MCPCapability",
    "MCPServerConfig",
    "RawMCPTool",
    "ScrubbingToolset",
    "disambiguate_tool_names",
    "load_mcp_tools",
    "mcp_capability",
    "safe_tool_name",
    "scrub_object",
    "scrub_token",
    "validate_mcp_url",
]
