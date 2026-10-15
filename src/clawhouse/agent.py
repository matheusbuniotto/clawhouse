"""Backward-compatible facade for clawhouse.agent.core."""

from clawhouse.agent.core import (
    TurnDeps,
    clawhouse_agent,
    format_utc,
)

__all__ = [
    "TurnDeps",
    "clawhouse_agent",
    "format_utc",
]
