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
    context_file: Path
    workspace_dir: Path


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
        context_file=directory / "CONTEXT.md",
        workspace_dir=directory / "workspace",
    )


def provision_agent_workspace(  # noqa: PLR0913
    root: Path,
    agent_name: str,
    agents_text: str,
    identity_name: str,
    *,
    signature_emoji: str = "🤖",
    soul_text: str | None = None,
    context_text: str | None = None,
) -> WorkspacePaths:
    """Provision a physical agent workspace folder and seed its bootstrap files."""
    paths = resolve_agent_workspace(root, agent_name)
    paths.directory.mkdir(parents=True, exist_ok=True)
    paths.workspace_dir.mkdir(parents=True, exist_ok=True)
    paths.skills.mkdir(parents=True, exist_ok=True)
    paths.context.mkdir(parents=True, exist_ok=True)

    paths.agents.write_text(agents_text, encoding="utf-8")
    identity_content = f"Name: {identity_name}\nEmoji: {signature_emoji}\n"
    paths.identity.write_text(identity_content, encoding="utf-8")

    if soul_text is not None:
        paths.soul.write_text(soul_text, encoding="utf-8")
    if context_text is not None:
        paths.context_file.write_text(context_text, encoding="utf-8")

    return paths
