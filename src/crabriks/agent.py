"""The platform agent and its one built-in tool."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache

from pydantic_ai import Agent, RunContext

from crabriks.prompt import CLOCK_DESCRIPTION


@dataclass(frozen=True, slots=True)
class TurnDeps:
    now: Callable[[], datetime]


def format_utc(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@lru_cache(maxsize=1)
def crabriks_agent() -> Agent[TurnDeps, str]:
    agent: Agent[TurnDeps, str] = Agent(name="crabriks", deps_type=TurnDeps)

    @agent.tool(description=CLOCK_DESCRIPTION)
    def clock(ctx: RunContext[TurnDeps]) -> str:
        return format_utc(ctx.deps.now())

    return agent
