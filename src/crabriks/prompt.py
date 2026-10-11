"""Backward-compatible facade for crabriks.agent.prompt."""

from crabriks.agent.prompt import (
    AGENT_NAME,
    BUILTIN_TOOLS,
    CLOCK,
    CLOCK_DESCRIPTION,
    CLOCK_NAME,
    SKILLS_READ,
    SKILLS_READ_DESCRIPTION,
    SKILLS_READ_NAME,
    SKILLS_SEARCH,
    SKILLS_SEARCH_DESCRIPTION,
    SKILLS_SEARCH_NAME,
    RuntimeMeta,
    SkillCard,
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
    "SKILLS_READ",
    "SKILLS_READ_DESCRIPTION",
    "SKILLS_READ_NAME",
    "SKILLS_SEARCH",
    "SKILLS_SEARCH_DESCRIPTION",
    "SKILLS_SEARCH_NAME",
    "RuntimeMeta",
    "SkillCard",
    "SystemPrompt",
    "ToolCard",
    "build_system_prompt",
]
