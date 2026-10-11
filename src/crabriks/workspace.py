"""Backward-compatible facade for crabriks.capabilities.workspace."""

from crabriks.capabilities.workspace import (
    UnsafeAgentName,
    WorkspacePaths,
    resolve_agent_workspace,
)

__all__ = ["UnsafeAgentName", "WorkspacePaths", "resolve_agent_workspace"]
