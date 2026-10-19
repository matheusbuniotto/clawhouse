"""Database schema DDL, constants, query strings, and migration runner for Lakebase."""

import logging
from contextlib import suppress

import asyncpg

from clawhouse.store.fired_schema import FIRED_DDL

logger = logging.getLogger(__name__)

_CONNECT_ATTEMPTS = 5
_CONNECT_TIMEOUT = 10
_RUNNING_INDEX = "runs_one_running_per_session"
_STALE_RUN_MINUTES = 10

# The app service principal owns this schema. It can create objects, and it
# cannot create tables in `public` on Postgres 15+.
SCHEMA = (
    """
CREATE SCHEMA IF NOT EXISTS clawhouse;

CREATE TABLE IF NOT EXISTS clawhouse.sessions (
    id uuid PRIMARY KEY,
    owner_id text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    title text,
    messages text
);

CREATE TABLE IF NOT EXISTS clawhouse.runs (
    id uuid PRIMARY KEY,
    session_id uuid NOT NULL REFERENCES clawhouse.sessions (id),
    status text NOT NULL,
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    CONSTRAINT runs_status_known CHECK (status IN ('running', 'ok', 'error', 'pending_approval'))
);

CREATE UNIQUE INDEX IF NOT EXISTS runs_one_running_per_session
    ON clawhouse.runs (session_id)
    WHERE status = 'running';

CREATE TABLE IF NOT EXISTS clawhouse.transcript_entries (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id uuid NOT NULL REFERENCES clawhouse.sessions (id),
    run_id uuid NOT NULL REFERENCES clawhouse.runs (id),
    position integer NOT NULL,
    role text NOT NULL,
    content text NOT NULL,
    tool_name text,
    tool_call_id text,
    agent_id text,
    model text,
    CONSTRAINT transcript_role_known CHECK (
        role IN ('user', 'assistant', 'tool_call', 'tool_result', 'notice')
    ),
    CONSTRAINT transcript_position_unique UNIQUE (session_id, position)
);

CREATE TABLE IF NOT EXISTS clawhouse.approvals (
    id uuid PRIMARY KEY,
    session_id uuid NOT NULL REFERENCES clawhouse.sessions (id),
    run_id uuid NOT NULL REFERENCES clawhouse.runs (id),
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
    ON clawhouse.approvals (session_id, status);

CREATE TABLE IF NOT EXISTS clawhouse.user_profiles (
    user_id text PRIMARY KEY,
    assistant_name text,
    signature_emoji text,
    user_directives text,
    hatched boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS clawhouse.custom_agents (
    id uuid PRIMARY KEY,
    owner_id text NOT NULL,
    name text NOT NULL,
    description text NOT NULL,
    system_prompt text NOT NULL,
    signature_emoji text NOT NULL DEFAULT '🤖',
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS custom_agents_owner_idx
    ON clawhouse.custom_agents (owner_id);

CREATE TABLE IF NOT EXISTS clawhouse.schedules (
    id uuid PRIMARY KEY,
    session_id uuid NOT NULL REFERENCES clawhouse.sessions (id),
    owner_id text NOT NULL,
    cron_expression text NOT NULL,
    prompt text NOT NULL,
    status text NOT NULL DEFAULT 'active',
    last_run_at timestamptz,
    next_run_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    last_status text,
    last_error text,
    CONSTRAINT schedules_status_known CHECK (status IN ('active', 'paused', 'cancelled'))
);

CREATE INDEX IF NOT EXISTS schedules_owner_idx
    ON clawhouse.schedules (owner_id);

CREATE TABLE IF NOT EXISTS clawhouse.memory_entries (
    id uuid PRIMARY KEY,
    owner_id text NOT NULL,
    text text NOT NULL,
    source_session_id uuid NULL REFERENCES clawhouse.sessions (id),
    table_fqn text NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS transcript_search_idx
    ON clawhouse.transcript_entries USING GIN (to_tsvector('english', content));

CREATE INDEX IF NOT EXISTS schedules_due_idx
    ON clawhouse.schedules (status, next_run_at)
    WHERE status = 'active';
"""
    + FIRED_DDL
)

_INSERT_ENTRY = (
    "INSERT INTO clawhouse.transcript_entries "
    "(session_id, run_id, position, role, content, tool_name, tool_call_id, agent_id, model) "
    "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)"
)

_INSERT_ENTRY_LEGACY = (
    "INSERT INTO clawhouse.transcript_entries "
    "(session_id, run_id, position, role, content, tool_name, tool_call_id) "
    "VALUES ($1, $2, $3, $4, $5, $6, $7)"
)

# A custom title wins; a blank or missing one falls back to the first user turn.
_SESSION_SUMMARY = (
    "SELECT s.id, s.created_at, "
    "COALESCE(NULLIF(btrim(s.title), ''), ("
    "    SELECT t.content FROM clawhouse.transcript_entries AS t "
    "    WHERE t.session_id = s.id AND t.role = 'user' "
    "    ORDER BY t.position LIMIT 1"
    ")) AS title, ("
    "    SELECT r.status FROM clawhouse.runs AS r "
    "    WHERE r.session_id = s.id "
    "    ORDER BY (r.status = 'running') DESC, r.started_at DESC LIMIT 1"
    ") AS latest_run_status "
    "FROM clawhouse.sessions AS s"
)
_LIST_SESSIONS_SUMMARY = f"{_SESSION_SUMMARY} WHERE s.owner_id = $1 ORDER BY s.created_at DESC"
_GET_SESSION_SUMMARY = f"{_SESSION_SUMMARY} WHERE s.id = $1"

_INSERT_SESSION_DEFAULT = (
    "INSERT INTO clawhouse.sessions (id, owner_id) VALUES ($1, $2) RETURNING id, created_at"
)
_UPDATE_SESSION_TITLE = "UPDATE clawhouse.sessions SET title = $2 WHERE id = $1"
_INSERT_RUN_RUNNING = (
    "INSERT INTO clawhouse.runs (id, session_id, status) VALUES ($1, $2, 'running')"
)
_RECLAIM_STALE_RUN = (
    "UPDATE clawhouse.runs SET status = 'error', finished_at = now() WHERE id = ("
    "    SELECT id FROM clawhouse.runs "
    "    WHERE session_id = $1 AND status = 'running' "
    "      AND started_at < now() - make_interval(mins => $2) "
    "    LIMIT 1"
    ") RETURNING id"
)
_SELECT_RUN_ACTIVE = (
    "SELECT 1 FROM clawhouse.runs WHERE id = $1 AND session_id = $2 AND status = 'running'"
)
_LOCK_SESSION = "SELECT id FROM clawhouse.sessions WHERE id = $1 FOR UPDATE"
_SELECT_MAX_POSITION = (
    "SELECT COALESCE(MAX(position), 0) + 1 FROM clawhouse.transcript_entries WHERE session_id = $1"
)
_UPDATE_RUN_STATUS = (
    "UPDATE clawhouse.runs SET status = $3, finished_at = now() "
    "WHERE id = $1 AND session_id = $2 AND status = 'running'"
)
_SELECT_TRANSCRIPT_ENTRIES = (
    "SELECT t.* FROM clawhouse.transcript_entries AS t "
    "JOIN clawhouse.sessions AS s ON s.id = t.session_id "
    "WHERE t.session_id = $1 AND s.owner_id = $2 ORDER BY t.position"
)
_DELETE_TRANSCRIPT_FOR_SESSION = "DELETE FROM clawhouse.transcript_entries WHERE session_id = $1"
_CLEAR_SESSION_MESSAGES = "UPDATE clawhouse.sessions SET messages = NULL WHERE id = $1"
_SELECT_SESSION_MESSAGES = "SELECT messages FROM clawhouse.sessions WHERE id = $1"
_UPDATE_SESSION_MESSAGES = "UPDATE clawhouse.sessions SET messages = $1 WHERE id = $2"
_DELETE_SESSION_MEMORIES = "DELETE FROM clawhouse.memory_entries WHERE source_session_id = $1"
_DELETE_SESSION_APPROVALS = "DELETE FROM clawhouse.approvals WHERE session_id = $1"
_DELETE_SESSION_RUNS = "DELETE FROM clawhouse.runs WHERE session_id = $1"
_DELETE_SESSION = "DELETE FROM clawhouse.sessions WHERE id = $1"
_INSERT_MEMORY_ENTRY = (
    "INSERT INTO clawhouse.memory_entries (id, owner_id, text, source_session_id, table_fqn) "
    "VALUES ($1, $2, $3, $4, $5) "
    "RETURNING id, owner_id, text, source_session_id, table_fqn, created_at"
)
_SELECT_MEMORY_ENTRIES = (
    "SELECT id, owner_id, text, source_session_id, table_fqn, created_at "
    "FROM clawhouse.memory_entries WHERE owner_id = $1 ORDER BY created_at DESC LIMIT $2"
)
_DELETE_MEMORY_ENTRY = "DELETE FROM clawhouse.memory_entries WHERE id = $1 AND owner_id = $2"
_SEARCH_TRANSCRIPTS_SQL = (
    "SELECT s.id AS session_id, t.role, left(t.content, 240) AS excerpt, r.started_at "
    "FROM clawhouse.transcript_entries AS t "
    "JOIN clawhouse.sessions AS s ON s.id = t.session_id "
    "JOIN clawhouse.runs AS r ON r.id = t.run_id "
    "WHERE s.owner_id = $1 "
    "  AND to_tsvector('english', t.content) @@ websearch_to_tsquery('english', $2) "
    "ORDER BY r.started_at DESC LIMIT $3"
)
_RANK_MEMORIES_SQL = (
    "SELECT id, owner_id, text, source_session_id, table_fqn, created_at, "
    "       ts_rank(to_tsvector('english', text), websearch_to_tsquery('english', $2)) AS rank "
    "FROM clawhouse.memory_entries WHERE owner_id = $1 "
    "  AND to_tsvector('english', text) @@ websearch_to_tsquery('english', $2) "
    "ORDER BY rank DESC, created_at DESC LIMIT $3"
)
_SELECT_SESSION_OWNER = "SELECT owner_id FROM clawhouse.sessions WHERE id = $1"
_INSERT_APPROVAL_ENTRY = (
    "INSERT INTO clawhouse.approvals "
    "(id, session_id, run_id, tool_name, tool_call_id, arguments, status) "
    "VALUES ($1, $2, $3, $4, $5, $6, 'pending') "
    "RETURNING id, session_id, run_id, tool_name, tool_call_id, "
    "arguments, status, created_at, resolved_at, resolved_by"
)
_SELECT_APPROVAL_BY_ID = (
    "SELECT id, session_id, run_id, tool_name, tool_call_id, "
    "arguments, status, created_at, resolved_at, resolved_by "
    "FROM clawhouse.approvals WHERE id = $1"
)
_SELECT_APPROVALS_BASE = (
    "SELECT a.id, a.session_id, a.run_id, a.tool_name, a.tool_call_id, "
    "a.arguments, a.status, a.created_at, a.resolved_at, a.resolved_by "
    "FROM clawhouse.approvals AS a JOIN clawhouse.sessions AS s ON s.id = a.session_id "
    "WHERE s.owner_id = $1"
)
_SELECT_APPROVAL_STATUS_FOR_UPDATE = (
    "SELECT status FROM clawhouse.approvals WHERE id = $1 FOR UPDATE"
)
_UPDATE_APPROVAL_RESOLUTION = (
    "UPDATE clawhouse.approvals SET status = $2, resolved_at = $3, resolved_by = $4 WHERE id = $1 "
    "RETURNING id, session_id, run_id, tool_name, tool_call_id, "
    "arguments, status, created_at, resolved_at, resolved_by"
)
_EXISTS_PENDING_APPROVAL = (
    "SELECT 1 FROM clawhouse.approvals WHERE session_id = $1 AND status = 'pending' LIMIT 1"
)
_SELECT_USER_PROFILE_BY_ID = (
    "SELECT user_id, assistant_name, signature_emoji, user_directives, "
    "hatched, created_at, updated_at "
    "FROM clawhouse.user_profiles WHERE user_id = $1"
)
_UPSERT_USER_PROFILE_SQL = (
    "INSERT INTO clawhouse.user_profiles "
    "(user_id, assistant_name, signature_emoji, user_directives, hatched, created_at, updated_at) "
    "VALUES ($1, $2, $3, $4, $5, $6, $6) "
    "ON CONFLICT (user_id) DO UPDATE SET "
    "    assistant_name = EXCLUDED.assistant_name, "
    "    signature_emoji = EXCLUDED.signature_emoji, "
    "    user_directives = EXCLUDED.user_directives, "
    "    hatched = EXCLUDED.hatched, "
    "    updated_at = EXCLUDED.updated_at "
    "RETURNING user_id, assistant_name, signature_emoji, user_directives, "
    "hatched, created_at, updated_at"
)
_SELECT_CUSTOM_AGENTS_BY_OWNER = (
    "SELECT id, owner_id, name, description, system_prompt, signature_emoji, created_at "
    "FROM clawhouse.custom_agents WHERE owner_id = $1 ORDER BY created_at ASC"
)
_INSERT_CUSTOM_AGENT_ENTRY = (
    "INSERT INTO clawhouse.custom_agents "
    "(id, owner_id, name, description, system_prompt, signature_emoji, created_at) "
    "VALUES ($1, $2, $3, $4, $5, $6, $7) "
    "RETURNING id, owner_id, name, description, system_prompt, signature_emoji, created_at"
)
_DELETE_CUSTOM_AGENT_BY_ID = "DELETE FROM clawhouse.custom_agents WHERE id = $1 AND owner_id = $2"
_SELECT_AGENT_ACTIVITIES_SQL = (
    "SELECT DISTINCT ON (COALESCE(t.agent_id, 'main')) "
    "    COALESCE(t.agent_id, 'main') AS agent_id, "
    "    r.started_at AS last_active_at, "
    "    t.content AS last_activity "
    "FROM clawhouse.transcript_entries AS t "
    "JOIN clawhouse.runs AS r ON r.id = t.run_id "
    "JOIN clawhouse.sessions AS s ON s.id = t.session_id "
    "WHERE s.owner_id = $1 AND t.role IN ('assistant', 'user') "
    "ORDER BY COALESCE(t.agent_id, 'main'), r.started_at DESC, t.position DESC"
)
_INSERT_SCHEDULE_ENTRY = (
    "INSERT INTO clawhouse.schedules "
    "(id, session_id, owner_id, cron_expression, prompt, status, "
    "next_run_at, created_at, last_run_at) "
    "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9) "
    "RETURNING id, session_id, owner_id, cron_expression, prompt, "
    "status, next_run_at, created_at, last_run_at, last_status, last_error"
)
_SELECT_SCHEDULES_BASE = (
    "SELECT id, session_id, owner_id, cron_expression, prompt, "
    "status, next_run_at, created_at, last_run_at, last_status, last_error "
    "FROM clawhouse.schedules WHERE owner_id = $1 AND ($2::uuid IS NULL OR session_id = $2::uuid) "
    "ORDER BY created_at DESC"
)
_CANCEL_SCHEDULE_SQL = (
    "UPDATE clawhouse.schedules SET status = 'cancelled' "
    "WHERE id = $1 AND owner_id = $2 AND status != 'cancelled'"
)
_CLAIM_DUE_SCHEDULES_SQL = (
    "SELECT id, session_id, owner_id, cron_expression, prompt, "
    "status, next_run_at, created_at, last_run_at, last_status, last_error "
    "FROM clawhouse.schedules WHERE status = 'active' AND next_run_at <= $1 "
    "ORDER BY next_run_at ASC FOR UPDATE SKIP LOCKED"
)

_UPDATE_SCHEDULE_RUN_SQL = (
    "UPDATE clawhouse.schedules "
    "SET last_run_at = $2, next_run_at = $3, last_status = $4, last_error = $5 "
    "WHERE id = $1 "
    "RETURNING id, session_id, owner_id, cron_expression, prompt, "
    "status, next_run_at, created_at, last_run_at, last_status, last_error"
)


_MIGRATE_CONSTRAINTS = """
DO $$
BEGIN
    ALTER TABLE clawhouse.runs DROP CONSTRAINT IF EXISTS runs_status_known;
    ALTER TABLE clawhouse.runs ADD CONSTRAINT runs_status_known
        CHECK (status IN ('running', 'ok', 'error', 'pending_approval'));
    ALTER TABLE clawhouse.transcript_entries
        DROP CONSTRAINT IF EXISTS transcript_role_known;
    ALTER TABLE clawhouse.transcript_entries ADD CONSTRAINT transcript_role_known
        CHECK (role IN ('user', 'assistant', 'tool_call', 'tool_result', 'notice'));
EXCEPTION
    WHEN undefined_table OR insufficient_privilege THEN NULL;
END $$;
"""

_MIGRATE_COLUMNS = """
ALTER TABLE clawhouse.transcript_entries ADD COLUMN IF NOT EXISTS agent_id text;
ALTER TABLE clawhouse.transcript_entries ADD COLUMN IF NOT EXISTS model text;
ALTER TABLE clawhouse.sessions ADD COLUMN IF NOT EXISTS title text;
ALTER TABLE clawhouse.sessions ADD COLUMN IF NOT EXISTS messages text;
ALTER TABLE clawhouse.schedules ADD COLUMN IF NOT EXISTS last_status text;
ALTER TABLE clawhouse.schedules ADD COLUMN IF NOT EXISTS last_error text;
"""

_CHECK_AGENT_COLUMNS = """
SELECT count(*) FROM information_schema.columns
WHERE table_schema = 'clawhouse'
  AND table_name = 'transcript_entries'
  AND column_name IN ('agent_id', 'model')
"""


async def migrate(pool: asyncpg.Pool) -> bool:
    """Run idempotent Lakebase schema migrations. Returns whether agent columns are present."""
    try:
        await pool.execute(SCHEMA)
    except asyncpg.InsufficientPrivilegeError:
        logger.info("Skipping SCHEMA creation: insufficient privilege (tables already exist)")
    with suppress(asyncpg.InsufficientPrivilegeError):
        await pool.execute(_MIGRATE_CONSTRAINTS)
    with suppress(asyncpg.InsufficientPrivilegeError):
        await pool.execute(_MIGRATE_COLUMNS)
    present = await pool.fetchval(_CHECK_AGENT_COLUMNS)
    agent_column = present == 2
    if not agent_column:
        logger.warning("transcript_entries.agent_id/model are missing; agent ids are not persisted")
    return agent_column
