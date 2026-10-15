"""Backward-compatible facade for clawhouse.agent.prompt."""

from clawhouse.agent.prompt import (
    AGENT_NAME,
    BUILTIN_TOOLS,
    CLOCK,
    CLOCK_DESCRIPTION,
    CLOCK_NAME,
    RuntimeMeta,
    SystemPrompt,
    ToolCard,
    build_system_prompt,
)

__all__ = [
    "AGENT_NAME",
    "BUILTIN_TOOLS",
    "CLOCK",
    "CLOCK_DESCRIPTION",
    "CLOCK_NAME",
    "RuntimeMeta",
    "SystemPrompt",
    "ToolCard",
    "build_system_prompt",
]
