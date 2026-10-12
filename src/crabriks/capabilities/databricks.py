"""Databricks Unity Catalog exploration, SQL warehouse execution, and system.ai capabilities."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.serving import ChatMessage, ChatMessageRole
from pydantic_ai import RunContext
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.toolsets import AbstractToolset, AgentToolset, FunctionToolset
from pydantic_ai.toolsets.approval_required import ApprovalRequiredToolset

logger = logging.getLogger("crabriks.databricks")

_SQL_COMMENT_PATTERN = re.compile(r"(--[^\n]*|\/\*[\s\S]*?\*\/)")
_MUTATING_KEYWORDS = {
    "insert",
    "update",
    "delete",
    "merge",
    "drop",
    "create",
    "alter",
    "truncate",
    "grant",
    "revoke",
    "optimize",
    "vacuum",
}
_READONLY_KEYWORDS = {"select", "show", "describe", "desc", "explain"}


@dataclass(frozen=True, slots=True)
class ColumnDef:
    name: str
    type_name: str
    comment: str | None = None


@dataclass(frozen=True, slots=True)
class TableMetadata:
    catalog: str
    schema: str
    name: str
    columns: tuple[ColumnDef, ...]
    comment: str | None = None


@dataclass(frozen=True, slots=True)
class QueryResult:
    columns: tuple[str, ...]
    rows: tuple[tuple[object, ...], ...]
    row_count: int
    truncated: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "columns": list(self.columns),
            "rows": [list(row) for row in self.rows],
            "row_count": self.row_count,
            "truncated": self.truncated,
        }


def strip_sql_comments(sql: str) -> str:
    return _SQL_COMMENT_PATTERN.sub(" ", sql).strip()


def is_readonly_query(sql: str) -> bool:
    cleaned = strip_sql_comments(sql)
    tokens = [t.lower() for t in re.split(r"\s+", cleaned) if t]
    if not tokens or tokens[0] in _MUTATING_KEYWORDS:
        return False

    first_word = tokens[0]
    if first_word == "with":
        has_mutation = any(t in _MUTATING_KEYWORDS for t in tokens)
        return not has_mutation and ("select" in tokens)

    return first_word in _READONLY_KEYWORDS


def enforce_query_limit(sql: str, default_limit: int = 100) -> str:
    if not is_readonly_query(sql):
        return sql
    if re.search(r"\blimit\s+\d+", sql, re.IGNORECASE):
        return sql
    return f"{sql.strip()}\nLIMIT {default_limit}"


def resolve_warehouse_id(client: WorkspaceClient, configured_id: str | None) -> str | None:
    if configured_id:
        return configured_id
    try:
        warehouses = list(client.warehouses.list())
        for wh in warehouses:
            state = getattr(wh, "state", None)
            val = getattr(state, "value", str(state)) if state else ""
            if val.upper() == "RUNNING" and wh.id:
                return wh.id
        if warehouses and warehouses[0].id:
            return warehouses[0].id
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to auto-discover Databricks SQL warehouse: %s", exc)
    return None


class DatabricksTools:
    """Methods exposed as agent tools for Unity Catalog and SQL execution."""

    def __init__(self, client: WorkspaceClient, warehouse_id: str | None) -> None:
        self.client = client
        self.warehouse_id = warehouse_id

    async def uc_list_catalogs(self) -> list[str]:
        """List available Unity Catalog catalogs."""
        try:
            return [c.name for c in self.client.catalogs.list() if c.name]
        except Exception as exc:  # noqa: BLE001
            logger.warning("uc_list_catalogs failed: %s", exc)
            return []

    async def uc_list_schemas(self, catalog_name: str) -> list[str]:
        """List schemas within a specific Unity Catalog catalog."""
        try:
            return [s.name for s in self.client.schemas.list(catalog_name=catalog_name) if s.name]
        except Exception as exc:  # noqa: BLE001
            logger.warning("uc_list_schemas failed: %s", exc)
            return []

    async def uc_list_tables(self, catalog_name: str, schema_name: str) -> list[str]:
        """List tables within a Unity Catalog schema."""
        try:
            return [
                t.name
                for t in self.client.tables.list(catalog_name=catalog_name, schema_name=schema_name)
                if t.name
            ]
        except Exception as exc:  # noqa: BLE001
            logger.warning("uc_list_tables failed: %s", exc)
            return []

    async def uc_describe_table(self, full_name: str) -> dict[str, object]:
        """Describe schema and column definitions of a Unity Catalog table."""
        try:
            info = self.client.tables.get(full_name=full_name)
            cols = [
                {
                    "name": col.name,
                    "type": getattr(col, "type_text", getattr(col, "type_name", "UNKNOWN")),
                    "comment": getattr(col, "comment", None),
                }
                for col in (getattr(info, "columns", None) or [])
            ]
            return {
                "name": full_name,
                "columns": cols,
                "comment": getattr(info, "comment", None),
            }
        except Exception as exc:  # noqa: BLE001
            return {"error": f"Failed to describe table {full_name}: {exc}"}

    async def dbsql_query(self, query: str, max_rows: int = 100) -> dict[str, object]:
        """Execute a SQL query on a Databricks SQL Warehouse."""
        if not self.warehouse_id:
            return {"error": "No Databricks SQL Warehouse available to execute queries."}

        effective_sql = enforce_query_limit(query, default_limit=max_rows)
        try:
            resp = self.client.statement_execution.execute_statement(
                statement=effective_sql,
                warehouse_id=self.warehouse_id,
                wait_timeout="30s",
                row_limit=max_rows,
            )
            columns: list[str] = []
            if resp.manifest and resp.manifest.schema and resp.manifest.schema.columns:
                columns = [c.name for c in resp.manifest.schema.columns if c.name]
            rows: list[list[Any]] = []
            if resp.result and resp.result.data_array:
                rows = [list(r) for r in resp.result.data_array]
            return {
                "columns": columns,
                "rows": rows,
                "row_count": len(rows),
                "query": effective_sql,
                "status": getattr(resp.status.state, "value", str(resp.status.state))
                if resp.status
                else "SUCCEEDED",
            }
        except Exception as exc:  # noqa: BLE001
            return {"error": f"SQL execution failed: {exc}", "query": effective_sql}

    async def system_ai_query(self, prompt: str, endpoint: str | None = None) -> str:
        """Invoke Databricks AI functions or foundation models."""
        target_endpoint = endpoint or "databricks-meta-llama-3-3-70b-instruct"
        try:
            resp = self.client.serving_endpoints.query(
                name=target_endpoint,
                messages=[ChatMessage(role=ChatMessageRole.USER, content=prompt)],
            )
            choices = getattr(resp, "choices", [])
            if choices:
                return getattr(choices[0].message, "content", str(choices[0]))
            return str(resp)
        except Exception as exc:  # noqa: BLE001
            return f"system_ai_query failed: {exc}"

    def all_tools(self) -> list[Callable[..., Any]]:
        return [
            self.uc_list_catalogs,
            self.uc_list_schemas,
            self.uc_list_tables,
            self.uc_describe_table,
            self.dbsql_query,
            self.system_ai_query,
        ]


@dataclass
class DatabricksCapability(AbstractCapability[Any]):
    """Provides Unity Catalog discovery, DBSQL query execution, and system.ai tools."""

    client_factory: Callable[[str], WorkspaceClient] = field(
        default_factory=lambda: lambda token: WorkspaceClient(token=token)
    )
    warehouse_id: str | None = None
    user_token: str = ""
    id: str | None = "databricks"

    def get_toolset(self) -> AgentToolset[Any] | None:
        client = self.client_factory(self.user_token)
        warehouse_id = resolve_warehouse_id(client, self.warehouse_id)
        impl = DatabricksTools(client, warehouse_id)
        return FunctionToolset(impl.all_tools())

    def get_wrapper_toolset(self, toolset: AbstractToolset[Any]) -> AbstractToolset[Any]:
        def approval_required(
            _ctx: RunContext[Any],
            tool_def: ToolDefinition,
            args: dict[str, Any],
        ) -> bool:
            if tool_def.name == "dbsql_query":
                sql = str(args.get("query", ""))
                return not is_readonly_query(sql)
            return False

        return ApprovalRequiredToolset(toolset, approval_required_func=approval_required)
