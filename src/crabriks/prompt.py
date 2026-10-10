"""Deterministic system prompt: a cache-stable prefix and a per-turn suffix."""

from collections.abc import Sequence
from dataclasses import dataclass

from crabriks.bootstrap import BootstrapContext
from crabriks.workspace import WorkspacePaths

AGENT_NAME = "main"
CLOCK_NAME = "clock"
CLOCK_DESCRIPTION = "Return the current UTC time as an ISO-8601 timestamp."
_IDENTITY_FILES = ("SOUL.md", "IDENTITY.md")
_PROJECT_FILES = ("AGENTS.md", "USER.md", "MEMORY.md")


@dataclass(frozen=True, slots=True)
class ToolCard:
    name: str
    description: str


CLOCK = ToolCard(name=CLOCK_NAME, description=CLOCK_DESCRIPTION)


@dataclass(frozen=True, slots=True)
class SkillCard:
    name: str
    description: str


@dataclass(frozen=True, slots=True)
class RuntimeMeta:
    """Per-turn suffix. The prefix does not depend on it."""

    session_id: str
    time: str | None = None


@dataclass(frozen=True, slots=True)
class SystemPrompt:
    """`prefix` is stable for a given tool list. `suffix` carries the session."""

    prefix: str
    suffix: str

    @property
    def text(self) -> str:
        return f"{self.prefix}\n\n{self.suffix}"


def build_system_prompt(
    *,
    tools: Sequence[ToolCard],
    runtime: RuntimeMeta,
    bootstrap: BootstrapContext | None = None,
    workspace: WorkspacePaths | None = None,
    skills: Sequence[SkillCard] = (),
) -> SystemPrompt:
    """Compose the platform agent's prompt. An agent with no tools is refused.

    The prefix depends only on tools, skills, bootstrap context, and workspace.
    The suffix carries the session and, when given, the turn time.
    """
    if not tools:
        raise ValueError("an agent must expose at least one tool")
    sections = (
        _identity(bootstrap),
        _tools(tools),
        _skills(skills),
        _project(bootstrap),
        _workspace(workspace),
    )
    prefix = "\n\n".join(section for section in sections if section)
    return SystemPrompt(prefix=prefix, suffix=_runtime(runtime))


def _runtime(runtime: RuntimeMeta) -> str:
    lines = [f"session_id: {runtime.session_id}"]
    if runtime.time:
        lines.append(f"time: {runtime.time}")
    return "# Runtime\n" + "\n".join(lines)


def _identity(bootstrap: BootstrapContext | None) -> str:
    blocks = [f"# Identity\nYou are Crabriks, the platform agent {AGENT_NAME}."]
    blocks.extend(_blocks(bootstrap, _IDENTITY_FILES))
    return "\n\n".join(blocks)


def _tools(tools: Sequence[ToolCard]) -> str:
    lines = "\n".join(f"- {tool.name}: {tool.description}" for tool in tools)
    return f"# Tools\n{lines}"


def _skills(skills: Sequence[SkillCard]) -> str | None:
    if not skills:
        return None
    lines = "\n".join(f"- {skill.name}: {skill.description}" for skill in skills)
    return f"# Skills\n{lines}"


def _project(bootstrap: BootstrapContext | None) -> str | None:
    if bootstrap is None:
        return None
    blocks = _blocks(bootstrap, _PROJECT_FILES)
    if bootstrap.notice:
        blocks.append(bootstrap.notice)
    if not blocks:
        return None
    return "# Project Context\n" + "\n\n".join(blocks)


def _workspace(workspace: WorkspacePaths | None) -> str | None:
    if workspace is None:
        return None
    return f"# Workspace\n{workspace.directory.as_posix()}"


def _blocks(bootstrap: BootstrapContext | None, names: tuple[str, ...]) -> list[str]:
    if bootstrap is None:
        return []
    by_name = {item.name: item.text for item in bootstrap.files}
    return [f"## {name}\n{by_name[name]}" for name in names if by_name.get(name)]
