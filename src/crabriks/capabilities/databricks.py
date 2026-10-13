"""Databricks Unity Catalog exploration, SQL warehouse execution, and system.ai capabilities."""

from __future__ import annotations

import io
import itertools
import logging
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, TypeVar

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.jobs import (
    CronSchedule,
    JobSettings,
    PauseStatus,
    Source,
    SparkPythonTask,
    SqlTask,
    SqlTaskFile,
    Task,
)
from databricks.sdk.service.serving import ChatMessage, ChatMessageRole
from databricks.sdk.service.workspace import ImportFormat
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
    {"jobs_run_now", "jobs_cancel_run", "jobs_create", "jobs_edit", "jobs_delete"}
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


def to_quartz_cron(cron: str) -> str:
    """Convert standard 5-field cron or preserve 6/7-field Quartz cron."""
    tokens = cron.strip().split()
    if len(tokens) in (6, 7):
        return cron.strip()
    if len(tokens) == 5:
        m, h, dom, mon, dow = tokens
        if dow == "*":
            dow = "?"
        elif dom == "*":
            dom = "?"
        return f"0 {m} {h} {dom} {mon} {dow}"
    return cron.strip()


def build_cron_schedule(
    cron_expression: str | None,
    timezone_id: str = "UTC",
    pause_status: str | None = "UNPAUSED",
) -> CronSchedule | None:
    """Build a Databricks Job CronSchedule from a cron expression."""
    if not cron_expression:
        return None
    quartz = to_quartz_cron(cron_expression)
    status = (
        PauseStatus.PAUSED
        if pause_status and pause_status.upper() == "PAUSED"
        else PauseStatus.UNPAUSED
    )
    return CronSchedule(
        quartz_cron_expression=quartz,
        timezone_id=timezone_id,
        pause_status=status,
    )


def build_agentic_query(
    query: str,
    *,
    agent_name: str = "Agent",
    instructions: str | None = None,
    endpoint: str = "databricks-meta-llama-3-3-70b-instruct",
    sample_limit: int = 100,
) -> str:
    """Wrap a SQL query into an agentic DBSQL query using ai_query."""
    cleaned = strip_sql_comments(query).strip().rstrip(";")
    agent_clean = agent_name.lstrip("@").strip()
    prompt = f"You are @{agent_clean}."
    if instructions:
        prompt += f" {instructions.strip()}"
    else:
        prompt += " Analyze these query results and provide key insights, anomalies, and metrics."
    escaped = prompt.replace("'", "''")
    return (
        f"WITH source_query AS (\n"
        f"  {cleaned}\n"
        f"),\n"
        f"sample_data AS (\n"
        f"  SELECT * FROM source_query LIMIT {sample_limit}\n"
        f"),\n"
        f"encoded_summary AS (\n"
        f"  SELECT to_json(collect_list(struct(*))) AS data_json\n"
        f"  FROM sample_data\n"
        f")\n"
        f"SELECT ai_query(\n"
        f"  '{endpoint}',\n"
        f"  '{escaped}\\n\\nQuery Results:\\n' || data_json\n"
        f") AS agent_analysis\n"
        f"FROM encoded_summary"
    )


def _enum_value(value: Any) -> str | None:
    if value is None:
        return None
    return str(getattr(value, "value", value))


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
            warehouses = _list_warehouses(WorkspaceClient())
        except Exception:  # noqa: BLE001
            return None
    if not warehouses:
        return None
    return _find_running_or_first(warehouses)


_T = TypeVar("_T")


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

    @property
    def effective_warehouse_id(self) -> str | None:
        if self.warehouse_id:
            return self.warehouse_id
        try:
            wh = self._call(lambda cl: resolve_warehouse_id(cl, None))
            if wh:
                self.warehouse_id = wh
                return wh
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to lazily resolve warehouse id: %s", exc)
        return None

    def _call(self, fn: Callable[[WorkspaceClient], _T]) -> _T:
        try:
            return fn(self.client)
        except Exception as exc:
            fallback = self._fallback_client()
            if fallback is not None and fallback is not self.client:
                logger.info("Call on user client failed (%s); trying ambient client", exc)
                return fn(fallback)
            raise

    async def uc_list_catalogs(self) -> list[str]:
        """List available Unity Catalog catalogs."""
        try:
            return self._call(lambda cl: [c.name for c in cl.catalogs.list() if c.name])
        except Exception as exc:  # noqa: BLE001
            logger.warning("uc_list_catalogs failed: %s", exc)
            return []

    async def uc_list_schemas(self, catalog_name: str) -> list[str]:
        """List schemas within a specific Unity Catalog catalog."""
        try:
            return self._call(
                lambda cl: [s.name for s in cl.schemas.list(catalog_name=catalog_name) if s.name]
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("uc_list_schemas failed: %s", exc)
            return []

    async def uc_list_tables(self, catalog_name: str, schema_name: str) -> list[str]:
        """List tables within a Unity Catalog schema."""
        try:
            return self._call(
                lambda cl: [
                    t.name
                    for t in cl.tables.list(catalog_name=catalog_name, schema_name=schema_name)
                    if t.name
                ]
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("uc_list_tables failed: %s", exc)
            return []

    async def uc_describe_table(self, full_name: str) -> dict[str, object]:
        """Describe schema and column definitions of a Unity Catalog table."""
        try:
            info = self._call(lambda cl: cl.tables.get(full_name=full_name))
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

    async def dbsql_query(self, query: str, max_rows: int = 100) -> dict[str, object]:
        """Execute a SQL query on a Databricks SQL Warehouse."""
        wh_id = self.effective_warehouse_id
        if not wh_id:
            return {"error": "No Databricks SQL Warehouse available to execute queries."}

        effective_sql = enforce_query_limit(query, default_limit=max_rows)
        try:
            resp = self._call(
                lambda cl: cl.statement_execution.execute_statement(
                    statement=effective_sql,
                    warehouse_id=wh_id,
                    wait_timeout="30s",
                    row_limit=max_rows,
                )
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
            resp = self._call(
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

    async def jobs_list(self, limit: int = 25) -> dict[str, object]:
        """List Lakeflow jobs in the workspace."""
        limit = max(1, min(limit, _JOBS_PAGE_MAX))
        try:
            jobs = self._call(lambda cl: list(itertools.islice(cl.jobs.list(limit=limit), limit)))
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
            wait = self._call(lambda cl: cl.jobs.run_now(job_id=job_id, job_parameters=parameters))
        except Exception as exc:  # noqa: BLE001
            return {"error": f"Failed to run job {job_id}: {exc}"}
        return {"run_id": wait.run_id, "job_id": job_id}

    def _save_workspace_sql_file(self, path: str, sql_text: str) -> None:
        parent_dir = str(Path(path).parent)
        content = sql_text.encode("utf-8")

        def _do_upload(client: WorkspaceClient) -> None:
            try:
                client.workspace.mkdirs(parent_dir)
            except Exception as exc:  # noqa: BLE001
                logger.debug("mkdirs %s: %s", parent_dir, exc)
            client.workspace.upload(
                path=path,
                content=io.BytesIO(content),
                overwrite=True,
                format=ImportFormat.AUTO,
            )

        try:
            self._call(_do_upload)
        except Exception as exc:
            fallback = self._fallback_client()
            if fallback is not None:
                try:
                    _do_upload(fallback)
                except Exception as fb_exc:  # noqa: BLE001
                    raise RuntimeError(
                        f"Failed to upload workspace SQL file to {path}: {fb_exc}"
                    ) from exc
                else:
                    return
            raise RuntimeError(f"Failed to upload workspace SQL file to {path}: {exc}") from exc

    def _build_sql_task(  # noqa: PLR0913
        self,
        task_key: str,
        path: str,
        *,
        query: str | None,
        warehouse_id: str | None,
        agent_name: str | None = None,
        instructions: str | None = None,
    ) -> tuple[Task | None, str | None]:
        sql_warehouse = warehouse_id or self.effective_warehouse_id
        if not sql_warehouse:
            return None, "A SQL job needs a SQL warehouse; none is available."
        effective_path = path
        sql_text = query or (
            path if path and not path.endswith(".sql") and "select" in path.lower() else None
        )
        if sql_text and agent_name:
            sql_text = build_agentic_query(
                query=sql_text,
                agent_name=agent_name,
                instructions=instructions,
            )
        if sql_text:
            if not effective_path or sql_text == effective_path or agent_name:
                effective_path = f"/Workspace/Shared/crabriks/{task_key}.sql"
            try:
                self._save_workspace_sql_file(effective_path, sql_text)
            except Exception as exc:  # noqa: BLE001
                return None, f"Failed to save SQL file to workspace: {exc}"
        elif not effective_path:
            return None, "A SQL job requires either a workspace file path or a SQL query."
        task = Task(
            task_key=task_key,
            sql_task=SqlTask(
                warehouse_id=sql_warehouse,
                file=SqlTaskFile(path=effective_path, source=Source.WORKSPACE),
            ),
        )
        return task, None

    async def jobs_create(  # noqa: PLR0913
        self,
        name: str,
        task_type: Literal["python", "sql", "agentic"] = "sql",
        path: str = "",
        *,
        parameters: list[str] | None = None,
        warehouse_id: str | None = None,
        query: str | None = None,
        agent_name: str | None = None,
        instructions: str | None = None,
        cron_expression: str | None = None,
        timezone_id: str = "UTC",
        pause_status: Literal["PAUSED", "UNPAUSED"] = "UNPAUSED",
    ) -> dict[str, object]:
        """Create a single-task Lakeflow job running SQL, Python, or an Agentic query.

        For `agentic`: runs query, feeds results to agent via ai_query, and outputs report.
        For `python`: `path` is a workspace Python file.
        For `sql`: pass SQL statement in `query` or workspace file in `path`.
        For scheduling: pass `cron_expression` (e.g. '0 0 12 * * ?' or '0 12 * * *').
        """
        task_key = _TASK_KEY_UNSAFE.sub("_", name)
        effective_agent = agent_name or (name if task_type == "agentic" else None)
        if task_type == "python":
            task = Task(
                task_key=task_key,
                spark_python_task=SparkPythonTask(python_file=path, parameters=parameters),
            )
        else:
            task, error = self._build_sql_task(
                task_key,
                path,
                query=query,
                warehouse_id=warehouse_id,
                agent_name=effective_agent,
                instructions=instructions,
            )
            if error or task is None:
                return {"error": error or "Failed to build SQL task."}

        schedule = build_cron_schedule(cron_expression, timezone_id, pause_status)
        create_kwargs: dict[str, Any] = {"name": name, "tasks": [task]}
        if schedule is not None:
            create_kwargs["schedule"] = schedule
        try:
            created = self._call(lambda cl: cl.jobs.create(**create_kwargs))
        except Exception as exc:  # noqa: BLE001
            return {"error": f"Failed to create job {name}: {exc}"}
        result: dict[str, object] = {"job_id": created.job_id, "name": name}
        if task_type == "agentic" or effective_agent:
            result["task_type"] = task_type
            result["agent_name"] = effective_agent
        if schedule:
            result["scheduled"] = True
        return result

    def _update_job_sql_file(
        self,
        job_id: int,
        query: str,
        agent_name: str | None = None,
        instructions: str | None = None,
    ) -> str | None:
        sql_text = (
            build_agentic_query(query, agent_name=agent_name or "Agent", instructions=instructions)
            if agent_name
            else query
        )
        try:
            self._save_workspace_sql_file(f"/Workspace/Shared/crabriks/job_{job_id}.sql", sql_text)
        except Exception as exc:  # noqa: BLE001
            return f"Failed to save updated SQL file: {exc}"
        else:
            return None

    def _prepare_edit_settings(
        self,
        new_settings: dict[str, Any] | None,
        *,
        name: str | None,
        cron_expression: str | None,
        timezone_id: str,
        pause_status: str | None,
    ) -> dict[str, Any]:
        settings_dict = dict(new_settings or {})
        if name:
            settings_dict["name"] = name
        if cron_expression or pause_status:
            schedule = build_cron_schedule(cron_expression, timezone_id, pause_status or "UNPAUSED")
            if schedule:
                settings_dict["schedule"] = schedule.as_dict()
        return settings_dict

    async def jobs_edit(  # noqa: PLR0913
        self,
        job_id: int,
        new_settings: dict[str, Any] | None = None,
        *,
        name: str | None = None,
        cron_expression: str | None = None,
        timezone_id: str = "UTC",
        pause_status: Literal["PAUSED", "UNPAUSED"] | None = None,
        query: str | None = None,
        agent_name: str | None = None,
        instructions: str | None = None,
    ) -> dict[str, object]:
        """Update a Lakeflow job settings, schedule, or query."""
        if query:
            err = self._update_job_sql_file(job_id, query, agent_name, instructions)
            if err:
                return {"error": err}

        settings_dict = self._prepare_edit_settings(
            new_settings,
            name=name,
            cron_expression=cron_expression,
            timezone_id=timezone_id,
            pause_status=pause_status,
        )
        if not settings_dict and not query:
            return {"job_id": job_id, "updated": False, "message": "No settings to update"}

        if settings_dict:
            try:
                self._call(
                    lambda cl: cl.jobs.update(
                        job_id=job_id, new_settings=JobSettings.from_dict(settings_dict)
                    )
                )
            except Exception as exc:  # noqa: BLE001
                return {"error": f"Failed to update job {job_id}: {exc}"}
        return {"job_id": job_id, "updated": True}

    async def jobs_delete(self, job_id: int) -> dict[str, object]:
        """Delete a Lakeflow job from the workspace."""
        try:
            self._call(lambda cl: cl.jobs.delete(job_id=job_id))
        except Exception as exc:  # noqa: BLE001
            return {"error": f"Failed to delete job {job_id}: {exc}"}
        return {"job_id": job_id, "deleted": True}

    async def jobs_cancel_run(self, run_id: int) -> dict[str, object]:
        """Request cancellation of an active Lakeflow job run."""
        try:
            self._call(lambda cl: cl.jobs.cancel_run(run_id=run_id))
        except Exception as exc:  # noqa: BLE001
            return {"error": f"Failed to cancel run {run_id}: {exc}"}
        return {"run_id": run_id, "cancel_requested": True}

    async def jobs_get_run(self, run_id: int) -> dict[str, object]:
        """Get the state of a Lakeflow job run."""
        try:
            run = self._call(lambda cl: cl.jobs.get_run(run_id=run_id))
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

    async def jobs_get_run_output(self, run_id: int) -> dict[str, object]:
        """Get the execution output and logs of a Lakeflow job run."""
        try:
            out = self._call(lambda cl: cl.jobs.get_run_output(run_id=run_id))
        except Exception as exc:  # noqa: BLE001
            return {"error": f"Failed to get output for run {run_id}: {exc}"}
        sql_out = out.sql_output.as_dict() if out.sql_output else None
        return {
            "run_id": run_id,
            "logs": out.logs,
            "error": out.error,
            "sql_output": sql_out,
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
            self.jobs_get_run_output,
            self.jobs_run_now,
            self.jobs_cancel_run,
            self.jobs_create,
            self.jobs_edit,
            self.jobs_delete,
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
