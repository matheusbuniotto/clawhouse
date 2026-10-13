"""Backward-compatible facade for crabriks.agent.prompt."""

from crabriks.agent.prompt import (
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
