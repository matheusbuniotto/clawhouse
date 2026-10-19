"""Cross-module shapes for a chat turn. The store and the agent speak these, nothing else."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

Role = Literal["user", "assistant", "tool_call", "tool_result", "notice"]
TurnStatus = Literal["ok", "error", "pending_approval"]
ApprovalStatus = Literal["pending", "approved", "denied"]
RunState = Literal["running", "idle", "error"]


@dataclass(frozen=True, slots=True)
class TranscriptEntry:
    role: Role
    content: str
    tool_name: str | None = None
    tool_call_id: str | None = None
    # Who produced the entry. None on rows written before agents were tracked: the default agent.
    agent_id: str | None = None
    # Display only (the agent header after reload); not part of an entry's identity.
    model: str | None = field(default=None, compare=False)


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


@dataclass(frozen=True, slots=True)
class CustomAgent:
    id: str
    owner_id: str
    name: str
    description: str
    system_prompt: str
    signature_emoji: str = "🤖"
    created_at: datetime | None = None


ScheduleStatus = Literal["active", "paused", "cancelled"]


@dataclass(frozen=True, slots=True)
class MemoryEntry:
    id: str
    owner_id: str
    text: str
    created_at: datetime
    source_session_id: str | None = None
    table_fqn: str | None = None


@dataclass(frozen=True, slots=True)
class SearchHit:
    session_id: str
    role: str
    excerpt: str
    created_at: datetime


FiredKind = Literal["sql", "sql_agent", "agent"]


@dataclass(frozen=True, slots=True)
class FiredJob:
    id: str
    session_id: str
    owner_id: str
    kind: FiredKind
    name: str
    slack_webhook_url: str
    instructions: str
    agent_name: str | None = None
    databricks_job_id: int | None = None
    schedule_id: str | None = None


@dataclass(frozen=True, slots=True)
class FiredDelivery:
    id: str
    fired_job_id: str
    databricks_job_id: int | None = None
    run_id: int | None = None
    event_type: str | None = None
    schedule_id: str | None = None
    next_run_at: datetime | None = None
    sheet_status: str | None = None


@dataclass(frozen=True, slots=True)
class ScheduleEntry:
    id: str
    session_id: str
    owner_id: str
    cron_expression: str
    prompt: str
    status: ScheduleStatus
    next_run_at: datetime
    created_at: datetime
    last_run_at: datetime | None = None
    last_status: str | None = None
    last_error: str | None = None
