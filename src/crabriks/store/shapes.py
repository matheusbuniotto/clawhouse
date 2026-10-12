"""Cross-module shapes for a chat turn. The store and the agent speak these, nothing else."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

Role = Literal["user", "assistant", "tool_call", "tool_result"]
TurnStatus = Literal["ok", "error", "pending_approval"]
ApprovalStatus = Literal["pending", "approved", "denied"]
RunState = Literal["running", "idle", "error"]


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
    run_state: RunState = "idle"


@dataclass(frozen=True, slots=True)
class ApprovalEntry:
    id: str
    session_id: str
    run_id: str
    tool_name: str
    tool_call_id: str
    arguments: str
    status: ApprovalStatus
    created_at: datetime
    resolved_at: datetime | None = None
    resolved_by: str | None = None


@dataclass(frozen=True, slots=True)
class TurnResult:
    session_id: str
    status: TurnStatus
    reply: str
    error: str | None
    transcript: tuple[TranscriptEntry, ...]
    approval_id: str | None = None


@dataclass(frozen=True, slots=True)
class UserProfile:
    user_id: str
    assistant_name: str | None = None
    signature_emoji: str | None = None
    user_directives: str | None = None
    hatched: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None
