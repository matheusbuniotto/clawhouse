"""Deterministic system prompt: a cache-stable prefix and a per-turn suffix."""

from collections.abc import Sequence
from dataclasses import dataclass

from crabriks.capabilities.bootstrap import BootstrapContext
from crabriks.capabilities.workspace import WorkspacePaths

AGENT_NAME = "main"
CLOCK_NAME = "clock"
CLOCK_DESCRIPTION = "Return the current UTC time as an ISO-8601 timestamp."
_IDENTITY_FILES = ("SOUL.md", "IDENTITY.md")
_PROJECT_FILES = ("AGENTS.md", "USER.md", "MEMORY.md", "CONTEXT.md")


@dataclass(frozen=True, slots=True)
class ToolCard:
    name: str
    description: str


CLOCK = ToolCard(name=CLOCK_NAME, description=CLOCK_DESCRIPTION)

BUILTIN_TOOLS: tuple[ToolCard, ...] = (CLOCK,)


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


def build_system_prompt(  # noqa: PLR0913
    *,
    tools: Sequence[ToolCard],
    runtime: RuntimeMeta,
    bootstrap: BootstrapContext | None = None,
    workspace: WorkspacePaths | None = None,
    assistant_name: str | None = None,
    signature_emoji: str | None = None,
    birth_ritual: bool = False,
) -> SystemPrompt:
    """Compose the platform agent's prompt. An agent with no tools is refused.

    The prefix depends only on tools, bootstrap context, and workspace.
    The suffix carries the session and, when given, the turn time.
    Skill names are not repeated here; the harness catalog is the only list.
    """
    if not tools:
        raise ValueError("an agent must expose at least one tool")
    sections = (
        _identity(bootstrap, assistant_name=assistant_name, signature_emoji=signature_emoji),
        _tools(tools),
        _birth_ritual() if birth_ritual else None,
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


def _birth_ritual() -> str:
    return (
        "# Birth Ritual\n"
        "You are awakening for the first time. The user has initiated the hatch ritual.\n"
        "Conduct the onboarding birth ritual:\n"
        "- Greet the user warmly and acknowledge awakening.\n"
        "- Guide them to establish:\n"
        "  1. Your preferred name / nickname\n"
        "  2. Your signature emoji\n"
        "  3. The user's role and focus in Databricks\n"
        "  4. Preferred communication tone and directives\n"
        "- Once the user shares these preferences, conclude the ritual and save them "
        "using the save_profile tool."
    )


def _identity(
    bootstrap: BootstrapContext | None,
    *,
    assistant_name: str | None = None,
    signature_emoji: str | None = None,
) -> str:
    name = assistant_name or "Crabriks"
    if signature_emoji and signature_emoji not in name:
        name = f"{name} {signature_emoji}"
    blocks = [f"# Identity\nYou are {name}, the platform agent {AGENT_NAME}."]
    blocks.extend(_blocks(bootstrap, _IDENTITY_FILES))
    return "\n\n".join(blocks)


def _tools(tools: Sequence[ToolCard]) -> str:
    lines = "\n".join(f"- {tool.name}: {tool.description}" for tool in tools)
    return f"# Tools\n{lines}"


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
