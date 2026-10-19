"""Fired-job tables and delivery statements."""

FIRED_DDL = """
CREATE TABLE IF NOT EXISTS clawhouse.fired_jobs (
    id uuid PRIMARY KEY,
    session_id uuid NOT NULL REFERENCES clawhouse.sessions (id),
    owner_id text NOT NULL,
    kind text NOT NULL,
    name text NOT NULL,
    slack_webhook_url text NOT NULL,
    agent_name text,
    instructions text NOT NULL DEFAULT '',
    databricks_job_id bigint,
    schedule_id uuid,
    CONSTRAINT fired_jobs_kind_known CHECK (kind IN ('sql', 'sql_agent', 'agent'))
);

CREATE TABLE IF NOT EXISTS clawhouse.deliveries (
    id uuid PRIMARY KEY,
    fired_job_id uuid NOT NULL REFERENCES clawhouse.fired_jobs (id),
    databricks_job_id bigint,
    run_id bigint,
    event_type text,
    schedule_id uuid,
    next_run_at timestamptz,
    sheet_status text
);

CREATE UNIQUE INDEX IF NOT EXISTS fired_delivery_run_idx
    ON clawhouse.deliveries (databricks_job_id, run_id, event_type);

CREATE UNIQUE INDEX IF NOT EXISTS fired_delivery_slot_idx
    ON clawhouse.deliveries (schedule_id, next_run_at);
"""

_INSERT_FIRED_JOB = (
    "INSERT INTO clawhouse.fired_jobs "
    "(id, session_id, owner_id, kind, name, slack_webhook_url, agent_name, instructions, "
    "databricks_job_id, schedule_id) "
    "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10) "
    "RETURNING id, session_id, owner_id, kind, name, slack_webhook_url, agent_name, "
    "instructions, databricks_job_id, schedule_id"
)
_SELECT_FIRED_BY_JOB = (
    "SELECT id, session_id, owner_id, kind, name, slack_webhook_url, agent_name, "
    "instructions, databricks_job_id, schedule_id "
    "FROM clawhouse.fired_jobs WHERE databricks_job_id = $1"
)
_SELECT_FIRED_BY_SCHEDULE = (
    "SELECT id, session_id, owner_id, kind, name, slack_webhook_url, agent_name, "
    "instructions, databricks_job_id, schedule_id "
    "FROM clawhouse.fired_jobs WHERE schedule_id = $1"
)
_INSERT_DELIVERY_RUN = (
    "INSERT INTO clawhouse.deliveries "
    "(id, fired_job_id, databricks_job_id, run_id, event_type, sheet_status) "
    "VALUES ($1, $2, $3, $4, $5, $6) "
    "ON CONFLICT (databricks_job_id, run_id, event_type) DO NOTHING RETURNING id"
)
_INSERT_DELIVERY_SLOT = (
    "INSERT INTO clawhouse.deliveries "
    "(id, fired_job_id, schedule_id, next_run_at, sheet_status) "
    "VALUES ($1, $2, $3, $4, $5) "
    "ON CONFLICT (schedule_id, next_run_at) DO NOTHING RETURNING id"
)
_DELETE_DELIVERY_RUN = (
    "DELETE FROM clawhouse.deliveries "
    "WHERE databricks_job_id = $1 AND run_id = $2 AND event_type = $3"
)
_SELECT_DELIVERY_RUN = (
    "SELECT id, fired_job_id, databricks_job_id, run_id, event_type, schedule_id, "
    "next_run_at, sheet_status FROM clawhouse.deliveries "
    "WHERE databricks_job_id = $1 AND run_id = $2 AND event_type = $3"
)
