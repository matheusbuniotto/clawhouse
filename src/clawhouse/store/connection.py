"""Lakebase connection planning, OAuth token minting, and connection pooling."""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass

import asyncpg
from databricks.sdk import WorkspaceClient

from clawhouse.store.protocol import MissingDatabaseCredential
from clawhouse.store.schema import _CONNECT_ATTEMPTS, _CONNECT_TIMEOUT

logger = logging.getLogger(__name__)

_TOKEN_TTL_SECONDS = 45 * 60
_POSTGRES_SCHEMES = ("postgres://", "postgresql://")
_SSL_OFF = frozenset({"disable", "allow", "prefer"})
_SSL_ON = frozenset({"require", "verify-ca", "verify-full"})


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
