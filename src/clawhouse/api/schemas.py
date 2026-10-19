"""Request and response schemas for the Clawhouse HTTP API."""

from typing import Annotated

from pydantic import BaseModel, StringConstraints

from clawhouse.store.shapes import RunState

__all__ = [
    "AnswerIn",
    "AnswerOut",
    "ApprovalActionOut",
    "ApprovalOut",
    "ApprovalsListOut",
    "AuthSnapshotOut",
    "ConnectionSnapshotOut",
    "CustomAgentIn",
    "CustomAgentOut",
    "EntryOut",
    "HatchProfileIn",
    "HatchStatusOut",
    "ModelOptionOut",
    "QuestionOut",
    "SandboxStatusOut",
    "ScheduleIn",
    "ScheduleOut",
    "SessionOut",
    "SessionTitleIn",
    "StatusOut",
    "TranscriptOut",
    "TurnIn",
]


class TurnIn(BaseModel):
    message: str
    model: str | None = None
    agent: str | None = None


class ModelOptionOut(BaseModel):
    id: str
    label: str
    default: bool


class SessionOut(BaseModel):
    id: str
    title: str
    created_at: str
    run_state: RunState = "idle"


class SessionTitleIn(BaseModel):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]


class HatchStatusOut(BaseModel):
    user_id: str
    hatched: bool
    assistant_name: str | None = None
    signature_emoji: str | None = None
    user_directives: str | None = None


class HatchProfileIn(BaseModel):
    assistant_name: str | None = None
    signature_emoji: str | None = None
    user_directives: str | None = None
    hatched: bool = True


class CustomAgentIn(BaseModel):
    name: str
    description: str
    system_prompt: str
    signature_emoji: str = "🤖"
    soul: str | None = None
    context: str | None = None


class CustomAgentOut(BaseModel):
    id: str
    owner_id: str
    name: str
    description: str
    system_prompt: str
    signature_emoji: str
    is_platform: bool = False
    model: str = "databricks"
    last_active_at: str | None = None
    last_activity: str = ""


class ScheduleIn(BaseModel):
    cron_expression: str
    prompt: str


class ScheduleOut(BaseModel):
    id: str
    session_id: str
    owner_id: str
    cron_expression: str
    prompt: str
    status: str
    next_run_at: str
    created_at: str
    last_run_at: str | None = None


class AuthSnapshotOut(BaseModel):
    user_id: str
    token_present: bool
    auth_type: str


class ConnectionSnapshotOut(BaseModel):
    workspace_host: str | None
    serving_endpoint: str | None
    store_type: str


class SandboxStatusOut(BaseModel):
    owner_id: str
    workspace_path: str
    backend: str = "databricks_python_exec"
    status: str = "ready"
    file_count: int = 0


class StatusOut(BaseModel):
    auth: AuthSnapshotOut
    connection: ConnectionSnapshotOut
    sessions: list[SessionOut]
    log_tail_url: str
    sandbox: SandboxStatusOut | None = None


class EntryOut(BaseModel):
    role: str
    content: str
    tool_name: str | None = None
    tool_call_id: str | None = None
    agent_id: str | None = None
    model: str | None = None


class TranscriptOut(BaseModel):
    entries: list[EntryOut]
    # `running` while a turn is still working: a reload polls until it settles.
    run_state: RunState = "idle"


class ApprovalOut(BaseModel):
    id: str
    session_id: str
    run_id: str
    tool_name: str
    tool_call_id: str
    arguments: str
    status: str
    created_at: str
    resolved_at: str | None = None
    resolved_by: str | None = None


class ApprovalsListOut(BaseModel):
    approvals: list[ApprovalOut]
    pending: list[ApprovalOut]
    history: list[ApprovalOut]


class QuestionOut(BaseModel):
    id: str
    session_id: str
    question: str
    options: list[str]
    default: str | None = None
    multi: bool = False
    status: str


class AnswerIn(BaseModel):
    selected: list[str]


class AnswerOut(BaseModel):
    status: str
    reply: str
    question: QuestionOut
    # A resumed run can stop on another question; the card for it.
    pending: list[QuestionOut] = []


class ApprovalActionOut(BaseModel):
    status: str
    reply: str
    approval: ApprovalOut
