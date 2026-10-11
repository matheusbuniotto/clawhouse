"""The platform agent and its built-in tools with sensitive guardrails."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache

from pydantic_ai import Agent, DeferredToolRequests, RunContext

from crabriks.agent.prompt import CLOCK_DESCRIPTION


@dataclass(frozen=True, slots=True)
class TurnDeps:
    now: Callable[[], datetime]


def format_utc(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@lru_cache(maxsize=1)
def crabriks_agent() -> Agent[TurnDeps, str | DeferredToolRequests]:
    agent: Agent[TurnDeps, str | DeferredToolRequests] = Agent(
        name="crabriks",
        deps_type=TurnDeps,
        output_type=[str, DeferredToolRequests],
    )

    @agent.tool(description=CLOCK_DESCRIPTION)
    def clock(ctx: RunContext[TurnDeps]) -> str:
        return format_utc(ctx.deps.now())

    return agent
