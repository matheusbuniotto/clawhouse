"""Lakebase (Postgres) sessions, transcripts, and the running-run lock."""

import logging
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

import asyncpg

from clawhouse.store import mappers as _map
from clawhouse.store import protocol as _proto
from clawhouse.store import schema as _sql
from clawhouse.store.fired_rows import FiredLakebase
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

logger = logging.getLogger(__name__)


class LakebaseSessionStore(FiredLakebase):
    """Lakebase (Postgres) sessions, transcripts, and the running-run lock."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool
        self._agent_column = True

    async def migrate(self) -> None:
        self._agent_column = await _sql.migrate(self._pool)

    async def open_session(self, session_id: str, owner_id: str) -> None:
        session = _map._uuid(session_id)
        async with self._pool.acquire() as conn:
            await _map._insert_or_check_owner(_map.cast_querier(conn), session, owner_id)

    async def create_session(self, owner_id: str) -> SessionSummary:
        row = await self._pool.fetchrow(_sql._INSERT_SESSION_DEFAULT, uuid4(), owner_id)
        return SessionSummary(id=str(row["id"]), title="", created_at=row["created_at"])

    async def list_sessions(self, owner_id: str) -> tuple[SessionSummary, ...]:
        rows = await self._pool.fetch(_sql._LIST_SESSIONS_SUMMARY, owner_id)
        return tuple(_map._summary_from_row(row) for row in rows)

    async def get_session(self, session_id: str, owner_id: str) -> SessionSummary:
        await self._require_owner(session_id, owner_id)
        row = await self._pool.fetchrow(_sql._GET_SESSION_SUMMARY, _map._uuid(session_id))
        return _map._summary_from_row(row)

    async def rename_session(self, session_id: str, owner_id: str, title: str) -> SessionSummary:
        await self._require_owner(session_id, owner_id)
        await self._pool.execute(_sql._UPDATE_SESSION_TITLE, _map._uuid(session_id), title)
        return await self.get_session(session_id, owner_id)

    async def claim_run(self, session_id: str) -> str:
        if await self.has_pending_approval(session_id):
            raise _proto.ApprovalPending(session_id)
        first = await self._insert_or_reclaim(session_id)
        if first is not None:
            return first
        try:
            return await self._insert_running(session_id)
        except asyncpg.UniqueViolationError as exc:
            if _map._constraint_name(exc) == _sql._RUNNING_INDEX:
                raise _proto.RunInProgress(session_id) from exc
            raise

    async def _insert_or_reclaim(self, session_id: str) -> str | None:
        try:
            return await self._insert_running(session_id)
        except asyncpg.UniqueViolationError as exc:
            if _map._constraint_name(exc) != _sql._RUNNING_INDEX:
                raise
            if not await self._reclaim_stale(session_id):
                raise _proto.RunInProgress(session_id) from exc
            return None

    async def _insert_running(self, session_id: str) -> str:
        run_id = uuid4()
        await self._pool.execute(_sql._INSERT_RUN_RUNNING, run_id, _map._uuid(session_id))
        return str(run_id)

    async def _reclaim_stale(self, session_id: str) -> bool:
        reclaimed = await self._pool.fetchval(
            _sql._RECLAIM_STALE_RUN, _map._uuid(session_id), _sql._STALE_RUN_MINUTES
        )
        return reclaimed is not None

    async def append_entry(self, session_id: str, run_id: str, entry: TranscriptEntry) -> None:
        session, run = _map._uuid(session_id), _map._uuid(run_id)
        async with self._pool.acquire() as conn, conn.transaction():
            active = await conn.fetchval(_sql._SELECT_RUN_ACTIVE, run, session)
            if active is None:
                raise _proto.RunNotActive(run_id)
            await conn.execute(_sql._LOCK_SESSION, session)
            position = await conn.fetchval(_sql._SELECT_MAX_POSITION, session)
            extra = (entry.agent_id, entry.model) if self._agent_column else ()
            await conn.execute(
                _sql._INSERT_ENTRY if self._agent_column else _sql._INSERT_ENTRY_LEGACY,
                session,
                run,
                position,
                entry.role,
                entry.content,
                entry.tool_name,
                entry.tool_call_id,
                *extra,
            )

    async def finish_run(self, session_id: str, run_id: str, status: TurnStatus) -> None:
        await self._pool.execute(
            _sql._UPDATE_RUN_STATUS, _map._uuid(run_id), _map._uuid(session_id), status
        )

    async def transcript(self, session_id: str, owner_id: str) -> tuple[TranscriptEntry, ...]:
        rows = await self._pool.fetch(
            _sql._SELECT_TRANSCRIPT_ENTRIES, _map._uuid(session_id), owner_id
        )
        if rows:
            return tuple(_map._entry_from_row(row) for row in rows)
        await self._require_owner(session_id, owner_id)
        return ()

    async def clear_transcript(self, session_id: str, owner_id: str) -> None:
        await self._require_owner(session_id, owner_id)
        session = _map._uuid(session_id)
        async with self._pool.acquire() as conn, conn.transaction():
            await conn.execute(_sql._DELETE_TRANSCRIPT_FOR_SESSION, session)
            await conn.execute(_sql._CLEAR_SESSION_MESSAGES, session)

    async def messages(self, session_id: str) -> bytes | None:
        row = await self._pool.fetchrow(_sql._SELECT_SESSION_MESSAGES, _map._uuid(session_id))
        if row is None:
            raise _proto.SessionNotFound(session_id)
        raw = row["messages"]
        if raw is None:
            return None
        return raw.encode("utf-8") if isinstance(raw, str) else bytes(raw)

    async def save_messages(self, session_id: str, messages: bytes) -> None:
        text = messages.decode("utf-8") if isinstance(messages, bytes) else str(messages)
        res = await self._pool.execute(_sql._UPDATE_SESSION_MESSAGES, text, _map._uuid(session_id))
        if res == "UPDATE 0":
            raise _proto.SessionNotFound(session_id)

    async def delete_session(self, session_id: str, owner_id: str) -> bool:
        await self._require_owner(session_id, owner_id)
        session = _map._uuid(session_id)
        async with self._pool.acquire() as conn, conn.transaction():
            for stmt in (
                _sql._DELETE_SESSION_MEMORIES,
                _sql._DELETE_SESSION_APPROVALS,
                _sql._DELETE_TRANSCRIPT_FOR_SESSION,
                _sql._DELETE_SESSION_RUNS,
            ):
                await conn.execute(stmt, session)
            deleted = await conn.execute(_sql._DELETE_SESSION, session)
            return "DELETE 1" in deleted

    async def save_memory(
        self,
        owner_id: str,
        text: str,
        source_session_id: str | None = None,
        table_fqn: str | None = None,
    ) -> MemoryEntry:
        if source_session_id is not None:
            await self.get_session(source_session_id, owner_id)
        row = await self._pool.fetchrow(
            _sql._INSERT_MEMORY_ENTRY,
            uuid4(),
            owner_id,
            text,
            _map._uuid(source_session_id) if source_session_id else None,
            table_fqn,
        )
        return _map._memory_from_row(row)

    async def list_memories(self, owner_id: str, limit: int = 20) -> tuple[MemoryEntry, ...]:
        rows = await self._pool.fetch(_sql._SELECT_MEMORY_ENTRIES, owner_id, limit)
        return tuple(_map._memory_from_row(row) for row in rows)

    async def delete_memory(self, owner_id: str, memory_id: str) -> bool:
        deleted = await self._pool.execute(
            _sql._DELETE_MEMORY_ENTRY, _map._uuid(memory_id), owner_id
        )
        return "DELETE 1" in deleted

    async def search_transcripts(
        self, owner_id: str, query: str, limit: int
    ) -> tuple[SearchHit, ...]:
        rows = await self._pool.fetch(_sql._SEARCH_TRANSCRIPTS_SQL, owner_id, query, limit)
        return tuple(
            SearchHit(
                session_id=str(row["session_id"]),
                role=row["role"],
                excerpt=row["excerpt"],
                created_at=row["started_at"],
            )
            for row in rows
        )

    async def rank_memories(
        self, owner_id: str, query: str, limit: int = 5
    ) -> tuple[MemoryEntry, ...]:
        rows = await self._pool.fetch(_sql._RANK_MEMORIES_SQL, owner_id, query, limit)
        return tuple(_map._memory_from_row(row) for row in rows)

    async def close(self) -> None:
        await self._pool.close()

    async def _require_owner(self, session_id: str, owner_id: str) -> None:
        owner = await self._pool.fetchval(_sql._SELECT_SESSION_OWNER, _map._uuid(session_id))
        if owner is None:
            raise _proto.SessionNotFound(session_id)
        if owner != owner_id:
            raise _proto.SessionForbidden(session_id)

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
            _sql._INSERT_APPROVAL_ENTRY,
            uuid4(),
            _map._uuid(session_id),
            _map._uuid(run_id),
            tool_name,
            tool_call_id,
            arguments,
        )
        if row is None:
            raise RuntimeError("approval row was not returned")
        return _map._approval_from_row(row)

    async def get_approval(self, approval_id: str) -> ApprovalEntry:
        row = await self._pool.fetchrow(_sql._SELECT_APPROVAL_BY_ID, _map._uuid(approval_id))
        if row is None:
            raise _proto.ApprovalNotFound(approval_id)
        return _map._approval_from_row(row)

    async def list_approvals(
        self,
        owner_id: str,
        status: ApprovalStatus | None = None,
    ) -> tuple[ApprovalEntry, ...]:
        query = _sql._SELECT_APPROVALS_BASE
        if status is not None:
            query += " AND a.status = $2 ORDER BY a.created_at DESC"
            rows = await self._pool.fetch(query, owner_id, status)
        else:
            query += " ORDER BY a.created_at DESC"
            rows = await self._pool.fetch(query, owner_id)
        return tuple(_map._approval_from_row(row) for row in rows)

    async def resolve_approval(
        self,
        approval_id: str,
        status: Literal["approved", "denied"],
        resolver_id: str,
        resolved_at: datetime | None = None,
    ) -> ApprovalEntry:
        app_id = _map._uuid(approval_id)
        when = resolved_at or datetime.now(UTC)
        async with self._pool.acquire() as conn, conn.transaction():
            current_status = await conn.fetchval(_sql._SELECT_APPROVAL_STATUS_FOR_UPDATE, app_id)
            if current_status is None:
                raise _proto.ApprovalNotFound(approval_id)
            if current_status != "pending":
                raise _proto.ApprovalAlreadyResolved(approval_id)
            row = await conn.fetchrow(
                _sql._UPDATE_APPROVAL_RESOLUTION, app_id, status, when, resolver_id
            )
            if row is None:
                raise RuntimeError("updated approval row was not returned")
            return _map._approval_from_row(row)

    async def has_pending_approval(self, session_id: str) -> bool:
        val = await self._pool.fetchval(_sql._EXISTS_PENDING_APPROVAL, _map._uuid(session_id))
        return val is not None

    async def get_user_profile(self, user_id: str) -> UserProfile | None:
        row = await self._pool.fetchrow(_sql._SELECT_USER_PROFILE_BY_ID, user_id)
        return _map._profile_from_row(row) if row is not None else None

    async def save_user_profile(self, profile: UserProfile) -> UserProfile:
        now = datetime.now(UTC)
        row = await self._pool.fetchrow(
            _sql._UPSERT_USER_PROFILE_SQL,
            profile.user_id,
            profile.assistant_name,
            profile.signature_emoji,
            profile.user_directives,
            profile.hatched,
            now,
        )
        if row is None:
            raise RuntimeError("failed to save user profile")
        return _map._profile_from_row(row)

    async def list_custom_agents(self, owner_id: str) -> tuple[CustomAgent, ...]:
        rows = await self._pool.fetch(_sql._SELECT_CUSTOM_AGENTS_BY_OWNER, owner_id)
        return tuple(_map._custom_agent_from_row(row) for row in rows)

    async def create_custom_agent(self, agent: CustomAgent) -> CustomAgent:
        now = datetime.now(UTC)
        row = await self._pool.fetchrow(
            _sql._INSERT_CUSTOM_AGENT_ENTRY,
            _map._uuid(agent.id),
            agent.owner_id,
            agent.name,
            agent.description,
            agent.system_prompt,
            agent.signature_emoji,
            agent.created_at or now,
        )
        if row is None:
            raise RuntimeError("failed to create custom agent")
        return _map._custom_agent_from_row(row)

    async def delete_custom_agent(self, agent_id: str, owner_id: str) -> bool:
        res = await self._pool.execute(
            _sql._DELETE_CUSTOM_AGENT_BY_ID, _map._uuid(agent_id), owner_id
        )
        return res.startswith("DELETE 1")

    async def agent_activities(self, owner_id: str) -> dict[str, tuple[datetime, str]]:
        if not self._agent_column:
            return {}
        rows = await self._pool.fetch(_sql._SELECT_AGENT_ACTIVITIES_SQL, owner_id)
        return {
            str(row["agent_id"]): (row["last_active_at"], str(row["last_activity"])) for row in rows
        }

    async def create_schedule(self, schedule: ScheduleEntry) -> ScheduleEntry:
        now = datetime.now(UTC)
        row = await self._pool.fetchrow(
            _sql._INSERT_SCHEDULE_ENTRY,
            _map._uuid(schedule.id),
            _map._uuid(schedule.session_id),
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
        return _map._schedule_from_row(row)

    async def list_schedules(
        self, owner_id: str, session_id: str | None = None
    ) -> tuple[ScheduleEntry, ...]:
        rows = await self._pool.fetch(
            _sql._SELECT_SCHEDULES_BASE, owner_id, _map._uuid(session_id) if session_id else None
        )
        return tuple(_map._schedule_from_row(r) for r in rows)

    async def cancel_schedule(self, schedule_id: str, owner_id: str) -> bool:
        res = await self._pool.execute(_sql._CANCEL_SCHEDULE_SQL, _map._uuid(schedule_id), owner_id)
        return res.startswith("UPDATE 1")

    async def claim_due_schedules(self, now: datetime) -> tuple[ScheduleEntry, ...]:
        rows = await self._pool.fetch(_sql._CLAIM_DUE_SCHEDULES_SQL, now)
        return tuple(_map._schedule_from_row(r) for r in rows)

    async def update_schedule_run(
        self,
        schedule_id: str,
        last_run_at: datetime,
        next_run_at: datetime,
        *,
        last_status: str | None = None,
        last_error: str | None = None,
    ) -> ScheduleEntry | None:
        sid = _map._uuid(schedule_id)
        row = await self._pool.fetchrow(
            _sql._UPDATE_SCHEDULE_RUN_SQL, sid, last_run_at, next_run_at, last_status, last_error
        )
        return _map._schedule_from_row(row) if row is not None else None
