"""Deterministic system prompt: a cache-stable prefix and a per-turn suffix."""

from collections.abc import Sequence
from dataclasses import dataclass

AGENT_NAME = "main"
CLOCK_NAME = "clock"
CLOCK_DESCRIPTION = "Return the current UTC time as an ISO-8601 timestamp."


@dataclass(frozen=True, slots=True)
class ToolCard:
    name: str
    description: str


CLOCK = ToolCard(name=CLOCK_NAME, description=CLOCK_DESCRIPTION)


@dataclass(frozen=True, slots=True)
class SystemPrompt:
    """`prefix` is stable for a given tool list. `suffix` carries the session."""

    prefix: str
    suffix: str

    @property
    def text(self) -> str:
        return f"{self.prefix}\n\n{self.suffix}"


def build_system_prompt(*, tools: Sequence[ToolCard], session_id: str) -> SystemPrompt:
    """Compose the platform agent's prompt. An agent with no tools is refused."""
    if not tools:
        raise ValueError("an agent must expose at least one tool")
    tool_lines = "\n".join(f"- {tool.name}: {tool.description}" for tool in tools)
    prefix = (
        f"# Identity\nYou are Crabriks, the platform agent {AGENT_NAME}.\n\n# Tools\n{tool_lines}"
    )
    suffix = f"# Runtime\nsession_id: {session_id}"
    return SystemPrompt(prefix=prefix, suffix=suffix)
