"""Row-to-shape parsing helpers, query casting, and session activity aggregators."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

import asyncpg

from clawhouse.store.protocol import SessionForbidden, SessionStore, _Querier
from clawhouse.store.shapes import (
    ApprovalEntry,
    CustomAgent,
    MemoryEntry,
    RunState,
    ScheduleEntry,
    SessionSummary,
    TranscriptEntry,
    UserProfile,
)

if TYPE_CHECKING:
    from clawhouse.store.memory import _MemorySession


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
        last_status=row.get("last_status"),
        last_error=row.get("last_error"),
    )


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


def _memory_from_row(row: asyncpg.Record) -> MemoryEntry:
    source = row["source_session_id"]
    return MemoryEntry(
        id=str(row["id"]),
        owner_id=row["owner_id"],
        text=row["text"],
        created_at=row["created_at"],
        source_session_id=str(source) if source else None,
        table_fqn=row["table_fqn"],
    )


def _entry_from_row(row: asyncpg.Record) -> TranscriptEntry:
    return TranscriptEntry(
        role=row["role"],
        content=row["content"],
        tool_name=row["tool_name"],
        tool_call_id=row["tool_call_id"],
        agent_id=row.get("agent_id"),
        model=row.get("model"),
    )


def run_state_for(*, is_running: bool, status: str | None) -> RunState:
    if is_running or status == "running":
        return "running"
    if status == "error":
        return "error"
    return "idle"


def _summary_from_row(row: asyncpg.Record) -> SessionSummary:
    return SessionSummary(
        id=str(row["id"]),
        title=row["title"] or "",
        created_at=row["created_at"],
        run_state=run_state_for(is_running=False, status=row["latest_run_status"]),
    )


def _memory_summary(session_id: str, session: _MemorySession) -> SessionSummary:
    first = next((entry.content for entry in session.entries if entry.role == "user"), "")
    title = session.title if session.title and session.title.strip() else first
    return SessionSummary(
        id=session_id,
        title=title,
        created_at=session.created_at,
        run_state=run_state_for(
            is_running=session.running is not None,
            status=session.last_status,
        ),
    )


def _collect_session_activities(
    sessions: list[_MemorySession],
) -> dict[str, tuple[datetime, str]]:
    out: dict[str, tuple[datetime, str]] = {}
    for session in sessions:
        when = session.last_run_at or session.created_at
        for aid, text in _session_entry_pairs(session.entries):
            prev = out.get(aid)
            if prev is None or when >= prev[0]:
                out[aid] = (when, text)
    return out


def _session_entry_pairs(entries: list[TranscriptEntry]) -> list[tuple[str, str]]:
    return [
        (entry.agent_id or "main", entry.content)
        for entry in entries
        if entry.role in ("assistant", "user") and entry.content.strip()
    ]


async def agent_activities(store: SessionStore, owner_id: str) -> dict[str, tuple[datetime, str]]:
    """Most recent (last_active_at, last_activity) per agent_id for an owner's sessions."""
    return await store.agent_activities(owner_id)


async def _insert_or_check_owner(conn: _Querier, session: UUID, owner_id: str) -> None:
    owner = await conn.fetchval("SELECT owner_id FROM clawhouse.sessions WHERE id = $1", session)
    if owner is None:
        await _insert_session(conn, session, owner_id)
        return
    if owner != owner_id:
        raise SessionForbidden(str(session))


async def _insert_session(conn: _Querier, session: UUID, owner_id: str) -> None:
    try:
        await conn.execute(
            "INSERT INTO clawhouse.sessions (id, owner_id) VALUES ($1, $2)",
            session,
            owner_id,
        )
    except asyncpg.UniqueViolationError:
        owner = await conn.fetchval(
            "SELECT owner_id FROM clawhouse.sessions WHERE id = $1", session
        )
        if owner != owner_id:
            raise SessionForbidden(str(session)) from None
