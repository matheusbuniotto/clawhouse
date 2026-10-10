"""The platform agent and its one built-in tool."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import lru_cache

from pydantic_ai import Agent, RunContext

from crabriks.prompt import (
    CLOCK_DESCRIPTION,
    SKILLS_READ_DESCRIPTION,
    SKILLS_SEARCH_DESCRIPTION,
)
from crabriks.skills import SkillsCatalog


@dataclass(frozen=True, slots=True)
class TurnDeps:
    now: Callable[[], datetime]
    skills: SkillsCatalog = field(default_factory=SkillsCatalog)


def format_utc(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@lru_cache(maxsize=1)
def crabriks_agent() -> Agent[TurnDeps, str]:
    agent: Agent[TurnDeps, str] = Agent(name="crabriks", deps_type=TurnDeps)

    @agent.tool(description=CLOCK_DESCRIPTION)
    def clock(ctx: RunContext[TurnDeps]) -> str:
        return format_utc(ctx.deps.now())

    @agent.tool(description=SKILLS_SEARCH_DESCRIPTION)
    def skills_search(ctx: RunContext[TurnDeps], query: str) -> str:
        matches = ctx.deps.skills.search(query)
        if not matches:
            return "No matching skills found."
        return "\n".join(f"- {s.name}: {s.description}" for s in matches)

    @agent.tool(description=SKILLS_READ_DESCRIPTION)
    def skills_read(ctx: RunContext[TurnDeps], name: str) -> str:
        return ctx.deps.skills.read(name)

    return agent
