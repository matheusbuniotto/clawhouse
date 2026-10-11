"""Backward-compatible facade for crabriks.agent.core."""

from crabriks.agent.core import (
    TurnDeps,
    crabriks_agent,
    format_utc,
)

__all__ = [
    "TurnDeps",
    "crabriks_agent",
    "format_utc",
]
