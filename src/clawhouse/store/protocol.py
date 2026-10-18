"""Store protocols and store domain exceptions."""

from datetime import datetime
from typing import Any, Literal, Protocol

from clawhouse.store.shapes import (
    ApprovalEntry,
    ApprovalStatus,
    CustomAgent,
    MemoryEntry,
    ScheduleEntry,
    SearchHit,
    SessionSummary,
    TranscriptEntry,
    TurnStatus,
    UserProfile,
)


class SessionStore(Protocol):
    async def open_session(self, session_id: str, owner_id: str) -> None: ...

    async def create_session(self, owner_id: str) -> SessionSummary: ...

    async def list_sessions(self, owner_id: str) -> tuple[SessionSummary, ...]: ...

    async def delete_session(self, session_id: str, owner_id: str) -> bool: ...

    async def get_session(self, session_id: str, owner_id: str) -> SessionSummary: ...

    async def rename_session(
        self, session_id: str, owner_id: str, title: str
    ) -> SessionSummary: ...

    async def clear_transcript(self, session_id: str, owner_id: str) -> None: ...

    async def claim_run(self, session_id: str) -> str: ...

    async def append_entry(self, session_id: str, run_id: str, entry: TranscriptEntry) -> None: ...

    async def finish_run(self, session_id: str, run_id: str, status: TurnStatus) -> None: ...

    async def transcript(self, session_id: str, owner_id: str) -> tuple[TranscriptEntry, ...]: ...

    async def messages(self, session_id: str) -> bytes | None: ...

    async def save_messages(self, session_id: str, messages: bytes) -> None: ...

    async def create_approval(
        self,
        *,
        session_id: str,
        run_id: str,
        tool_name: str,
        tool_call_id: str,
        arguments: str,
    ) -> ApprovalEntry: ...

    async def get_approval(self, approval_id: str) -> ApprovalEntry: ...

    async def list_approvals(
        self,
        owner_id: str,
        status: ApprovalStatus | None = None,
    ) -> tuple[ApprovalEntry, ...]: ...

    async def resolve_approval(
        self,
        approval_id: str,
        status: Literal["approved", "denied"],
        resolver_id: str,
        resolved_at: datetime | None = None,
    ) -> ApprovalEntry: ...

    async def has_pending_approval(self, session_id: str) -> bool: ...

    async def get_user_profile(self, user_id: str) -> UserProfile | None: ...

    async def save_user_profile(self, profile: UserProfile) -> UserProfile: ...

    async def list_custom_agents(self, owner_id: str) -> tuple[CustomAgent, ...]: ...

    async def create_custom_agent(self, agent: CustomAgent) -> CustomAgent: ...

    async def delete_custom_agent(self, agent_id: str, owner_id: str) -> bool: ...

    async def agent_activities(self, owner_id: str) -> dict[str, tuple[datetime, str]]: ...

    async def create_schedule(self, schedule: ScheduleEntry) -> ScheduleEntry: ...

    async def list_schedules(
        self, owner_id: str, session_id: str | None = None
    ) -> tuple[ScheduleEntry, ...]: ...

    async def cancel_schedule(self, schedule_id: str, owner_id: str) -> bool: ...

    async def claim_due_schedules(self, now: datetime) -> tuple[ScheduleEntry, ...]: ...

    async def update_schedule_run(
        self,
        schedule_id: str,
        last_run_at: datetime,
        next_run_at: datetime,
        *,
        last_status: str | None = None,
        last_error: str | None = None,
    ) -> ScheduleEntry | None: ...

    async def save_memory(
        self,
        owner_id: str,
        text: str,
        source_session_id: str | None = None,
        table_fqn: str | None = None,
    ) -> MemoryEntry: ...

    async def list_memories(self, owner_id: str, limit: int = 20) -> tuple[MemoryEntry, ...]: ...

    async def delete_memory(self, owner_id: str, memory_id: str) -> bool: ...

    async def search_transcripts(
        self, owner_id: str, query: str, limit: int
    ) -> tuple[SearchHit, ...]: ...

    async def rank_memories(
        self, owner_id: str, query: str, limit: int = 5
    ) -> tuple[MemoryEntry, ...]: ...

    async def close(self) -> None: ...


class RunNotActive(Exception):
    """The run is not the session's current running claim."""


class ApprovalPending(Exception):
    """A tool call is pending approval for this session."""


class ApprovalNotFound(Exception):
    """No approval with this id."""


class ApprovalAlreadyResolved(Exception):
    """This approval has already been resolved."""


class ApprovalForbidden(Exception):
    """The caller does not own this approval."""


class RunInProgress(Exception):
    """This session already has a running turn."""


class SessionForbidden(Exception):
    """The caller does not own this session."""


class SessionNotFound(Exception):
    """No session with this id."""


class MissingDatabaseCredential(Exception):
    """A Lakebase host is set, but there is no password and no endpoint to mint one."""


class _Querier(Protocol):
    async def fetchval(self, _query: str, *_args: object) -> Any: ...

    async def execute(self, _query: str, *_args: object) -> str: ...
