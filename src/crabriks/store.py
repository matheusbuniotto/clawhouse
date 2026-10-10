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
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID, uuid4

import asyncpg
from databricks.sdk import WorkspaceClient

from crabriks.shapes import SessionSummary, TranscriptEntry, TurnStatus

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
    CONSTRAINT runs_status_known CHECK (status IN ('running', 'ok', 'error'))
);

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
"""

_RUNNING_INDEX = "runs_one_running_per_session"
_STALE_RUN_MINUTES = 10


class SessionStore(Protocol):
    async def open_session(self, session_id: str, owner_id: str) -> None: ...

    async def create_session(self, owner_id: str) -> SessionSummary: ...

    async def list_sessions(self, owner_id: str) -> tuple[SessionSummary, ...]: ...

    async def claim_run(self, session_id: str) -> str: ...

    async def append_entry(self, session_id: str, run_id: str, entry: TranscriptEntry) -> None: ...

    async def finish_run(self, session_id: str, run_id: str, status: TurnStatus) -> None: ...

    async def transcript(self, session_id: str, owner_id: str) -> tuple[TranscriptEntry, ...]: ...

    async def close(self) -> None: ...


class RunNotActive(Exception):
    """The run is not the session's current running claim."""


@dataclass
class _MemorySession:
    owner_id: str
    created_at: datetime
    entries: list[TranscriptEntry] = field(default_factory=list)
    running: str | None = None


class MemorySessionStore:
    """In-process stand-in. `running` is the partial unique index."""

    def __init__(self) -> None:
        self._sessions: dict[str, _MemorySession] = {}
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

    async def claim_run(self, session_id: str) -> str:
        async with self._lock:
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
            if session.running == run_id and status in ("ok", "error"):
                session.running = None

    async def transcript(self, session_id: str, owner_id: str) -> tuple[TranscriptEntry, ...]:
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise SessionNotFound(session_id)
            if session.owner_id != owner_id:
                raise SessionForbidden(session_id)
            return tuple(session.entries)

    async def close(self) -> None:
        return None


class LakebaseSessionStore:
    """Lakebase (Postgres) sessions, transcripts, and the running-run lock."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def migrate(self) -> None:
        await self._pool.execute(SCHEMA)

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
                ) AS title
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
            )
            for row in rows
        )

    async def claim_run(self, session_id: str) -> str:
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


def _memory_summary(session_id: str, session: _MemorySession) -> SessionSummary:
    title = next((entry.content for entry in session.entries if entry.role == "user"), "")
    return SessionSummary(id=session_id, title=title, created_at=session.created_at)


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
