"""Unity Catalog exploration, permissions, and data lineage capabilities."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from databricks.sdk.errors import PermissionDenied
from databricks.sdk.service.sql import StatementParameterListItem

if TYPE_CHECKING:
    from clawhouse.capabilities.databricks.tools import DatabricksTools

logger = logging.getLogger("clawhouse.databricks")

_LINEAGE_CAP = 50


def _hidden_or_error(exc: Exception, fallback: str) -> dict[str, object]:
    if isinstance(exc, PermissionDenied) or "permission" in str(exc).lower():
        return {"error": "not visible to you"}
    return {"error": fallback}


def _estate_closed(tools: DatabricksTools) -> dict[str, object] | None:
    if not tools.user_token.strip():
        return {"error": "not visible to you"}
    return None


def _lineage_statement(
    full_name: str, column: str | None
) -> tuple[str, list[StatementParameterListItem]]:
    params = [StatementParameterListItem(name="fqn", type="STRING", value=full_name)]
    if column is None:
        statement = (
            "SELECT source_table_full_name, target_table_full_name, event_time "
            "FROM system.access.table_lineage "
            "WHERE source_table_full_name = :fqn OR target_table_full_name = :fqn"
        )
        return statement, params
    params.append(StatementParameterListItem(name="column", type="STRING", value=column))
    statement = (
        "SELECT source_table_full_name, source_column_name, "
        "target_table_full_name, target_column_name, event_time "
        "FROM system.access.column_lineage "
        "WHERE (source_table_full_name = :fqn AND source_column_name = :column) "
        "OR (target_table_full_name = :fqn AND target_column_name = :column)"
    )
    return statement, params


def _statement_rows(resp: object) -> list[dict[str, str]]:
    manifest = getattr(resp, "manifest", None)
    schema = getattr(manifest, "schema", None)
    columns = [c.name for c in (getattr(schema, "columns", None) or []) if getattr(c, "name", None)]
    data = getattr(getattr(resp, "result", None), "data_array", None) or []
    rows: list[dict[str, str]] = []
    for raw in data:
        values = list(raw)
        rows.append({columns[i]: str(values[i]) for i in range(min(len(columns), len(values)))})
    return rows


def _lineage_payload(
    full_name: str, rows: list[dict[str, str]], *, column: str | None
) -> dict[str, object]:
    if not rows:
        return {"table": full_name, "upstream": [], "downstream": [], "note": "no lineage found"}
    upstream: dict[str, str] = {}
    downstream: dict[str, str] = {}
    for row in rows:
        seen = row.get("event_time", "")
        if column is None:
            _keep_newer(upstream, row.get("source_table_full_name"), seen, full_name)
            _keep_newer(downstream, row.get("target_table_full_name"), seen, full_name)
            continue
        _keep_column(upstream, row, ("source_table_full_name", "source_column_name", full_name))
        _keep_column(downstream, row, ("target_table_full_name", "target_column_name", full_name))
    return {
        "table": full_name,
        "upstream": _cap_direction(upstream, column=column),
        "downstream": _cap_direction(downstream, column=column),
    }


def _keep_newer(bucket: dict[str, str], table: str | None, seen: str, self_name: str) -> None:
    if not table or table == self_name:
        return
    if table not in bucket or seen > bucket[table]:
        bucket[table] = seen


def _keep_column(bucket: dict[str, str], row: dict[str, str], keys: tuple[str, str, str]) -> None:
    table_key, column_key, self_name = keys
    seen = row.get("event_time", "")
    table = row.get(table_key)
    column = row.get(column_key)
    if not table or not column or table == self_name:
        return
    key = f"{table}\t{column}"
    if key not in bucket or seen > bucket[key]:
        bucket[key] = seen


def _cap_direction(bucket: dict[str, str], *, column: str | None) -> list[dict[str, str]]:
    ranked = sorted(bucket.items(), key=lambda item: item[1], reverse=True)[:_LINEAGE_CAP]
    if column is None:
        return [{"table": table, "last_seen": seen} for table, seen in ranked]
    out = []
    for key, seen in ranked:
        table, col = key.split("\t", 1)
        out.append({"table": table, "column": col, "last_seen": seen})
    return out


async def uc_list_catalogs(tools: DatabricksTools) -> list[str]:
    """List available Unity Catalog catalogs."""
    try:
        return tools._call(lambda cl: [c.name for c in cl.catalogs.list() if c.name])
    except Exception as exc:  # noqa: BLE001
        logger.warning("uc_list_catalogs failed: %s", exc)
        return []


async def uc_list_schemas(tools: DatabricksTools, catalog_name: str) -> list[str]:
    """List schemas within a specific Unity Catalog catalog."""
    try:
        return tools._call(
            lambda cl: [s.name for s in cl.schemas.list(catalog_name=catalog_name) if s.name]
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("uc_list_schemas failed: %s", exc)
        return []


async def uc_list_tables(tools: DatabricksTools, catalog_name: str, schema_name: str) -> list[str]:
    """List tables within a Unity Catalog schema."""
    try:
        return tools._call(
            lambda cl: [
                t.name
                for t in cl.tables.list(catalog_name=catalog_name, schema_name=schema_name)
                if t.name
            ]
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("uc_list_tables failed: %s", exc)
        return []


async def uc_describe_table(tools: DatabricksTools, full_name: str) -> dict[str, object]:
    """Describe schema and column definitions of a Unity Catalog table."""
    try:
        info = tools._call(lambda cl: cl.tables.get(full_name=full_name))
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Failed to describe table {full_name}: {exc}"}
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


async def uc_list_grants(tools: DatabricksTools, full_name: str) -> dict[str, object]:
    """Effective table grants for the caller. Never uses the ambient client."""
    closed = _estate_closed(tools)
    if closed is not None:
        return closed
    if len(full_name.split(".")) != 3 or any(part == "" for part in full_name.split(".")):
        return {"error": "full_name must be catalog.schema.table"}
    try:
        listed = tools.client.grants.get_effective(securable_type="table", full_name=full_name)
    except Exception as exc:  # noqa: BLE001
        return _hidden_or_error(exc, f"Failed to read grants for {full_name}: {exc}")
    grants = []
    for assignment in listed.privilege_assignments or []:
        for privilege in assignment.privileges or []:
            name = getattr(privilege.privilege, "value", privilege.privilege)
            grants.append(
                {
                    "principal": assignment.principal,
                    "privilege": name,
                    "inherited": bool(
                        privilege.inherited_from_name or privilege.inherited_from_type
                    ),
                }
            )
    return {"full_name": full_name, "grants": grants}


async def _lineage(
    tools: DatabricksTools, full_name: str, *, column: str | None
) -> dict[str, object]:
    closed = _estate_closed(tools)
    if closed is not None:
        return closed
    if not tools.warehouse_id:
        return {"error": "No Databricks SQL Warehouse available to execute queries."}
    statement, parameters = _lineage_statement(full_name, column)
    try:
        resp = tools.client.statement_execution.execute_statement(
            statement=statement,
            warehouse_id=tools.warehouse_id,
            parameters=parameters,
            wait_timeout="30s",
        )
    except Exception as exc:  # noqa: BLE001
        return _hidden_or_error(exc, f"Lineage query failed: {exc}")
    return _lineage_payload(full_name, _statement_rows(resp), column=column)


async def uc_table_lineage(tools: DatabricksTools, full_name: str) -> dict[str, object]:
    """Upstream and downstream tables from system.access.table_lineage."""
    return await _lineage(tools, full_name, column=None)


async def uc_column_lineage(
    tools: DatabricksTools, full_name: str, column: str
) -> dict[str, object]:
    """Upstream and downstream columns from system.access.column_lineage."""
    return await _lineage(tools, full_name, column=column)
