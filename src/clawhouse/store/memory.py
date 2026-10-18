"""In-memory SessionStore implementation for tests and local development."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from clawhouse.store.mappers import _collect_session_activities, _memory_summary
from clawhouse.store.protocol import (
    ApprovalAlreadyResolved,
    ApprovalNotFound,
    ApprovalPending,
    RunInProgress,
    RunNotActive,
    SessionForbidden,
    SessionNotFound,
)
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


@dataclass
class _MemorySession:
    owner_id: str
    created_at: datetime
    entries: list[TranscriptEntry] = field(default_factory=list)
    entry_times: list[datetime] = field(default_factory=list)
    running: str | None = None
    last_status: TurnStatus | None = None
    title: str | None = None
    last_run_at: datetime | None = None
    messages: bytes | None = None


class MemorySessionStore:
    """In-process stand-in. `running` is the partial unique index."""

    def __init__(self, *, now: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self._sessions: dict[str, _MemorySession] = {}
        self._approvals: dict[str, ApprovalEntry] = {}
        self._profiles: dict[str, UserProfile] = {}
        self._custom_agents: dict[str, list[CustomAgent]] = {}
        self._schedules: dict[str, ScheduleEntry] = {}
        self._memories: list[MemoryEntry] = []
        self._now = now
        self._lock = asyncio.Lock()

    async def open_session(self, session_id: str, owner_id: str) -> None:
        async with self._lock:
            existing = self._sessions.get(session_id)
            if existing is None:
                self._sessions[session_id] = _MemorySession(
                    owner_id=owner_id, created_at=self._now()
                )
                return
            if existing.owner_id != owner_id:
                raise SessionForbidden(session_id)

    async def create_session(self, owner_id: str) -> SessionSummary:
        async with self._lock:
            session_id = str(uuid4())
            session = _MemorySession(owner_id=owner_id, created_at=self._now())
            self._sessions[session_id] = session
            return _memory_summary(session_id, session)

    async def list_sessions(self, owner_id: str) -> tuple[SessionSummary, ...]:
        async with self._lock:
            owned = [(sid, s) for sid, s in self._sessions.items() if s.owner_id == owner_id]
        owned.reverse()
        return tuple(_memory_summary(sid, s) for sid, s in owned)

    async def delete_session(self, session_id: str, owner_id: str) -> bool:
        async with self._lock:
            self._owned(session_id, owner_id)
            del self._sessions[session_id]
            self._approvals = {
                k: v for k, v in self._approvals.items() if v.session_id != session_id
            }
            self._memories = [r for r in self._memories if r.source_session_id != session_id]
            return True

    async def get_session(self, session_id: str, owner_id: str) -> SessionSummary:
        async with self._lock:
            return _memory_summary(session_id, self._owned(session_id, owner_id))

    async def rename_session(self, session_id: str, owner_id: str, title: str) -> SessionSummary:
        async with self._lock:
            session = self._owned(session_id, owner_id)
            session.title = title
            return _memory_summary(session_id, session)

    def _owned(self, session_id: str, owner_id: str) -> _MemorySession:
        session = self._require_session(session_id)
        if session.owner_id != owner_id:
            raise SessionForbidden(session_id)
        return session

    def _require_session(self, session_id: str) -> _MemorySession:
        session = self._sessions.get(session_id)
        if session is None:
            raise SessionNotFound(session_id)
        return session

    async def claim_run(self, session_id: str) -> str:
        async with self._lock:
            if any(
                a.session_id == session_id and a.status == "pending"
                for a in self._approvals.values()
            ):
                raise ApprovalPending(session_id)
            session = self._sessions[session_id]
            if session.running is not None:
                raise RunInProgress(session_id)
            run_id = str(uuid4())
            session.running = run_id
            return run_id

    async def append_entry(self, session_id: str, run_id: str, entry: TranscriptEntry) -> None:
        async with self._lock:
            session = self._sessions[session_id]
            if session.running != run_id:
                raise RunNotActive(run_id)
            session.entries.append(entry)
            session.entry_times.append(self._now())
            session.last_run_at = self._now()

    async def finish_run(self, session_id: str, run_id: str, status: TurnStatus) -> None:
        async with self._lock:
            session = self._sessions[session_id]
            if session.running == run_id and status in ("ok", "error", "pending_approval"):
                session.running = None
                session.last_status = status

    async def transcript(self, session_id: str, owner_id: str) -> tuple[TranscriptEntry, ...]:
        async with self._lock:
            return tuple(self._owned(session_id, owner_id).entries)

    async def clear_transcript(self, session_id: str, owner_id: str) -> None:
        async with self._lock:
            session = self._owned(session_id, owner_id)
            session.entries.clear()
            session.messages = None

    async def messages(self, session_id: str) -> bytes | None:
        async with self._lock:
            return self._require_session(session_id).messages

    async def save_messages(self, session_id: str, messages: bytes) -> None:
        async with self._lock:
            self._require_session(session_id).messages = messages

    async def create_approval(
        self,
        *,
        session_id: str,
        run_id: str,
        tool_name: str,
        tool_call_id: str,
        arguments: str,
    ) -> ApprovalEntry:
        async with self._lock:
            approval_id = str(uuid4())
            entry = ApprovalEntry(
                id=approval_id,
                session_id=session_id,
                run_id=run_id,
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                arguments=arguments,
                status="pending",
                created_at=datetime.now(UTC),
            )
            self._approvals[approval_id] = entry
            return entry

    async def get_approval(self, approval_id: str) -> ApprovalEntry:
        async with self._lock:
            entry = self._approvals.get(approval_id)
            if entry is None:
                raise ApprovalNotFound(approval_id)
            return entry

    async def list_approvals(
        self,
        owner_id: str,
        status: ApprovalStatus | None = None,
    ) -> tuple[ApprovalEntry, ...]:
        async with self._lock:
            owned = {s_id for s_id, s in self._sessions.items() if s.owner_id == owner_id}
            matching = [
                a
                for a in self._approvals.values()
                if a.session_id in owned and (status is None or a.status == status)
            ]
        matching.sort(key=lambda a: a.created_at, reverse=True)
        return tuple(matching)

    async def resolve_approval(
        self,
        approval_id: str,
        status: Literal["approved", "denied"],
        resolver_id: str,
        resolved_at: datetime | None = None,
    ) -> ApprovalEntry:
        async with self._lock:
            entry = self._approvals.get(approval_id)
            if entry is None:
                raise ApprovalNotFound(approval_id)
            if entry.status != "pending":
                raise ApprovalAlreadyResolved(approval_id)
            resolved = replace(
                entry,
                status=status,
                resolved_by=resolver_id,
                resolved_at=resolved_at or datetime.now(UTC),
            )
            self._approvals[approval_id] = resolved
            return resolved

    async def has_pending_approval(self, session_id: str) -> bool:
        async with self._lock:
            return any(
                a.session_id == session_id and a.status == "pending"
                for a in self._approvals.values()
            )

    async def get_user_profile(self, user_id: str) -> UserProfile | None:
        async with self._lock:
            return self._profiles.get(user_id)

    async def save_user_profile(self, profile: UserProfile) -> UserProfile:
        async with self._lock:
            now = datetime.now(UTC)
            saved = replace(profile, created_at=profile.created_at or now, updated_at=now)
            self._profiles[profile.user_id] = saved
            return saved

    async def list_custom_agents(self, owner_id: str) -> tuple[CustomAgent, ...]:
        async with self._lock:
            return tuple(self._custom_agents.get(owner_id, []))

    async def create_custom_agent(self, agent: CustomAgent) -> CustomAgent:
        async with self._lock:
            agents = self._custom_agents.setdefault(agent.owner_id, [])
            agents.append(agent)
            return agent

    async def delete_custom_agent(self, agent_id: str, owner_id: str) -> bool:
        async with self._lock:
            agents = self._custom_agents.get(owner_id, [])
            initial_len = len(agents)
            self._custom_agents[owner_id] = [a for a in agents if a.id != agent_id]
            return len(self._custom_agents[owner_id]) < initial_len

    async def agent_activities(self, owner_id: str) -> dict[str, tuple[datetime, str]]:
        async with self._lock:
            owned = [s for s in self._sessions.values() if s.owner_id == owner_id]
        return _collect_session_activities(owned)

    async def create_schedule(self, schedule: ScheduleEntry) -> ScheduleEntry:
        async with self._lock:
            self._schedules[schedule.id] = schedule
            return schedule

    async def list_schedules(
        self, owner_id: str, session_id: str | None = None
    ) -> tuple[ScheduleEntry, ...]:
        async with self._lock:
            results = [
                s
                for s in self._schedules.values()
                if s.owner_id == owner_id and (session_id is None or s.session_id == session_id)
            ]
            results.sort(key=lambda s: s.created_at, reverse=True)
            return tuple(results)

    async def cancel_schedule(self, schedule_id: str, owner_id: str) -> bool:
        async with self._lock:
            schedule = self._schedules.get(schedule_id)
            if schedule is None or schedule.owner_id != owner_id:
                return False
            self._schedules[schedule_id] = replace(schedule, status="cancelled")
            return True

    async def claim_due_schedules(self, now: datetime) -> tuple[ScheduleEntry, ...]:
        async with self._lock:
            return tuple(
                s for s in self._schedules.values() if s.status == "active" and s.next_run_at <= now
            )

    async def update_schedule_run(
        self,
        schedule_id: str,
        last_run_at: datetime,
        next_run_at: datetime,
        *,
        last_status: str | None = None,
        last_error: str | None = None,
    ) -> ScheduleEntry | None:
        async with self._lock:
            schedule = self._schedules.get(schedule_id)
            if schedule is None:
                return None
            updated = replace(
                schedule,
                last_run_at=last_run_at,
                next_run_at=next_run_at,
                last_status=last_status,
                last_error=last_error,
            )
            self._schedules[schedule_id] = updated
            return updated

    async def save_memory(
        self,
        owner_id: str,
        text: str,
        source_session_id: str | None = None,
        table_fqn: str | None = None,
    ) -> MemoryEntry:
        if source_session_id is not None:
            await self.get_session(source_session_id, owner_id)
        entry = MemoryEntry(
            id=str(uuid4()),
            owner_id=owner_id,
            text=text,
            created_at=self._now(),
            source_session_id=source_session_id,
            table_fqn=table_fqn,
        )
        async with self._lock:
            self._memories.append(entry)
        return entry

    async def list_memories(self, owner_id: str, limit: int = 20) -> tuple[MemoryEntry, ...]:
        owned = [row for row in self._memories if row.owner_id == owner_id]
        owned.sort(key=lambda row: row.created_at, reverse=True)
        return tuple(owned[:limit])

    async def delete_memory(self, owner_id: str, memory_id: str) -> bool:
        async with self._lock:
            for index, row in enumerate(self._memories):
                if row.id == memory_id and row.owner_id == owner_id:
                    self._memories.pop(index)
                    return True
        return False

    async def search_transcripts(
        self, owner_id: str, query: str, limit: int
    ) -> tuple[SearchHit, ...]:
        needle = query.casefold()
        hits: list[SearchHit] = []
        for session_id, session in self._sessions.items():
            if session.owner_id != owner_id:
                continue
            for entry, created_at in zip(session.entries, session.entry_times, strict=False):
                if needle in entry.content.casefold():
                    hits.append(
                        SearchHit(
                            session_id=session_id,
                            role=entry.role,
                            excerpt=entry.content[:240],
                            created_at=created_at,
                        )
                    )
        hits.sort(key=lambda hit: hit.created_at, reverse=True)
        return tuple(hits[:limit])

    async def rank_memories(
        self, owner_id: str, query: str, limit: int = 5
    ) -> tuple[MemoryEntry, ...]:
        terms = [term for term in query.casefold().split() if term]
        ranked: list[tuple[int, MemoryEntry]] = []
        for row in self._memories:
            if row.owner_id == owner_id:
                score = sum(row.text.casefold().count(term) for term in terms)
                if score:
                    ranked.append((score, row))
        ranked.sort(key=lambda item: (item[0], item[1].created_at), reverse=True)
        return tuple(row for _score, row in ranked[:limit])

    async def close(self) -> None:
        return None
