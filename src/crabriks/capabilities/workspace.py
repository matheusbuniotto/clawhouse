"""Pure path composer for the platform agent's Git-versioned folder."""

import re
from dataclasses import dataclass
from pathlib import Path

# Names are a single path segment. Traversal is rejected, never normalized away.
_AGENT_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")


class UnsafeAgentName(ValueError):
    """The agent name is not a single safe path segment."""


@dataclass(frozen=True, slots=True)
class WorkspacePaths:
    """Typed paths under `{root}/claw/agents/{name}`. Nothing here is created."""

    directory: Path
    agents: Path
    soul: Path
    identity: Path
    user_file: Path
    memory: Path
    memory_dir: Path
    skills: Path
    context: Path


def resolve_agent_workspace(root: Path, agent_name: str) -> WorkspacePaths:
    """Compose the platform agent folder. Does not touch the filesystem."""
    if _AGENT_NAME.fullmatch(agent_name) is None:
        raise UnsafeAgentName(agent_name)
    directory = Path(root) / "claw" / "agents" / agent_name
    return WorkspacePaths(
        directory=directory,
        agents=directory / "AGENTS.md",
        soul=directory / "SOUL.md",
        identity=directory / "IDENTITY.md",
        user_file=directory / "USER.md",
        memory=directory / "MEMORY.md",
        memory_dir=directory / "memory",
        skills=directory / "skills",
        context=directory / "context",
    )
