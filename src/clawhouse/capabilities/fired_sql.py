"""Create the Lakeflow SQL job for a fired schedule."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from databricks.sdk.service.jobs import (
    Source,
    SqlTask,
    SqlTaskFile,
    Task,
    Webhook,
    WebhookNotifications,
)

from clawhouse.capabilities.databricks.cron_util import build_cron_schedule
from clawhouse.store.shapes import FiredJob, FiredKind

if TYPE_CHECKING:
    from clawhouse.capabilities.databricks.tools import DatabricksTools


@dataclass(frozen=True, slots=True)
class SqlFire:
    dest: str
    warehouse: str
    path: str
    name: str
    kind: FiredKind
    task_key: str
    agent_name: str
    instructions: str
    cron_expression: str
    timezone_id: str
    pause_status: str
    slack_webhook_url: str


async def _create_sql_job(tools: DatabricksTools, client: Any, spec: SqlFire) -> dict[str, object]:
    task = Task(
        task_key=spec.task_key,
        sql_task=SqlTask(
            warehouse_id=spec.warehouse,
            file=SqlTaskFile(path=spec.path, source=Source.WORKSPACE),
        ),
    )
    schedule = build_cron_schedule(spec.cron_expression, spec.timezone_id, spec.pause_status)
    webhooks = WebhookNotifications(
        on_success=[Webhook(id=spec.dest)],
        on_failure=[Webhook(id=spec.dest)],
    )
    try:
        created = client.jobs.create(
            name=spec.name,
            tasks=[task],
            schedule=schedule,
            webhook_notifications=webhooks,
        )
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Failed to create job {spec.name}: {exc}"}
    raw_id = created.job_id
    if raw_id is None:
        return {"error": f"Failed to create job {spec.name}: no job id"}
    job_id = int(raw_id)
    store = tools.store
    if store is None:
        return {"error": "no session store"}
    await store.insert_fired_job(
        FiredJob(
            id=str(uuid4()),
            session_id=tools.session_id,
            owner_id=tools.owner_id,
            kind=spec.kind,
            name=spec.name,
            slack_webhook_url=spec.slack_webhook_url,
            instructions=spec.instructions,
            agent_name=spec.agent_name or None,
            databricks_job_id=job_id,
        )
    )
    return {
        "job_id": job_id,
        "kind": spec.kind,
        "name": spec.name,
        "scheduled": schedule is not None,
    }
