"""Session, transcript, and run-lock storage facade.

Re-exports all protocol definitions, exceptions, schemas, connections,
adapters, and mappers for backwards compatibility.
"""

import os
from collections.abc import Mapping

import asyncpg

from clawhouse.store.connection import (
    PgConnect,
    _connect_with_retry,
    _connector,
    _dsn,
    _endpoint,
    _lakebase_configured,
    _mint_database_token,
    _Minted,
    _required_pool,
    _ssl,
    _token,
    connect_pool,
    connection_plan,
)
from clawhouse.store.lakebase import LakebaseSessionStore
from clawhouse.store.mappers import (
    _approval_from_row,
    _collect_session_activities,
    _constraint_name,
    _custom_agent_from_row,
    _entry_from_row,
    _insert_or_check_owner,
    _insert_session,
    _memory_from_row,
    _memory_summary,
    _profile_from_row,
    _schedule_from_row,
    _session_entry_pairs,
    _summary_from_row,
    _uuid,
    agent_activities,
    cast_querier,
    run_state_for,
)
from clawhouse.store.memory import MemorySessionStore, _MemorySession
from clawhouse.store.protocol import (
    ApprovalAlreadyResolved,
    ApprovalForbidden,
    ApprovalNotFound,
    ApprovalPending,
    MissingDatabaseCredential,
    RunInProgress,
    RunNotActive,
    SessionForbidden,
    SessionNotFound,
    SessionStore,
    _Querier,
)
from clawhouse.store.schema import (
    _CONNECT_ATTEMPTS,
    _CONNECT_TIMEOUT,
    _INSERT_ENTRY,
    _INSERT_ENTRY_LEGACY,
    _RUNNING_INDEX,
    _SESSION_SUMMARY,
    _STALE_RUN_MINUTES,
    SCHEMA,
    migrate,
)
from clawhouse.store.shapes import (
    ApprovalEntry,
    ApprovalStatus,
    CustomAgent,
    MemoryEntry,
    Role,
    RunState,
    ScheduleEntry,
    SearchHit,
    SessionSummary,
    TranscriptEntry,
    TurnResult,
    TurnStatus,
    UserProfile,
)


async def open_store(env: Mapping[str, str] | None = None) -> SessionStore:
    """Lakebase when the platform injected a database; memory otherwise."""
    source = os.environ if env is None else env
    if source.get("CLAWHOUSE_STORE", "").lower() == "memory" or not _lakebase_configured(source):
        return MemorySessionStore()
    pool = await _connect_with_retry(source)
    store = LakebaseSessionStore(pool)
    try:
        await store.migrate()
    except asyncpg.PostgresError:
        await store.close()
        raise
    return store


__all__ = [
    "SCHEMA",
    "_CONNECT_ATTEMPTS",
    "_CONNECT_TIMEOUT",
    "_INSERT_ENTRY",
    "_INSERT_ENTRY_LEGACY",
    "_RUNNING_INDEX",
    "_SESSION_SUMMARY",
    "_STALE_RUN_MINUTES",
    "ApprovalAlreadyResolved",
    "ApprovalEntry",
    "ApprovalForbidden",
    "ApprovalNotFound",
    "ApprovalPending",
    "ApprovalStatus",
    "CustomAgent",
    "LakebaseSessionStore",
    "MemoryEntry",
    "MemorySessionStore",
    "MissingDatabaseCredential",
    "PgConnect",
    "Role",
    "RunInProgress",
    "RunNotActive",
    "RunState",
    "ScheduleEntry",
    "SearchHit",
    "SessionForbidden",
    "SessionNotFound",
    "SessionStore",
    "SessionSummary",
    "TranscriptEntry",
    "TurnResult",
    "TurnStatus",
    "UserProfile",
    "_MemorySession",
    "_Minted",
    "_Querier",
    "_approval_from_row",
    "_collect_session_activities",
    "_connect_with_retry",
    "_connector",
    "_constraint_name",
    "_custom_agent_from_row",
    "_dsn",
    "_endpoint",
    "_entry_from_row",
    "_insert_or_check_owner",
    "_insert_session",
    "_lakebase_configured",
    "_memory_from_row",
    "_memory_summary",
    "_mint_database_token",
    "_profile_from_row",
    "_required_pool",
    "_schedule_from_row",
    "_session_entry_pairs",
    "_ssl",
    "_summary_from_row",
    "_token",
    "_uuid",
    "agent_activities",
    "cast_querier",
    "connect_pool",
    "connection_plan",
    "migrate",
    "open_store",
    "run_state_for",
]
