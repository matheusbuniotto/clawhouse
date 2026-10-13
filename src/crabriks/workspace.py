"""Backward-compatible facade for crabriks.capabilities.workspace."""

from crabriks.capabilities.workspace import (
    UnsafeAgentName,
    WorkspacePaths,
    provision_agent_workspace,
    resolve_agent_workspace,
)

__all__ = [
    "UnsafeAgentName",
    "WorkspacePaths",
    "provision_agent_workspace",
    "resolve_agent_workspace",
]
