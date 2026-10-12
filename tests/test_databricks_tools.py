"""Tests for Databricks Unity Catalog exploration, system.ai, and DBSQL tools."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel

from crabriks.agent.turn import (
    TurnContext,
    run_turn,
)
from crabriks.capabilities.databricks import (
    DatabricksCapability,
    enforce_query_limit,
    is_readonly_query,
    resolve_warehouse_id,
)
from crabriks.store.store import MemorySessionStore


def test_is_readonly_query() -> None:
    assert is_readonly_query("SELECT * FROM my_table") is True
    assert is_readonly_query("  /* comment */ select 1") is True
    assert is_readonly_query("-- comment\nSELECT a, b FROM c") is True
    assert is_readonly_query("WITH c AS (SELECT 1) SELECT * FROM c") is True
    assert is_readonly_query("SHOW TABLES IN default") is True
    assert is_readonly_query("DESCRIBE TABLE my_cat.my_schema.my_tab") is True
    assert is_readonly_query("DESC my_table") is True
    assert is_readonly_query("EXPLAIN SELECT 1") is True

    assert is_readonly_query("DROP TABLE my_table") is False
    assert is_readonly_query("DELETE FROM my_table WHERE id = 1") is False
    assert is_readonly_query("INSERT INTO my_table VALUES (1)") is False
    assert is_readonly_query("UPDATE my_table SET a = 1") is False
    assert is_readonly_query("CREATE TABLE foo AS SELECT 1") is False
    assert is_readonly_query("TRUNCATE TABLE foo") is False
    assert is_readonly_query("ALTER TABLE foo ADD COLUMN bar string") is False
    merge_sql = "MERGE INTO target USING source ON a = b WHEN MATCHED THEN UPDATE SET *"
    assert is_readonly_query(merge_sql) is False


def test_enforce_query_limit() -> None:
    assert enforce_query_limit("SELECT * FROM t", 100) == "SELECT * FROM t\nLIMIT 100"
    assert enforce_query_limit("SELECT * FROM t LIMIT 10", 100) == "SELECT * FROM t LIMIT 10"
    assert enforce_query_limit("DROP TABLE t", 100) == "DROP TABLE t"


def test_resolve_warehouse_id() -> None:
    mock_client = MagicMock()
    # Explicitly configured warehouse wins
    assert resolve_warehouse_id(mock_client, "explicit-wh-123") == "explicit-wh-123"

    # Auto-discover first running warehouse
    wh1 = MagicMock(id="wh-stopped", state=MagicMock(value="STOPPED"))
    wh2 = MagicMock(id="wh-running", state=MagicMock(value="RUNNING"))
    mock_client.warehouses.list.return_value = [wh1, wh2]

    assert resolve_warehouse_id(mock_client, None) == "wh-running"


@dataclass
class _FakeColumn:
    name: str
    type_text: str
    comment: str | None = None


@dataclass
class _FakeTable:
    name: str
    columns: list[_FakeColumn]
    comment: str | None = None


def test_databricks_capability_metadata_tools() -> None:
    mock_client = MagicMock()
    cat_mock = MagicMock(name="main")
    cat_mock.name = "main"
    mock_client.catalogs.list.return_value = [cat_mock]

    schema_mock = MagicMock()
    schema_mock.name = "default"
    mock_client.schemas.list.return_value = [schema_mock]

    tab_mock = MagicMock()
    tab_mock.name = "users"
    mock_client.tables.list.return_value = [tab_mock]

    cols = [
        _FakeColumn(name="id", type_text="INT"),
        _FakeColumn(name="name", type_text="STRING"),
    ]
    mock_client.tables.get.return_value = _FakeTable(
        name="users",
        columns=cols,
        comment="User accounts table",
    )

    cap = DatabricksCapability(client_factory=lambda token: mock_client, warehouse_id="wh-1")
    toolset = cap.get_toolset()
    assert toolset is not None


@pytest.mark.asyncio
async def test_dbsql_query_read_vs_mutation_approval() -> None:
    store = MemorySessionStore()

    def now() -> datetime:
        return datetime(2026, 10, 11, 12, 0, 0, tzinfo=UTC)

    mock_client = MagicMock()
    manifest_col1 = MagicMock(name="id")
    manifest_col1.name = "id"
    manifest_col2 = MagicMock(name="val")
    manifest_col2.name = "val"

    stmt_resp = MagicMock()
    stmt_resp.manifest.schema.columns = [manifest_col1, manifest_col2]
    stmt_resp.result.data_array = [["1", "alpha"], ["2", "beta"]]
    stmt_resp.status.state = MagicMock(value="SUCCEEDED")
    mock_client.statement_execution.execute_statement.return_value = stmt_resp

    cap = DatabricksCapability(client_factory=lambda token: mock_client, warehouse_id="wh-1")

    # 1. Read-only SELECT query should NOT require approval
    async def call_read(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        del info
        returned = any(
            getattr(part, "part_kind", "") == "tool-return" for m in messages for part in m.parts
        )
        if not returned:
            yield {
                0: DeltaToolCall(
                    name="dbsql_query",
                    json_args='{"query": "SELECT * FROM users"}',
                    tool_call_id="call-read-1",
                )
            }
            return
        yield "Here are the users."

    session_id = "00000000-0000-4000-8000-000000000001"
    ctx_read = TurnContext(
        owner_id="user-1",
        store=store,
        model=FunctionModel(stream_function=call_read),
        now=now,
        user_token="test-token",
        databricks_capability=cap,
    )

    result_read = await run_turn(session_id, "Show users", ctx=ctx_read)
    assert result_read.status == "ok"
    assert len(result_read.transcript) > 0

    # 2. Mutating query DROP TABLE should require approval
    async def call_mutate(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        del messages, info
        yield {
            0: DeltaToolCall(
                name="dbsql_query",
                json_args='{"query": "DROP TABLE users"}',
                tool_call_id="call-mut-1",
            )
        }

    session_id_2 = "00000000-0000-4000-8000-000000000002"
    ctx_mutate = TurnContext(
        owner_id="user-1",
        store=store,
        model=FunctionModel(stream_function=call_mutate),
        now=now,
        user_token="test-token",
        databricks_capability=cap,
    )

    result_mutate = await run_turn(session_id_2, "Delete users table", ctx=ctx_mutate)
    assert result_mutate.status == "pending_approval"
    assert result_mutate.approval_id is not None
