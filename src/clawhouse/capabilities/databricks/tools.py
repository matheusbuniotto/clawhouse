"""Databricks tools aggregation class delegating to capability modules."""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Literal, TypeVar

from databricks.sdk import WorkspaceClient

from clawhouse.capabilities.databricks import (
    capability,
    catalog,
    jobs_client,
    jobs_tasks,
    python_analysis,
    warehouse,
)
from clawhouse.capabilities.databricks.jobs_client import (
    JobsIdentity,
    MissingJobsIdentityError,
    jobs_identity,
)

if TYPE_CHECKING:
    from clawhouse.settings import Settings

logger = logging.getLogger("clawhouse.databricks")

_T = TypeVar("_T")


def _workspace_client_cls() -> type[WorkspaceClient]:
    mod = sys.modules.get("clawhouse.capabilities.databricks")
    if mod and hasattr(mod, "WorkspaceClient"):
        return mod.WorkspaceClient
    return WorkspaceClient


class DatabricksTools:
    """Methods exposed as agent tools for Unity Catalog and SQL execution."""

    def __init__(  # noqa: PLR0913
        self,
        client: WorkspaceClient,
        warehouse_id: str | None,
        *,
        jobs_identity: JobsIdentity | None = None,
        jobs_identity_resolver: Callable[[], JobsIdentity] | None = None,
        user_token: str = "",
        settings: Settings | None = None,
        store: Any = None,
        session_id: str = "",
        owner_id: str = "",
        model: Any = None,
        workspace: Any = None,
    ) -> None:
        self.client = client
        self.warehouse_id = warehouse_id
        self._jobs_identity = jobs_identity
        self._jobs_identity_resolver = jobs_identity_resolver
        self.user_token = user_token
        self.settings = settings
        self.store = store
        self.session_id = session_id
        self.owner_id = owner_id
        self.model = model
        self.workspace = workspace

    def _resolve_jobs_identity(self) -> JobsIdentity:
        if self._jobs_identity is not None:
            return self._jobs_identity
        if self._jobs_identity_resolver is not None:
            self._jobs_identity = self._jobs_identity_resolver()
            return self._jobs_identity
        if (
            self.settings is not None
            and self.settings.jobs_sp_client_id
            and self.settings.jobs_sp_client_secret
        ):
            self._jobs_identity = jobs_identity(settings=self.settings)
            return self._jobs_identity
        token = self.user_token.strip() if self.user_token else ""
        if token:
            self._jobs_identity = JobsIdentity(kind="user_obo", client=self.client, label="user")
            return self._jobs_identity
        raise MissingJobsIdentityError(
            "No jobs execution identity configured: "
            "neither dedicated Service Principal nor user token is available"
        )

    def _fallback_client(self) -> WorkspaceClient | None:
        try:
            return _workspace_client_cls()()
        except Exception:  # noqa: BLE001
            return None

    @property
    def effective_warehouse_id(self) -> str | None:
        if self.warehouse_id:
            return self.warehouse_id
        try:
            wh = self._call(lambda cl: warehouse.resolve_warehouse_id(cl, None))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to lazily resolve warehouse id: %s", exc)
            return None
        if wh:
            self.warehouse_id = wh
            return wh
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

    def _estate_closed(self) -> dict[str, object] | None:
        return catalog._estate_closed(self)

    async def uc_list_catalogs(self) -> list[str]:
        """List available Unity Catalog catalogs."""
        return await catalog.uc_list_catalogs(self)

    async def uc_list_schemas(self, catalog_name: str) -> list[str]:
        """List schemas within a specific Unity Catalog catalog."""
        return await catalog.uc_list_schemas(self, catalog_name)

    async def uc_list_tables(self, catalog_name: str, schema_name: str) -> list[str]:
        """List tables within a Unity Catalog schema."""
        return await catalog.uc_list_tables(self, catalog_name, schema_name)

    async def uc_describe_table(self, full_name: str) -> dict[str, object]:
        """Describe schema and column definitions of a Unity Catalog table."""
        return await catalog.uc_describe_table(self, full_name)

    async def uc_list_grants(self, full_name: str) -> dict[str, object]:
        """Effective table grants for the caller. Never uses the ambient client."""
        return await catalog.uc_list_grants(self, full_name)

    async def uc_table_lineage(self, full_name: str) -> dict[str, object]:
        """Upstream and downstream tables from system.access.table_lineage."""
        return await catalog.uc_table_lineage(self, full_name)

    async def uc_column_lineage(self, full_name: str, column: str) -> dict[str, object]:
        """Upstream and downstream columns from system.access.column_lineage."""
        return await catalog.uc_column_lineage(self, full_name, column)

    async def dbsql_query(self, query: str, max_rows: int = 100) -> dict[str, object]:
        """Execute a SQL query on a Databricks SQL Warehouse."""
        return await warehouse.dbsql_query(self, query, max_rows=max_rows)

    async def system_ai_query(self, prompt: str, endpoint: str | None = None) -> str:
        """Invoke Databricks AI functions or foundation models."""
        return await warehouse.system_ai_query(self, prompt, endpoint=endpoint)

    async def jobs_list(self, limit: int = 25) -> dict[str, object]:
        """List Lakeflow jobs and active app schedules."""
        return await jobs_client.jobs_list(self, limit=limit)

    async def jobs_run_now(
        self,
        job_id: int | str = 0,
        parameters: dict[str, str] | None = None,
        *,
        schedule_id: str | None = None,
        wait: bool = False,
        timeout_seconds: int = 120,
    ) -> dict[str, object]:
        """Trigger an immediate run of a Lakeflow job (`job_id`) or app schedule (`schedule_id`)."""
        return await jobs_client.jobs_run_now(
            self,
            job_id,
            parameters,
            schedule_id=schedule_id,
            wait=wait,
            timeout_seconds=timeout_seconds,
        )

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
        """Create a single-task Lakeflow job running SQL, Python, or an Agentic query."""
        return await jobs_client.jobs_create(
            self,
            name,
            task_type=task_type,
            path=path,
            parameters=parameters,
            warehouse_id=warehouse_id,
            query=query,
            agent_name=agent_name,
            instructions=instructions,
            cron_expression=cron_expression,
            timezone_id=timezone_id,
            pause_status=pause_status,
        )

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
        return await jobs_client.jobs_edit(
            self,
            job_id,
            new_settings=new_settings,
            name=name,
            cron_expression=cron_expression,
            timezone_id=timezone_id,
            pause_status=pause_status,
            query=query,
            agent_name=agent_name,
            instructions=instructions,
        )

    async def jobs_schedule(  # noqa: PLR0913
        self,
        name: str,
        kind: Literal["sql", "sql_agent", "agent"],
        cron_expression: str,
        slack_webhook_url: str = "",
        *,
        query: str = "",
        agent_name: str = "",
        instructions: str = "",
        timezone_id: str = "UTC",
        pause_status: Literal["PAUSED", "UNPAUSED"] = "UNPAUSED",
    ) -> dict[str, object]:
        """Schedule a fired job: raw SQL, SQL into a Clawhouse agent, or an agent run."""
        from clawhouse.capabilities.fired import schedule_fired  # noqa: PLC0415

        return await schedule_fired(
            self,
            name=name,
            kind=kind,
            cron_expression=cron_expression,
            slack_webhook_url=slack_webhook_url,
            query=query,
            agent_name=agent_name,
            instructions=instructions,
            timezone_id=timezone_id,
            pause_status=pause_status,
        )

    async def jobs_delete(
        self,
        job_id: int | str = 0,
        *,
        schedule_id: str | None = None,
    ) -> dict[str, object]:
        """Delete a Lakeflow job (`job_id`) or cancel an app schedule (`schedule_id`)."""
        return await jobs_client.jobs_delete(self, job_id, schedule_id=schedule_id)

    async def jobs_cancel_run(self, run_id: int) -> dict[str, object]:
        """Request cancellation of an active Lakeflow job run."""
        return await jobs_client.jobs_cancel_run(self, run_id)

    async def jobs_get_run(self, run_id: int) -> dict[str, object]:
        """Get the state of a Lakeflow job run."""
        return await jobs_client.jobs_get_run(self, run_id)

    async def jobs_get_run_output(self, run_id: int) -> dict[str, object]:
        """Get the execution output and logs of a Lakeflow job run."""
        return await jobs_tasks.jobs_get_run_output(self, run_id)

    async def jobs_wait_run(
        self,
        run_id: int,
        timeout_seconds: int = 120,
        poll_interval_seconds: int = 5,
    ) -> dict[str, object]:
        """Poll and wait for a job run to complete, returning final status and output."""
        return await jobs_tasks.jobs_wait_run(
            self,
            run_id,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
        )

    async def system_ai_format_delivery(
        self,
        content: str,
        destination: Literal["slack", "sheets"],
        title: str | None = None,
    ) -> dict[str, object]:
        """Format analytical outputs or reports for Slack or Google Sheets using Databricks AI."""
        return await capability.system_ai_format_delivery(
            self, content, destination=destination, title=title
        )

    async def delivery_send_webhook(
        self,
        url: str,
        payload: dict[str, Any] | str,
    ) -> dict[str, object]:
        """Send a formatted payload or notification to an external webhook (Slack, Sheets)."""
        return await capability.delivery_send_webhook(url, payload)

    async def job_run_failure(self, run_id: int) -> dict[str, object]:
        """Why a run failed, using only the forwarded client."""
        return await jobs_tasks.job_run_failure(self, run_id)

    async def run_python_analysis(
        self,
        code: str,
        execution_id: str | None = None,
        timeout_seconds: int | None = None,
    ) -> dict[str, object]:
        """Run ad-hoc Python on a one-off Lakeflow submit as the caller."""
        return await python_analysis.run_python_analysis(
            self, code, execution_id=execution_id, timeout_seconds=timeout_seconds
        )

    def all_tools(self) -> list[Callable[..., Any]]:
        return [
            self.uc_list_catalogs,
            self.uc_list_schemas,
            self.uc_list_tables,
            self.uc_describe_table,
            self.uc_list_grants,
            self.uc_table_lineage,
            self.uc_column_lineage,
            self.job_run_failure,
            self.run_python_analysis,
            self.dbsql_query,
            self.system_ai_query,
            self.system_ai_format_delivery,
            self.delivery_send_webhook,
            self.jobs_list,
            self.jobs_get_run,
            self.jobs_get_run_output,
            self.jobs_wait_run,
            self.jobs_run_now,
            self.jobs_cancel_run,
            self.jobs_create,
            self.jobs_edit,
            self.jobs_delete,
            self.jobs_schedule,
        ]
