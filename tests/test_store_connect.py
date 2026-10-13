"""How a process decides to reach Lakebase. No network."""

import pytest

from crabriks.store import (
    SCHEMA,
    MemorySessionStore,
    MissingDatabaseCredential,
    PgConnect,
    UserProfile,
    connection_plan,
    open_store,
)

URL = "postgresql://postgres:postgres@localhost:5432/crabriks"
ENDPOINT = "projects/app/branches/production/endpoints/ep-1"


def test_a_postgres_url_is_used_as_the_connection_string() -> None:
    assert connection_plan({"DATABASE_URL": URL, "PGHOST": "ignored.example"}) == URL
    assert connection_plan({"DB_CONNECTION_STRING": URL}) == URL


def test_a_static_password_does_not_mint_a_token() -> None:
    plan = connection_plan(
        {
            "PGHOST": "localhost",
            "PGPORT": "5433",
            "PGUSER": "postgres",
            "PGDATABASE": "crabriks",
            "PGPASSWORD": "postgres",
            "LAKEBASE_ENDPOINT": ENDPOINT,
        }
    )
    assert plan == PgConnect(
        host="localhost",
        port=5433,
        user="postgres",
        database="crabriks",
        ssl=False,
        password="post" + "gres",
        endpoint=None,
    )


def test_an_endpoint_mints_an_oauth_password_over_tls() -> None:
    plan = connection_plan(
        {
            "PGHOST": "ep-1.database.cloud.databricks.com",
            "PGUSER": "6b215d2b-f099-4bdb-900a-60837201ecec",
            "PGDATABASE": "databricks_postgres",
            "PGSSLMODE": "require",
            "DB_CONNECTION_STRING": ENDPOINT,
            "ENDPOINT_NAME": ENDPOINT,
        }
    )
    assert plan == PgConnect(
        host="ep-1.database.cloud.databricks.com",
        port=5432,
        user="6b215d2b-f099-4bdb-900a-60837201ecec",
        database="databricks_postgres",
        ssl=True,
        password=None,
        endpoint=ENDPOINT,
    )


def test_oauth_uses_tls_unless_ssl_is_disabled() -> None:
    base = {
        "PGHOST": "ep-1.database.cloud.databricks.com",
        "PGUSER": "sp",
        "PGDATABASE": "databricks_postgres",
        "LAKEBASE_ENDPOINT": ENDPOINT,
    }
    implied = connection_plan(base)
    disabled = connection_plan({**base, "PGSSLMODE": "disable"})
    assert isinstance(implied, PgConnect)
    assert isinstance(disabled, PgConnect)
    assert implied.ssl is True
    assert disabled.ssl is False


def test_a_host_without_a_credential_is_refused() -> None:
    with pytest.raises(MissingDatabaseCredential):
        connection_plan(
            {
                "PGHOST": "ep-1.database.cloud.databricks.com",
                "PGUSER": "sp",
                "PGDATABASE": "databricks_postgres",
            }
        )


def test_lakebase_names_without_a_host_are_refused() -> None:
    with pytest.raises(MissingDatabaseCredential):
        connection_plan({"PGUSER": "sp", "LAKEBASE_ENDPOINT": ENDPOINT})


async def test_open_store_uses_memory_when_no_database_is_configured() -> None:
    store = await open_store({})
    assert isinstance(store, MemorySessionStore)


def test_tables_live_in_the_app_owned_schema() -> None:
    assert "CREATE SCHEMA IF NOT EXISTS crabriks;" in SCHEMA
    assert "CREATE TABLE IF NOT EXISTS crabriks.sessions" in SCHEMA
    assert "CREATE TABLE IF NOT EXISTS crabriks.runs" in SCHEMA
    assert "CREATE TABLE IF NOT EXISTS crabriks.transcript_entries" in SCHEMA
    assert "ON crabriks.runs (session_id)" in SCHEMA
    assert "CREATE TABLE IF NOT EXISTS crabriks.user_profiles" in SCHEMA


async def test_memory_session_store_user_profile() -> None:
    store = MemorySessionStore()
    assert await store.get_user_profile("ada@example.com") is None

    profile = UserProfile(
        user_id="ada@example.com",
        assistant_name="Jarvis",
        signature_emoji="🤖",
        user_directives="Data Engineer, be concise",
        hatched=True,
    )
    saved = await store.save_user_profile(profile)
    assert saved.user_id == "ada@example.com"
    assert saved.assistant_name == "Jarvis"
    assert saved.signature_emoji == "🤖"
    assert saved.user_directives == "Data Engineer, be concise"
    assert saved.hatched is True
    assert saved.created_at is not None
    assert saved.updated_at is not None

    retrieved = await store.get_user_profile("ada@example.com")
    assert retrieved == saved
