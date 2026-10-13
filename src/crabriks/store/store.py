"""Session, transcript, and run-lock storage.

The production store is Lakebase. A partial unique index on running runs is the
lock: two claims for one session cannot both commit. A running row older than
10 minutes is finished as error, so a dead process does not hold the session.
Apps authenticate with an OAuth token minted from `LAKEBASE_ENDPOINT`; a
postgres URI or `PGPASSWORD` is the local path. `MemorySessionStore` is the
same contract for tests and for a process with no database.
"""

import asyncio
import logging
import os
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any, Literal, Protocol
from uuid import UUID, uuid4

import asyncpg
from databricks.sdk import WorkspaceClient

from crabriks.store.shapes import (
    ApprovalEntry,
    ApprovalStatus,
    CustomAgent,
    RunState,
    ScheduleEntry,
    SessionSummary,
    TranscriptEntry,
    TurnStatus,
    UserProfile,
)

logger = logging.getLogger(__name__)
_CONNECT_ATTEMPTS = 5
_CONNECT_TIMEOUT = 10

# The app service principal owns this schema. It can create objects, and it
# cannot create tables in `public` on Postgres 15+.
SCHEMA = """
CREATE SCHEMA IF NOT EXISTS crabriks;

CREATE TABLE IF NOT EXISTS crabriks.sessions (
    id uuid PRIMARY KEY,
    owner_id text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS crabriks.runs (
    id uuid PRIMARY KEY,
    session_id uuid NOT NULL REFERENCES crabriks.sessions (id),
    status text NOT NULL,
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    CONSTRAINT runs_status_known CHECK (status IN ('running', 'ok', 'error', 'pending_approval'))
);

ALTER TABLE crabriks.runs DROP CONSTRAINT IF EXISTS runs_status_known;
ALTER TABLE crabriks.runs ADD CONSTRAINT runs_status_known
    CHECK (status IN ('running', 'ok', 'error', 'pending_approval'));

CREATE UNIQUE INDEX IF NOT EXISTS runs_one_running_per_session
    ON crabriks.runs (session_id)
    WHERE status = 'running';

CREATE TABLE IF NOT EXISTS crabriks.transcript_entries (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id uuid NOT NULL REFERENCES crabriks.sessions (id),
    run_id uuid NOT NULL REFERENCES crabriks.runs (id),
    position integer NOT NULL,
    role text NOT NULL,
    content text NOT NULL,
    tool_name text,
    tool_call_id text,
    CONSTRAINT transcript_role_known CHECK (
        role IN ('user', 'assistant', 'tool_call', 'tool_result')
    ),
    CONSTRAINT transcript_position_unique UNIQUE (session_id, position)
);

CREATE TABLE IF NOT EXISTS crabriks.approvals (
    id uuid PRIMARY KEY,
    session_id uuid NOT NULL REFERENCES crabriks.sessions (id),
    run_id uuid NOT NULL REFERENCES crabriks.runs (id),
    tool_name text NOT NULL,
    tool_call_id text NOT NULL,
    arguments text NOT NULL,
    status text NOT NULL DEFAULT 'pending',
    created_at timestamptz NOT NULL DEFAULT now(),
    resolved_at timestamptz,
    resolved_by text,
    CONSTRAINT approvals_status_known CHECK (status IN ('pending', 'approved', 'denied'))
);

CREATE INDEX IF NOT EXISTS approvals_session_status
    ON crabriks.approvals (session_id, status);

CREATE TABLE IF NOT EXISTS crabriks.user_profiles (
    user_id text PRIMARY KEY,
    assistant_name text,
    signature_emoji text,
    user_directives text,
    hatched boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS crabriks.custom_agents (
    id uuid PRIMARY KEY,
    owner_id text NOT NULL,
    name text NOT NULL,
    description text NOT NULL,
    system_prompt text NOT NULL,
    signature_emoji text NOT NULL DEFAULT '🤖',
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS custom_agents_owner_idx
    ON crabriks.custom_agents (owner_id);

CREATE TABLE IF NOT EXISTS crabriks.schedules (
    id uuid PRIMARY KEY,
    session_id uuid NOT NULL REFERENCES crabriks.sessions (id),
    owner_id text NOT NULL,
    cron_expression text NOT NULL,
    prompt text NOT NULL,
    status text NOT NULL DEFAULT 'active',
    last_run_at timestamptz,
    next_run_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT schedules_status_known CHECK (status IN ('active', 'paused', 'cancelled'))
);

CREATE INDEX IF NOT EXISTS schedules_owner_idx
    ON crabriks.schedules (owner_id);

CREATE INDEX IF NOT EXISTS schedules_due_idx
    ON crabriks.schedules (status, next_run_at)
    WHERE status = 'active';
"""


_RUNNING_INDEX = "runs_one_running_per_session"
_STALE_RUN_MINUTES = 10


class SessionStore(Protocol):
    async def open_session(self, session_id: str, owner_id: str) -> None: ...

    async def create_session(self, owner_id: str) -> SessionSummary: ...

    async def list_sessions(self, owner_id: str) -> tuple[SessionSummary, ...]: ...

    async def delete_session(self, session_id: str, owner_id: str) -> bool: ...

    async def claim_run(self, session_id: str) -> str: ...

    async def append_entry(self, session_id: str, run_id: str, entry: TranscriptEntry) -> None: ...

    async def finish_run(self, session_id: str, run_id: str, status: TurnStatus) -> None: ...

    async def transcript(self, session_id: str, owner_id: str) -> tuple[TranscriptEntry, ...]: ...

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

    async def create_schedule(self, schedule: ScheduleEntry) -> ScheduleEntry: ...

    async def list_schedules(
        self, owner_id: str, session_id: str | None = None
    ) -> tuple[ScheduleEntry, ...]: ...

    async def cancel_schedule(self, schedule_id: str, owner_id: str) -> bool: ...

    async def claim_due_schedules(self, now: datetime) -> tuple[ScheduleEntry, ...]: ...

    async def update_schedule_run(
        self, schedule_id: str, last_run_at: datetime, next_run_at: datetime
    ) -> ScheduleEntry | None: ...

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


@dataclass
class _MemorySession:
    owner_id: str
    created_at: datetime
    entries: list[TranscriptEntry] = field(default_factory=list)
    running: str | None = None
    last_status: TurnStatus | None = None


class MemorySessionStore:
    """In-process stand-in. `running` is the partial unique index."""

    def __init__(self) -> None:
        self._sessions: dict[str, _MemorySession] = {}
        self._approvals: dict[str, ApprovalEntry] = {}
        self._profiles: dict[str, UserProfile] = {}
        self._custom_agents: dict[str, list[CustomAgent]] = {}
        self._schedules: dict[str, ScheduleEntry] = {}
        self._lock = asyncio.Lock()

    async def open_session(self, session_id: str, owner_id: str) -> None:
        async with self._lock:
            existing = self._sessions.get(session_id)
            if existing is None:
                self._sessions[session_id] = _MemorySession(
                    owner_id=owner_id, created_at=datetime.now(UTC)
                )
                return
            if existing.owner_id != owner_id:
                raise SessionForbidden(session_id)

    async def create_session(self, owner_id: str) -> SessionSummary:
        async with self._lock:
            session_id = str(uuid4())
            session = _MemorySession(owner_id=owner_id, created_at=datetime.now(UTC))
            self._sessions[session_id] = session
            return _memory_summary(session_id, session)

    async def list_sessions(self, owner_id: str) -> tuple[SessionSummary, ...]:
        async with self._lock:
            owned = [
                (session_id, session)
                for session_id, session in self._sessions.items()
                if session.owner_id == owner_id
            ]
        owned.reverse()
        return tuple(_memory_summary(session_id, session) for session_id, session in owned)

    async def delete_session(self, session_id: str, owner_id: str) -> bool:
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise SessionNotFound(session_id)
            if session.owner_id != owner_id:
                raise SessionForbidden(session_id)
            del self._sessions[session_id]
            self._approvals = {
                k: v for k, v in self._approvals.items() if v.session_id != session_id
            }
            return True

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

    async def finish_run(self, session_id: str, run_id: str, status: TurnStatus) -> None:
        async with self._lock:
            session = self._sessions[session_id]
            if session.running == run_id and status in ("ok", "error", "pending_approval"):
                session.running = None
                session.last_status = status

    async def transcript(self, session_id: str, owner_id: str) -> tuple[TranscriptEntry, ...]:
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise SessionNotFound(session_id)
            if session.owner_id != owner_id:
                raise SessionForbidden(session_id)
            return tuple(session.entries)

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
            saved = replace(
                profile,
                created_at=profile.created_at or now,
                updated_at=now,
            )
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
            due = [
                s for s in self._schedules.values() if s.status == "active" and s.next_run_at <= now
            ]
            return tuple(due)

    async def update_schedule_run(
        self, schedule_id: str, last_run_at: datetime, next_run_at: datetime
    ) -> ScheduleEntry | None:
        async with self._lock:
            schedule = self._schedules.get(schedule_id)
            if schedule is None:
                return None
            updated = replace(schedule, last_run_at=last_run_at, next_run_at=next_run_at)
            self._schedules[schedule_id] = updated
            return updated

    async def close(self) -> None:
        return None


class LakebaseSessionStore:
    """Lakebase (Postgres) sessions, transcripts, and the running-run lock."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def migrate(self) -> None:
        await self._pool.execute(SCHEMA)
        await self._pool.execute(
            """
            DO $$
            BEGIN
                ALTER TABLE crabriks.runs DROP CONSTRAINT IF EXISTS runs_status_known;
                ALTER TABLE crabriks.runs ADD CONSTRAINT runs_status_known
                    CHECK (status IN ('running', 'ok', 'error', 'pending_approval'));
            EXCEPTION
                WHEN undefined_table THEN NULL;
            END $$;
            """
        )

    async def open_session(self, session_id: str, owner_id: str) -> None:
        session = _uuid(session_id)
        async with self._pool.acquire() as conn:
            await _insert_or_check_owner(cast_querier(conn), session, owner_id)

    async def create_session(self, owner_id: str) -> SessionSummary:
        row = await self._pool.fetchrow(
            """
            INSERT INTO crabriks.sessions (id, owner_id)
            VALUES ($1, $2)
            RETURNING id, created_at
            """,
            uuid4(),
            owner_id,
        )
        return SessionSummary(id=str(row["id"]), title="", created_at=row["created_at"])

    async def list_sessions(self, owner_id: str) -> tuple[SessionSummary, ...]:
        rows = await self._pool.fetch(
            """
            SELECT s.id, s.created_at,
                (
                    SELECT t.content FROM crabriks.transcript_entries AS t
                    WHERE t.session_id = s.id AND t.role = 'user'
                    ORDER BY t.position
                    LIMIT 1
                ) AS title,
                (
                    SELECT r.status FROM crabriks.runs AS r
                    WHERE r.session_id = s.id
                    ORDER BY (r.status = 'running') DESC, r.started_at DESC
                    LIMIT 1
                ) AS latest_run_status
            FROM crabriks.sessions AS s
            WHERE s.owner_id = $1
            ORDER BY s.created_at DESC
            """,
            owner_id,
        )
        return tuple(
            SessionSummary(
                id=str(row["id"]),
                title=row["title"] or "",
                created_at=row["created_at"],
                run_state=run_state_for(
                    is_running=False,
                    status=row["latest_run_status"],
                ),
            )
            for row in rows
        )

    async def claim_run(self, session_id: str) -> str:
        if await self.has_pending_approval(session_id):
            raise ApprovalPending(session_id)
        first = await self._insert_or_reclaim(session_id)
        if first is not None:
            return first
        try:
            return await self._insert_running(session_id)
        except asyncpg.UniqueViolationError as exc:
            if _constraint_name(exc) == _RUNNING_INDEX:
                raise RunInProgress(session_id) from exc
            raise

    async def _insert_or_reclaim(self, session_id: str) -> str | None:
        try:
            return await self._insert_running(session_id)
        except asyncpg.UniqueViolationError as exc:
            if _constraint_name(exc) != _RUNNING_INDEX:
                raise
            if not await self._reclaim_stale(session_id):
                raise RunInProgress(session_id) from exc
            return None

    async def _insert_running(self, session_id: str) -> str:
        run_id = uuid4()
        await self._pool.execute(
            "INSERT INTO crabriks.runs (id, session_id, status) VALUES ($1, $2, 'running')",
            run_id,
            _uuid(session_id),
        )
        return str(run_id)

    async def _reclaim_stale(self, session_id: str) -> bool:
        reclaimed = await self._pool.fetchval(
            """
            UPDATE crabriks.runs
            SET status = 'error', finished_at = now()
            WHERE id = (
                SELECT id FROM crabriks.runs
                WHERE session_id = $1
                  AND status = 'running'
                  AND started_at < now() - make_interval(mins => $2)
                LIMIT 1
            )
            RETURNING id
            """,
            _uuid(session_id),
            _STALE_RUN_MINUTES,
        )
        return reclaimed is not None

    async def append_entry(self, session_id: str, run_id: str, entry: TranscriptEntry) -> None:
        session = _uuid(session_id)
        run = _uuid(run_id)
        async with self._pool.acquire() as conn, conn.transaction():
            active = await conn.fetchval(
                """
                SELECT 1 FROM crabriks.runs
                WHERE id = $1 AND session_id = $2 AND status = 'running'
                """,
                run,
                session,
            )
            if active is None:
                raise RunNotActive(run_id)
            await conn.execute("SELECT id FROM crabriks.sessions WHERE id = $1 FOR UPDATE", session)
            position = await conn.fetchval(
                """
                SELECT COALESCE(MAX(position), 0) + 1
                FROM crabriks.transcript_entries
                WHERE session_id = $1
                """,
                session,
            )
            await conn.execute(
                """
                INSERT INTO crabriks.transcript_entries (
                    session_id, run_id, position, role, content, tool_name, tool_call_id
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                session,
                run,
                position,
                entry.role,
                entry.content,
                entry.tool_name,
                entry.tool_call_id,
            )

    async def finish_run(self, session_id: str, run_id: str, status: TurnStatus) -> None:
        await self._pool.execute(
            """
            UPDATE crabriks.runs
            SET status = $3, finished_at = now()
            WHERE id = $1 AND session_id = $2 AND status = 'running'
            """,
            _uuid(run_id),
            _uuid(session_id),
            status,
        )

    async def transcript(self, session_id: str, owner_id: str) -> tuple[TranscriptEntry, ...]:
        rows = await self._pool.fetch(
            """
            SELECT t.role, t.content, t.tool_name, t.tool_call_id
            FROM crabriks.transcript_entries AS t
            JOIN crabriks.sessions AS s ON s.id = t.session_id
            WHERE t.session_id = $1 AND s.owner_id = $2
            ORDER BY t.position
            """,
            _uuid(session_id),
            owner_id,
        )
        if rows:
            return tuple(_entry_from_row(row) for row in rows)
        await self._require_owner(session_id, owner_id)
        return ()

    async def delete_session(self, session_id: str, owner_id: str) -> bool:
        await self._require_owner(session_id, owner_id)
        session = _uuid(session_id)
        async with self._pool.acquire() as conn, conn.transaction():
            await conn.execute("DELETE FROM crabriks.approvals WHERE session_id = $1", session)
            await conn.execute(
                "DELETE FROM crabriks.transcript_entries WHERE session_id = $1", session
            )
            await conn.execute("DELETE FROM crabriks.runs WHERE session_id = $1", session)
            deleted = await conn.execute("DELETE FROM crabriks.sessions WHERE id = $1", session)
            return "DELETE 1" in deleted

    async def close(self) -> None:
        await self._pool.close()

    async def _require_owner(self, session_id: str, owner_id: str) -> None:
        owner = await self._pool.fetchval(
            "SELECT owner_id FROM crabriks.sessions WHERE id = $1",
            _uuid(session_id),
        )
        if owner is None:
            raise SessionNotFound(session_id)
        if owner != owner_id:
            raise SessionForbidden(session_id)

    async def create_approval(
        self,
        *,
        session_id: str,
        run_id: str,
        tool_name: str,
        tool_call_id: str,
        arguments: str,
    ) -> ApprovalEntry:
        row = await self._pool.fetchrow(
            """
            INSERT INTO crabriks.approvals (
                id, session_id, run_id, tool_name, tool_call_id, arguments, status
            )
            VALUES ($1, $2, $3, $4, $5, $6, 'pending')
            RETURNING
                id, session_id, run_id, tool_name, tool_call_id,
                arguments, status, created_at, resolved_at, resolved_by
            """,
            uuid4(),
            _uuid(session_id),
            _uuid(run_id),
            tool_name,
            tool_call_id,
            arguments,
        )
        if row is None:
            raise RuntimeError("approval row was not returned")
        return _approval_from_row(row)

    async def get_approval(self, approval_id: str) -> ApprovalEntry:
        row = await self._pool.fetchrow(
            """
            SELECT
                id, session_id, run_id, tool_name, tool_call_id,
                arguments, status, created_at, resolved_at, resolved_by
            FROM crabriks.approvals
            WHERE id = $1
            """,
            _uuid(approval_id),
        )
        if row is None:
            raise ApprovalNotFound(approval_id)
        return _approval_from_row(row)

    async def list_approvals(
        self,
        owner_id: str,
        status: ApprovalStatus | None = None,
    ) -> tuple[ApprovalEntry, ...]:
        query = """
            SELECT
                a.id, a.session_id, a.run_id, a.tool_name, a.tool_call_id,
                a.arguments, a.status, a.created_at, a.resolved_at, a.resolved_by
            FROM crabriks.approvals AS a
            JOIN crabriks.sessions AS s ON s.id = a.session_id
            WHERE s.owner_id = $1
        """
        if status is not None:
            query += " AND a.status = $2 ORDER BY a.created_at DESC"
            rows = await self._pool.fetch(query, owner_id, status)
        else:
            query += " ORDER BY a.created_at DESC"
            rows = await self._pool.fetch(query, owner_id)
        return tuple(_approval_from_row(row) for row in rows)

    async def resolve_approval(
        self,
        approval_id: str,
        status: Literal["approved", "denied"],
        resolver_id: str,
        resolved_at: datetime | None = None,
    ) -> ApprovalEntry:
        app_id = _uuid(approval_id)
        when = resolved_at or datetime.now(UTC)
        async with self._pool.acquire() as conn, conn.transaction():
            current_status = await conn.fetchval(
                "SELECT status FROM crabriks.approvals WHERE id = $1 FOR UPDATE", app_id
            )
            if current_status is None:
                raise ApprovalNotFound(approval_id)
            if current_status != "pending":
                raise ApprovalAlreadyResolved(approval_id)
            row = await conn.fetchrow(
                """
                UPDATE crabriks.approvals
                SET status = $2, resolved_at = $3, resolved_by = $4
                WHERE id = $1
                RETURNING
                    id, session_id, run_id, tool_name, tool_call_id,
                    arguments, status, created_at, resolved_at, resolved_by
                """,
                app_id,
                status,
                when,
                resolver_id,
            )
            if row is None:
                raise RuntimeError("updated approval row was not returned")
            return _approval_from_row(row)

    async def has_pending_approval(self, session_id: str) -> bool:
        val = await self._pool.fetchval(
            """
            SELECT 1 FROM crabriks.approvals
            WHERE session_id = $1 AND status = 'pending'
            LIMIT 1
            """,
            _uuid(session_id),
        )
        return val is not None

    async def get_user_profile(self, user_id: str) -> UserProfile | None:
        row = await self._pool.fetchrow(
            """
            SELECT
                user_id, assistant_name, signature_emoji, user_directives,
                hatched, created_at, updated_at
            FROM crabriks.user_profiles
            WHERE user_id = $1
            """,
            user_id,
        )
        if row is None:
            return None
        return _profile_from_row(row)

    async def save_user_profile(self, profile: UserProfile) -> UserProfile:
        now = datetime.now(UTC)
        row = await self._pool.fetchrow(
            """
            INSERT INTO crabriks.user_profiles (
                user_id, assistant_name, signature_emoji,
                user_directives, hatched, created_at, updated_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $6)
            ON CONFLICT (user_id) DO UPDATE SET
                assistant_name = EXCLUDED.assistant_name,
                signature_emoji = EXCLUDED.signature_emoji,
                user_directives = EXCLUDED.user_directives,
                hatched = EXCLUDED.hatched,
                updated_at = EXCLUDED.updated_at
            RETURNING
                user_id, assistant_name, signature_emoji,
                user_directives, hatched, created_at, updated_at
            """,
            profile.user_id,
            profile.assistant_name,
            profile.signature_emoji,
            profile.user_directives,
            profile.hatched,
            now,
        )
        if row is None:
            raise RuntimeError("failed to save user profile")
        return _profile_from_row(row)

    async def list_custom_agents(self, owner_id: str) -> tuple[CustomAgent, ...]:
        rows = await self._pool.fetch(
            """
            SELECT id, owner_id, name, description, system_prompt, signature_emoji, created_at
            FROM crabriks.custom_agents
            WHERE owner_id = $1
            ORDER BY created_at ASC
            """,
            owner_id,
        )
        return tuple(_custom_agent_from_row(row) for row in rows)

    async def create_custom_agent(self, agent: CustomAgent) -> CustomAgent:
        now = datetime.now(UTC)
        row = await self._pool.fetchrow(
            """
            INSERT INTO crabriks.custom_agents (
                id, owner_id, name, description, system_prompt, signature_emoji, created_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING id, owner_id, name, description, system_prompt, signature_emoji, created_at
            """,
            _uuid(agent.id),
            agent.owner_id,
            agent.name,
            agent.description,
            agent.system_prompt,
            agent.signature_emoji,
            agent.created_at or now,
        )
        if row is None:
            raise RuntimeError("failed to create custom agent")
        return _custom_agent_from_row(row)

    async def delete_custom_agent(self, agent_id: str, owner_id: str) -> bool:
        res = await self._pool.execute(
            """
            DELETE FROM crabriks.custom_agents
            WHERE id = $1 AND owner_id = $2
            """,
            _uuid(agent_id),
            owner_id,
        )
        return res.startswith("DELETE 1")

    async def create_schedule(self, schedule: ScheduleEntry) -> ScheduleEntry:
        now = datetime.now(UTC)
        row = await self._pool.fetchrow(
            """
            INSERT INTO crabriks.schedules (
                id, session_id, owner_id, cron_expression, prompt,
                status, next_run_at, created_at, last_run_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            RETURNING
                id, session_id, owner_id, cron_expression, prompt,
                status, next_run_at, created_at, last_run_at
            """,
            _uuid(schedule.id),
            _uuid(schedule.session_id),
            schedule.owner_id,
            schedule.cron_expression,
            schedule.prompt,
            schedule.status,
            schedule.next_run_at,
            schedule.created_at or now,
            schedule.last_run_at,
        )
        if row is None:
            raise RuntimeError("failed to create schedule")
        return _schedule_from_row(row)

    async def list_schedules(
        self, owner_id: str, session_id: str | None = None
    ) -> tuple[ScheduleEntry, ...]:
        query = """
            SELECT
                id, session_id, owner_id, cron_expression, prompt,
                status, next_run_at, created_at, last_run_at
            FROM crabriks.schedules
            WHERE owner_id = $1 AND ($2::uuid IS NULL OR session_id = $2::uuid)
            ORDER BY created_at DESC
        """
        rows = await self._pool.fetch(query, owner_id, _uuid(session_id) if session_id else None)
        return tuple(_schedule_from_row(r) for r in rows)

    async def cancel_schedule(self, schedule_id: str, owner_id: str) -> bool:
        res = await self._pool.execute(
            """
            UPDATE crabriks.schedules
            SET status = 'cancelled'
            WHERE id = $1 AND owner_id = $2 AND status != 'cancelled'
            """,
            _uuid(schedule_id),
            owner_id,
        )
        return res.startswith("UPDATE 1")

    async def claim_due_schedules(self, now: datetime) -> tuple[ScheduleEntry, ...]:
        rows = await self._pool.fetch(
            """
            SELECT
                id, session_id, owner_id, cron_expression, prompt,
                status, next_run_at, created_at, last_run_at
            FROM crabriks.schedules
            WHERE status = 'active' AND next_run_at <= $1
            ORDER BY next_run_at ASC
            """,
            now,
        )
        return tuple(_schedule_from_row(r) for r in rows)

    async def update_schedule_run(
        self, schedule_id: str, last_run_at: datetime, next_run_at: datetime
    ) -> ScheduleEntry | None:
        row = await self._pool.fetchrow(
            """
            UPDATE crabriks.schedules
            SET last_run_at = $2, next_run_at = $3
            WHERE id = $1
            RETURNING
                id, session_id, owner_id, cron_expression, prompt,
                status, next_run_at, created_at, last_run_at
            """,
            _uuid(schedule_id),
            last_run_at,
            next_run_at,
        )
        if row is None:
            return None
        return _schedule_from_row(row)


def _custom_agent_from_row(row: asyncpg.Record) -> CustomAgent:
    return CustomAgent(
        id=str(row["id"]),
        owner_id=row["owner_id"],
        name=row["name"],
        description=row["description"],
        system_prompt=row["system_prompt"],
        signature_emoji=row["signature_emoji"],
        created_at=row["created_at"],
    )


def _profile_from_row(row: asyncpg.Record) -> UserProfile:
    return UserProfile(
        user_id=row["user_id"],
        assistant_name=row["assistant_name"],
        signature_emoji=row["signature_emoji"],
        user_directives=row["user_directives"],
        hatched=row["hatched"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _approval_from_row(row: asyncpg.Record) -> ApprovalEntry:
    return ApprovalEntry(
        id=str(row["id"]),
        session_id=str(row["session_id"]),
        run_id=str(row["run_id"]),
        tool_name=row["tool_name"],
        tool_call_id=row["tool_call_id"],
        arguments=row["arguments"],
        status=row["status"],
        created_at=row["created_at"],
        resolved_at=row["resolved_at"],
        resolved_by=row["resolved_by"],
    )


def _schedule_from_row(row: asyncpg.Record) -> ScheduleEntry:
    return ScheduleEntry(
        id=str(row["id"]),
        session_id=str(row["session_id"]),
        owner_id=row["owner_id"],
        cron_expression=row["cron_expression"],
        prompt=row["prompt"],
        status=row["status"],
        next_run_at=row["next_run_at"],
        created_at=row["created_at"],
        last_run_at=row["last_run_at"],
    )


class RunInProgress(Exception):
    """This session already has a running turn."""


class SessionForbidden(Exception):
    """The caller does not own this session."""


class SessionNotFound(Exception):
    """No session with this id."""


class _Querier(Protocol):
    async def fetchval(self, _query: str, *_args: object) -> Any: ...

    async def execute(self, _query: str, *_args: object) -> str: ...


def cast_querier(conn: object) -> _Querier:
    """asyncpg's pool proxy is a connection; the stubs don't say so."""
    return conn  # type: ignore[return-value]


def _constraint_name(exc: BaseException) -> str | None:
    name = getattr(exc, "constraint_name", None)
    if isinstance(name, str):
        return name
    return None


def _uuid(value: str) -> UUID:
    return UUID(value)


def _entry_from_row(row: asyncpg.Record) -> TranscriptEntry:
    return TranscriptEntry(
        role=row["role"],
        content=row["content"],
        tool_name=row["tool_name"],
        tool_call_id=row["tool_call_id"],
    )


def run_state_for(*, is_running: bool, status: str | None) -> RunState:
    if is_running or status == "running":
        return "running"
    if status == "error":
        return "error"
    return "idle"


def _memory_summary(session_id: str, session: _MemorySession) -> SessionSummary:
    title = next((entry.content for entry in session.entries if entry.role == "user"), "")
    return SessionSummary(
        id=session_id,
        title=title,
        created_at=session.created_at,
        run_state=run_state_for(
            is_running=session.running is not None,
            status=session.last_status,
        ),
    )


async def _insert_or_check_owner(conn: _Querier, session: UUID, owner_id: str) -> None:
    owner = await conn.fetchval("SELECT owner_id FROM crabriks.sessions WHERE id = $1", session)
    if owner is None:
        await _insert_session(conn, session, owner_id)
        return
    if owner != owner_id:
        raise SessionForbidden(str(session))


async def _insert_session(conn: _Querier, session: UUID, owner_id: str) -> None:
    try:
        await conn.execute(
            "INSERT INTO crabriks.sessions (id, owner_id) VALUES ($1, $2)",
            session,
            owner_id,
        )
    except asyncpg.UniqueViolationError:
        owner = await conn.fetchval("SELECT owner_id FROM crabriks.sessions WHERE id = $1", session)
        if owner != owner_id:
            raise SessionForbidden(str(session)) from None


_TOKEN_TTL_SECONDS = 45 * 60
_POSTGRES_SCHEMES = ("postgres://", "postgresql://")
_SSL_OFF = frozenset({"disable", "allow", "prefer"})
_SSL_ON = frozenset({"require", "verify-ca", "verify-full"})


class MissingDatabaseCredential(Exception):
    """A Lakebase host is set, but there is no password and no endpoint to mint one."""


@dataclass(frozen=True, slots=True)
class PgConnect:
    """A `PG*` target. `password` is static; `endpoint` is minted per connection."""

    host: str
    port: int
    user: str
    database: str
    ssl: bool
    password: str | None
    endpoint: str | None


class _Minted:
    token: str = ""
    at: float = 0.0

    def fresh(self, now: float) -> bool:
        return bool(self.token) and now - self.at < _TOKEN_TTL_SECONDS


def connection_plan(env: Mapping[str, str]) -> str | PgConnect:
    """A postgres URI, or host parameters. A non-URI `DB_CONNECTION_STRING` is not a DSN."""
    dsn = _dsn(env.get("DATABASE_URL")) or _dsn(env.get("DB_CONNECTION_STRING"))
    if dsn:
        return dsn
    host = env.get("PGHOST")
    user = env.get("PGUSER")
    database = env.get("PGDATABASE")
    if not host or not user or not database:
        raise MissingDatabaseCredential
    password = env.get("PGPASSWORD") or None
    endpoint = None if password else _endpoint(env)
    if endpoint is None and password is None:
        raise MissingDatabaseCredential
    return PgConnect(
        host=host,
        port=int(env.get("PGPORT") or "5432"),
        user=user,
        database=database,
        ssl=_ssl(env, oauth=password is None),
        password=password,
        endpoint=endpoint,
    )


def _dsn(value: str | None) -> str | None:
    if value and value.startswith(_POSTGRES_SCHEMES):
        return value
    return None


def _endpoint(env: Mapping[str, str]) -> str | None:
    return env.get("LAKEBASE_ENDPOINT") or env.get("ENDPOINT_NAME") or None


def _ssl(env: Mapping[str, str], *, oauth: bool) -> bool:
    mode = (env.get("PGSSLMODE") or "").lower()
    if mode in _SSL_OFF:
        return False
    if mode in _SSL_ON:
        return True
    return oauth


def _mint_database_token(endpoint: str) -> str:
    """Lakebase Apps roles take a short-lived OAuth token as the Postgres password."""
    token = WorkspaceClient().postgres.generate_database_credential(endpoint=endpoint).token
    if not token:
        raise MissingDatabaseCredential
    return token


def _connector(plan: PgConnect) -> Callable[[], Awaitable[asyncpg.Connection]]:
    minted = _Minted()
    lock = asyncio.Lock()

    async def connect(*_args: object, **_kwargs: object) -> asyncpg.Connection:
        # The pool calls this with asyncpg.connect's arguments, including `loop`.
        if plan.endpoint is None:
            raise MissingDatabaseCredential
        token = await _token(plan.endpoint, minted, lock)
        return await asyncpg.connect(
            host=plan.host,
            port=plan.port,
            user=plan.user,
            password=token,
            database=plan.database,
            ssl=plan.ssl or None,
            timeout=_CONNECT_TIMEOUT,
        )

    return connect


async def _token(endpoint: str, minted: _Minted, lock: asyncio.Lock) -> str:
    async with lock:
        now = time.monotonic()
        if minted.fresh(now):
            return minted.token
        minted.token = await asyncio.to_thread(_mint_database_token, endpoint)
        minted.at = now
        return minted.token


def _required_pool(pool: asyncpg.Pool | None) -> asyncpg.Pool:
    if pool is None:
        raise RuntimeError("postgres pool was not created")
    return pool


async def connect_pool(env: Mapping[str, str]) -> asyncpg.Pool:
    """Open a pool from a postgres URI, a static password, or a minted Lakebase token."""
    plan = connection_plan(env)
    if isinstance(plan, str):
        return _required_pool(
            await asyncpg.create_pool(plan, min_size=1, max_size=4, timeout=_CONNECT_TIMEOUT)
        )
    if plan.password is not None:
        return _required_pool(
            await asyncpg.create_pool(
                host=plan.host,
                port=plan.port,
                user=plan.user,
                password=plan.password,
                database=plan.database,
                ssl=plan.ssl or None,
                min_size=1,
                max_size=4,
                timeout=_CONNECT_TIMEOUT,
            )
        )
    return _required_pool(
        await asyncpg.create_pool(
            connect=_connector(plan),
            min_size=1,
            max_size=4,
            timeout=_CONNECT_TIMEOUT,
        )
    )


def _lakebase_configured(env: Mapping[str, str]) -> bool:
    if _dsn(env.get("DATABASE_URL")) or _dsn(env.get("DB_CONNECTION_STRING")):
        return True
    return bool(env.get("PGHOST"))


async def _connect_with_retry(env: Mapping[str, str]) -> asyncpg.Pool:
    """Lakebase compute wakes from scale-to-zero. The first dial often fails."""
    delay = 0.5
    last: BaseException | None = None
    for attempt in range(_CONNECT_ATTEMPTS):
        try:
            return await connect_pool(env)
        except (OSError, asyncpg.PostgresConnectionError, TimeoutError) as exc:
            last = exc
            if attempt + 1 == _CONNECT_ATTEMPTS:
                break
            logger.warning("lakebase connect failed (%s); retrying", type(exc).__name__)
            await asyncio.sleep(delay)
            delay *= 2
    if last is not None:
        raise last
    raise RuntimeError("postgres pool was not created")


async def open_store(env: Mapping[str, str] | None = None) -> SessionStore:
    """Lakebase when the platform injected a database; memory otherwise."""
    source = os.environ if env is None else env
    if source.get("CRABRIKS_STORE", "").lower() == "memory" or not _lakebase_configured(source):
        return MemorySessionStore()
    pool = await _connect_with_retry(source)
    store = LakebaseSessionStore(pool)
    try:
        await store.migrate()
    except asyncpg.PostgresError:
        await store.close()
        raise
    return store
