"""Databricks SQL warehouse resolution, execution, and system.ai capabilities."""

from __future__ import annotations

import logging
import os
import sys
from typing import TYPE_CHECKING, Any

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.serving import ChatMessage, ChatMessageRole

from clawhouse.capabilities.databricks.sql_util import enforce_query_limit

if TYPE_CHECKING:
    from clawhouse.capabilities.databricks.tools import DatabricksTools

logger = logging.getLogger("clawhouse.databricks")


def _workspace_client_cls() -> type[WorkspaceClient]:
    mod = sys.modules.get("clawhouse.capabilities.databricks")
    if mod and hasattr(mod, "WorkspaceClient"):
        return mod.WorkspaceClient
    return WorkspaceClient


def _find_running_or_first(warehouses: list[Any]) -> str | None:
    for wh in warehouses:
        state = getattr(wh, "state", None)
        val = getattr(state, "value", str(state)) if state else ""
        if val.upper() == "RUNNING" and wh.id:
            return wh.id
    if warehouses and warehouses[0].id:
        return warehouses[0].id
    return None


def _list_warehouses(client: WorkspaceClient) -> list[Any] | None:
    try:
        return list(client.warehouses.list())
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to list Databricks SQL warehouses: %s", exc)
        return None


def resolve_warehouse_id(client: WorkspaceClient, configured_id: str | None) -> str | None:
    if configured_id:
        return configured_id
    env_id = os.environ.get("DATABRICKS_WAREHOUSE_ID") or os.environ.get("SQL_WAREHOUSE_ID")
    if env_id:
        return env_id
    warehouses = _list_warehouses(client)
    if warehouses is None:
        try:
            warehouses = _list_warehouses(_workspace_client_cls()())
        except Exception:  # noqa: BLE001
            return None
    if not warehouses:
        return None
    return _find_running_or_first(warehouses)


def _extract_columns(resp: Any) -> list[str]:
    manifest = getattr(resp, "manifest", None)
    schema = getattr(manifest, "schema", None)
    columns = getattr(schema, "columns", None) or []
    return [c.name for c in columns if getattr(c, "name", None)]


def _extract_rows(resp: Any) -> list[list[Any]]:
    result = getattr(resp, "result", None)
    data = getattr(result, "data_array", None) or []
    return [list(r) for r in data]


def _statement_status(resp: Any) -> str:
    status = getattr(resp, "status", None)
    if status is None:
        return "SUCCEEDED"
    return str(getattr(status.state, "value", status.state))


def _format_statement_result(resp: Any, query: str) -> dict[str, object]:
    rows = _extract_rows(resp)
    return {
        "columns": _extract_columns(resp),
        "rows": rows,
        "row_count": len(rows),
        "query": query,
        "status": _statement_status(resp),
    }


async def dbsql_query(tools: DatabricksTools, query: str, max_rows: int = 100) -> dict[str, object]:
    """Execute a SQL query on a Databricks SQL Warehouse."""
    wh_id = tools.effective_warehouse_id
    if not wh_id:
        return {"error": "No Databricks SQL Warehouse available to execute queries."}

    effective_sql = enforce_query_limit(query, default_limit=max_rows)
    try:
        resp = tools._call(
            lambda cl: cl.statement_execution.execute_statement(
                statement=effective_sql,
                warehouse_id=wh_id,
                wait_timeout="30s",
                row_limit=max_rows,
            )
        )
        return _format_statement_result(resp, effective_sql)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"SQL execution failed: {exc}", "query": effective_sql}


async def system_ai_query(tools: DatabricksTools, prompt: str, endpoint: str | None = None) -> str:
    """Invoke Databricks AI functions or foundation models."""
    target_endpoint = endpoint or "databricks-meta-llama-3-3-70b-instruct"
    try:
        resp = tools._call(
            lambda cl: cl.serving_endpoints.query(
                name=target_endpoint,
                messages=[ChatMessage(role=ChatMessageRole.USER, content=prompt)],
            )
        )
        choices = getattr(resp, "choices", [])
        if choices:
            return getattr(choices[0].message, "content", str(choices[0]))
        return str(resp)
    except Exception as exc:  # noqa: BLE001
        return f"system_ai_query failed: {exc}"
