"""Databricks Unity Catalog exploration, SQL warehouse execution, and system.ai capabilities."""

from __future__ import annotations

import base64
import itertools
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.jobs import JobSettings, SparkPythonTask, SqlTask, SqlTaskFile, Task
from databricks.sdk.service.serving import ChatMessage, ChatMessageRole
from databricks.sdk.service.workspace import ImportFormat, Language
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
# Lakeflow tools that change workspace state; each one waits for human approval.
_JOBS_PAGE_MAX = 100  # the Jobs API rejects a page limit above 100
_TASK_KEY_UNSAFE = re.compile(r"[^A-Za-z0-9_-]+")
_APPROVAL_REQUIRED_TOOLS = frozenset(
    {"jobs_run_now", "jobs_cancel_run", "jobs_create", "jobs_edit"}
)


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


def _enum_value(value: Any) -> str | None:
    if value is None:
        return None
    return str(getattr(value, "value", value))


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

    def _fallback_client(self) -> WorkspaceClient | None:
        try:
            return WorkspaceClient()
        except Exception:  # noqa: BLE001
            return None

    async def uc_list_catalogs(self) -> list[str]:
        """List available Unity Catalog catalogs."""
        try:
            return [c.name for c in self.client.catalogs.list() if c.name]
        except Exception as exc:  # noqa: BLE001
            logger.warning("uc_list_catalogs failed with client: %s; trying ambient client", exc)
            fallback = self._fallback_client()
            if fallback is not None:
                try:
                    return [c.name for c in fallback.catalogs.list() if c.name]
                except Exception as inner_exc:  # noqa: BLE001
                    logger.warning("uc_list_catalogs fallback failed: %s", inner_exc)
            return []

    async def uc_list_schemas(self, catalog_name: str) -> list[str]:
        """List schemas within a specific Unity Catalog catalog."""
        try:
            return [s.name for s in self.client.schemas.list(catalog_name=catalog_name) if s.name]
        except Exception as exc:  # noqa: BLE001
            logger.warning("uc_list_schemas failed with client: %s; trying ambient client", exc)
            fallback = self._fallback_client()
            if fallback is not None:
                try:
                    return [
                        s.name for s in fallback.schemas.list(catalog_name=catalog_name) if s.name
                    ]
                except Exception as inner_exc:  # noqa: BLE001
                    logger.warning("uc_list_schemas fallback failed: %s", inner_exc)
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
            logger.warning("uc_list_tables failed with client: %s; trying ambient client", exc)
            fallback = self._fallback_client()
            if fallback is not None:
                try:
                    return [
                        t.name
                        for t in fallback.tables.list(
                            catalog_name=catalog_name, schema_name=schema_name
                        )
                        if t.name
                    ]
                except Exception as inner_exc:  # noqa: BLE001
                    logger.warning("uc_list_tables fallback failed: %s", inner_exc)
            return []

    async def uc_describe_table(self, full_name: str) -> dict[str, object]:
        """Describe schema and column definitions of a Unity Catalog table."""
        try:
            info = self.client.tables.get(full_name=full_name)
        except Exception as exc:  # noqa: BLE001
            logger.warning("uc_describe_table failed with client: %s; trying ambient client", exc)
            fallback = self._fallback_client()
            if fallback is not None:
                try:
                    info = fallback.tables.get(full_name=full_name)
                except Exception as inner_exc:  # noqa: BLE001
                    return {"error": f"Failed to describe table {full_name}: {inner_exc}"}
            else:
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

    async def jobs_list(self, limit: int = 25) -> dict[str, object]:
        """List Lakeflow jobs in the workspace."""
        limit = max(1, min(limit, _JOBS_PAGE_MAX))
        try:
            jobs = list(itertools.islice(self.client.jobs.list(limit=limit), limit))
        except Exception as exc:  # noqa: BLE001
            return {"error": f"Failed to list jobs: {exc}"}
        return {
            "jobs": [
                {
                    "job_id": job.job_id,
                    "name": job.settings.name if job.settings else None,
                    "creator": job.creator_user_name,
                }
                for job in jobs
            ],
            "job_count": len(jobs),
        }

    async def jobs_run_now(
        self, job_id: int, parameters: dict[str, str] | None = None
    ) -> dict[str, object]:
        """Trigger an immediate run of a Lakeflow job, optionally overriding job parameters."""
        try:
            wait = self.client.jobs.run_now(job_id=job_id, job_parameters=parameters)
        except Exception as exc:  # noqa: BLE001
            return {"error": f"Failed to run job {job_id}: {exc}"}
        return {"run_id": wait.run_id, "job_id": job_id}

    async def jobs_create(  # noqa: PLR0913
        self,
        name: str,
        task_type: Literal["python", "sql"],
        path: str = "",
        *,
        parameters: list[str] | None = None,
        warehouse_id: str | None = None,
        query: str | None = None,
    ) -> dict[str, object]:
        """Create a single-task Lakeflow job that runs a Python script or a SQL file/query.

        For `python`, `path` is a workspace file path.
        For `sql`, provide `path` to a `.sql` file, or provide `query` with the SQL statement
        which is automatically saved into a workspace SQL file.
        """
        task_key = _TASK_KEY_UNSAFE.sub("_", name)
        if task_type == "python":
            task = Task(
                task_key=task_key,
                spark_python_task=SparkPythonTask(python_file=path, parameters=parameters),
            )
        else:
            sql_warehouse = warehouse_id or self.warehouse_id
            if not sql_warehouse:
                return {"error": "A SQL job needs a SQL warehouse; none is available."}
            effective_path = path
            sql_text = query or (
                path if path and not path.endswith(".sql") and "select" in path.lower() else None
            )
            if sql_text:
                effective_path = f"/Workspace/Shared/crabriks/{task_key}.sql"
                try:
                    b64_content = base64.b64encode(sql_text.encode("utf-8")).decode("utf-8")
                    self.client.workspace.import_(
                        path=effective_path,
                        content=b64_content,
                        format=ImportFormat.SOURCE,
                        language=Language.SQL,
                        overwrite=True,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Failed to auto-import SQL file to workspace: %s", exc)
            elif not effective_path:
                return {"error": "A SQL job requires either a workspace file path or a SQL query."}
            task = Task(
                task_key=task_key,
                sql_task=SqlTask(warehouse_id=sql_warehouse, file=SqlTaskFile(path=effective_path)),
            )
        try:
            created = self.client.jobs.create(name=name, tasks=[task])
        except Exception as exc:  # noqa: BLE001
            return {"error": f"Failed to create job {name}: {exc}"}
        return {"job_id": created.job_id, "name": name}

    async def jobs_edit(self, job_id: int, new_settings: dict[str, Any]) -> dict[str, object]:
        """Update a Lakeflow job. `new_settings` holds the top-level job settings to change."""
        try:
            self.client.jobs.update(job_id=job_id, new_settings=JobSettings.from_dict(new_settings))
        except Exception as exc:  # noqa: BLE001
            return {"error": f"Failed to update job {job_id}: {exc}"}
        return {"job_id": job_id, "updated": True}

    async def jobs_cancel_run(self, run_id: int) -> dict[str, object]:
        """Request cancellation of an active Lakeflow job run."""
        try:
            self.client.jobs.cancel_run(run_id=run_id)
        except Exception as exc:  # noqa: BLE001
            return {"error": f"Failed to cancel run {run_id}: {exc}"}
        return {"run_id": run_id, "cancel_requested": True}

    async def jobs_get_run(self, run_id: int) -> dict[str, object]:
        """Get the state of a Lakeflow job run."""
        try:
            run = self.client.jobs.get_run(run_id=run_id)
        except Exception as exc:  # noqa: BLE001
            return {"error": f"Failed to get run {run_id}: {exc}"}
        state = run.state
        duration = run.end_time - run.start_time if run.start_time and run.end_time else None
        return {
            "run_id": run.run_id,
            "job_id": run.job_id,
            "life_cycle_state": _enum_value(state.life_cycle_state if state else None),
            "result_state": _enum_value(state.result_state if state else None),
            "state_message": state.state_message if state else None,
            "duration_ms": duration,
            "url": run.run_page_url,
            "tasks": [
                {
                    "task_key": task.task_key,
                    "life_cycle_state": _enum_value(
                        task.state.life_cycle_state if task.state else None
                    ),
                    "result_state": _enum_value(task.state.result_state if task.state else None),
                }
                for task in run.tasks or []
            ],
        }

    def all_tools(self) -> list[Callable[..., Any]]:
        return [
            self.uc_list_catalogs,
            self.uc_list_schemas,
            self.uc_list_tables,
            self.uc_describe_table,
            self.dbsql_query,
            self.system_ai_query,
            self.jobs_list,
            self.jobs_get_run,
            self.jobs_run_now,
            self.jobs_cancel_run,
            self.jobs_create,
            self.jobs_edit,
        ]


def default_workspace_client(token: str = "") -> WorkspaceClient:
    """Create a Databricks WorkspaceClient.

    If a user token is provided, explicitly uses `auth_type='pat'` so it does not conflict
    with ambient OAuth service-principal environment variables in Databricks Apps.
    Falls back to ambient authentication if token authentication is not configured
    or fails.
    """
    if token:
        try:
            return WorkspaceClient(token=token, auth_type="pat")
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "WorkspaceClient with user token failed: %s; falling back to ambient auth", exc
            )
    return WorkspaceClient()


@dataclass
class DatabricksCapability(AbstractCapability[Any]):
    """Provides Unity Catalog discovery, DBSQL query execution, and system.ai tools."""

    client_factory: Callable[[str], WorkspaceClient] = field(
        default_factory=lambda: default_workspace_client
    )
    warehouse_id: str | None = None
    user_token: str = ""
    id: str | None = "databricks"

    def get_toolset(self) -> AgentToolset[Any] | None:
        try:
            client = self.client_factory(self.user_token)
            warehouse_id = resolve_warehouse_id(client, self.warehouse_id)
            impl = DatabricksTools(client, warehouse_id)
            return FunctionToolset(impl.all_tools())
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "DatabricksCapability failed with user client: %s; trying ambient client", exc
            )
            try:
                ambient = WorkspaceClient()
                warehouse_id = resolve_warehouse_id(ambient, self.warehouse_id)
                impl = DatabricksTools(ambient, warehouse_id)
                return FunctionToolset(impl.all_tools())
            except Exception as inner_exc:  # noqa: BLE001
                logger.warning("DatabricksCapability ambient fallback also failed: %s", inner_exc)
                return None

    def get_wrapper_toolset(self, toolset: AbstractToolset[Any]) -> AbstractToolset[Any]:
        def approval_required(
            _ctx: RunContext[Any],
            tool_def: ToolDefinition,
            args: dict[str, Any],
        ) -> bool:
            if tool_def.name == "dbsql_query":
                sql = str(args.get("query", ""))
                return not is_readonly_query(sql)
            return tool_def.name in _APPROVAL_REQUIRED_TOOLS

        return ApprovalRequiredToolset(toolset, approval_required_func=approval_required)
