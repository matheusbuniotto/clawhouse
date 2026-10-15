"""Backward-compatible facade for clawhouse.capabilities.workspace."""

from clawhouse.capabilities.workspace import (
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
