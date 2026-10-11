"""Backward-compatible facade for crabriks.agent.core."""

from crabriks.agent.core import (
    ApprovalRequired,
    TurnDeps,
    crabriks_agent,
    format_utc,
)

__all__ = [
    "ApprovalRequired",
    "TurnDeps",
    "crabriks_agent",
    "format_utc",
]
