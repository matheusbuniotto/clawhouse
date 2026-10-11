"""Tools, skills, Model Context Protocol (MCP), and workspace environments."""

from crabriks.capabilities.bootstrap import BootstrapContext, load_bootstrap
from crabriks.capabilities.mcp import (
    DuplicateMCPServerName,
    MCPCapability,
    MCPServerConfig,
    ScrubbingToolset,
    load_mcp_tools,
    mcp_capability,
    scrub_token,
)
from crabriks.capabilities.skills import loaded_skill_text, skills_capability
from crabriks.capabilities.workspace import WorkspacePaths, resolve_agent_workspace

__all__ = [
    "BootstrapContext",
    "DuplicateMCPServerName",
    "MCPCapability",
    "MCPServerConfig",
    "ScrubbingToolset",
    "WorkspacePaths",
    "load_bootstrap",
    "load_mcp_tools",
    "loaded_skill_text",
    "mcp_capability",
    "resolve_agent_workspace",
    "scrub_token",
    "skills_capability",
]
