"""Cross-module shapes for a chat turn. The store and the agent speak these, nothing else."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

Role = Literal["user", "assistant", "tool_call", "tool_result"]
TurnStatus = Literal["ok", "error"]


@dataclass(frozen=True, slots=True)
class TranscriptEntry:
    role: Role
    content: str
    tool_name: str | None = None
    tool_call_id: str | None = None


@dataclass(frozen=True, slots=True)
class SessionSummary:
    """A session as shown in a list: its first user message is the title."""

    id: str
    title: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class TurnResult:
    session_id: str
    status: TurnStatus
    reply: str
    error: str | None
    transcript: tuple[TranscriptEntry, ...]
