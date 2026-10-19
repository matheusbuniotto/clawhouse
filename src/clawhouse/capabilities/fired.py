"""Schedule a fired job from chat and deliver its result to Slack."""

from __future__ import annotations

import base64
import json
import logging
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal
from uuid import uuid4

from databricks.sdk.errors import PermissionDenied
from databricks.sdk.service.settings import Config, GenericWebhookConfig

from clawhouse.agent.roster import find_agent
from clawhouse.capabilities.databricks.jobs_client import MissingJobsIdentityError
from clawhouse.capabilities.databricks.jobs_tasks import _save_workspace_sql_file
from clawhouse.capabilities.schedules import create_schedule_entry
from clawhouse.capabilities.sheets.tools import write_new_sheet  # noqa: F401
from clawhouse.settings import Settings
from clawhouse.store.shapes import FiredJob

if TYPE_CHECKING:
    from clawhouse.capabilities.databricks.tools import DatabricksTools
    from clawhouse.store.store import SessionStore

logger = logging.getLogger("clawhouse.fired")

HOOK_USER = "clawhouse"
DEST_NAME = "clawhouse-job-hook"
ANALYZE = "Analyze these query results."
HEADLESS_DENY = "headless fired job: tool not approved"
SLACK_REPLY_LIMIT = 3000
SQL_PREVIEW_ROWS = 20
AGENT_ROWS = 100
SHEET_ROWS = 500
SHEET_COLUMNS = 26
FiredKind = Literal["sql", "sql_agent", "agent"]

_TASK_UNSAFE = re.compile(r"[^A-Za-z0-9_-]+")


def _as_kind(kind: str) -> FiredKind:
    if kind == "sql_agent":
        return "sql_agent"
    if kind == "agent":
        return "agent"
    return "sql"


@dataclass(frozen=True, slots=True)
class HookOutcome:
    status: int
    body: dict[str, object]


def validate_fired_request(  # noqa: PLR0917
    kind: str, query: str, agent_name: str, instructions: str, slack_webhook_url: str
) -> str | None:
    error = ""
    if kind not in ("sql", "sql_agent", "agent"):
        error = f"kind must be sql, sql_agent, or agent, not {kind}"
    elif kind in ("sql", "sql_agent") and not query.strip():
        error = "query is required"
    elif kind in ("sql_agent", "agent") and not agent_name.strip():
        error = "agent_name is required"
    elif kind == "agent" and not instructions.strip():
        error = "instructions are required"
    elif not slack_webhook_url.startswith("https://"):
        error = "slack_webhook_url must start with https://"
    return error or None


def hook_url(settings: Settings | None) -> str:
    base = "" if settings is None else settings.app_base_url.rstrip("/")
    if not base:
        return "/api/job-hooks"
    return f"{base}/api/job-hooks"


def hook_password(settings: Settings | None) -> str:
    if settings is None:
        return ""
    return settings.job_hook_password


def basic_ok(header: str | None, password: str) -> bool:
    if not password or not header or not header.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(header.split(" ", 1)[1]).decode()
    except (ValueError, UnicodeDecodeError):
        return False
    user, _, secret = decoded.partition(":")
    return user == HOOK_USER and secret == password


def row_lines(sql_output: object, limit: int) -> list[str]:
    rows = _raw_rows(sql_output)
    return [str(row) for row in rows[:limit]]


def agent_user_message(agent_name: str, instructions: str, sql_output: object) -> str:
    head = instructions.strip() or ANALYZE
    lines = row_lines(sql_output, AGENT_ROWS)
    body = head if not lines else f"{head}\n" + "\n".join(lines)
    return f"@{agent_name}\n{body}"


def sql_slack_text(job_id: int, run_id: int, sql_output: object) -> str:
    preview = "\n".join(row_lines(sql_output, SQL_PREVIEW_ROWS))
    return f"job_id={job_id} run_id={run_id}\n{preview}"


def failure_slack_text(job_id: int, run_id: int) -> str:
    return f"jobs.on_failure job_id={job_id} run_id={run_id}"


def reply_slack_text(reply: str, sheet_url: str | None) -> str:
    body = reply[:SLACK_REPLY_LIMIT]
    if not sheet_url:
        return body
    return f"{body}\n{sheet_url}"


def cap_sheet_rows(sql_output: object) -> list[list[object]]:
    capped: list[list[object]] = []
    for row in _raw_rows(sql_output)[:SHEET_ROWS]:
        if isinstance(row, list):
            capped.append(row[:SHEET_COLUMNS])
    return capped


def post_slack(url: str, text: str) -> int:
    payload = json.dumps({"text": text}).encode()
    request = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return int(response.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code)
    except Exception:  # noqa: BLE001
        return 0


def _raw_rows(sql_output: object) -> list[object]:
    if isinstance(sql_output, dict):
        raw = sql_output.get("rows")
        if isinstance(raw, list):
            return raw
        return []
    if isinstance(sql_output, list):
        return sql_output
    return []


def _task_key(name: str) -> str:
    return _TASK_UNSAFE.sub("_", name) or "fired"


def _log_hook(job_id: int, run_id: int, event_type: str) -> None:
    logger.info("job hook job_id=%s run_id=%s event_type=%s", job_id, run_id, event_type)


def destination_id(client: Any, url: str, password: str) -> str | dict[str, object]:
    try:
        listed = list(client.notification_destinations.list())
    except PermissionDenied:
        return {"error": "notification destination forbidden"}
    for item in listed:
        if getattr(item, "display_name", None) == DEST_NAME and getattr(item, "id", None):
            return str(item.id)
    try:
        created = client.notification_destinations.create(
            display_name=DEST_NAME,
            config=Config(
                generic_webhook=GenericWebhookConfig(url=url, username=HOOK_USER, password=password)
            ),
        )
    except PermissionDenied:
        return {"error": "notification destination forbidden"}
    if not getattr(created, "id", None):
        return {"error": "notification destination forbidden"}
    return str(created.id)


def _sql_task(name: str, query: str, tools: DatabricksTools, client: Any) -> str | None:
    path = f"/Workspace/Shared/clawhouse/{_task_key(name)}.sql"
    try:
        _save_workspace_sql_file(tools, path, query, client=client)
    except Exception as exc:  # noqa: BLE001
        return f"Failed to save SQL file to workspace: {exc}"
    return path


async def schedule_fired(  # noqa: PLR0913
    tools: DatabricksTools,
    *,
    name: str,
    kind: str,
    cron_expression: str,
    slack_webhook_url: str,
    query: str = "",
    agent_name: str = "",
    instructions: str = "",
    timezone_id: str = "UTC",
    pause_status: Literal["PAUSED", "UNPAUSED"] = "UNPAUSED",
    now: datetime | None = None,
) -> dict[str, object]:
    invalid = validate_fired_request(kind, query, agent_name, instructions, slack_webhook_url)
    if invalid:
        return {"error": invalid}
    store = tools.store
    if store is None:
        return {"error": "no session store"}
    agent_error = await _unknown_agent(store, tools.owner_id, kind, agent_name)
    if agent_error:
        return agent_error
    if kind == "agent":
        return await _schedule_agent(
            store,
            session_id=tools.session_id,
            owner_id=tools.owner_id,
            name=name,
            agent_name=agent_name,
            instructions=instructions,
            cron_expression=cron_expression,
            slack_webhook_url=slack_webhook_url,
            now=now or datetime.now(UTC),
        )
    return await _schedule_sql(
        tools,
        name=name,
        kind=kind,
        query=query,
        agent_name=agent_name,
        instructions=instructions,
        cron_expression=cron_expression,
        timezone_id=timezone_id,
        pause_status=pause_status,
        slack_webhook_url=slack_webhook_url,
    )


async def _unknown_agent(
    store: SessionStore, owner_id: str, kind: str, agent_name: str
) -> dict[str, object] | None:
    if kind not in ("sql_agent", "agent"):
        return None
    found = await find_agent(store, owner_id, agent_name)
    if found is None:
        return {"error": "unknown agent"}
    return None


async def _schedule_agent(  # noqa: PLR0913
    store: SessionStore,
    *,
    session_id: str,
    owner_id: str,
    name: str,
    agent_name: str,
    instructions: str,
    cron_expression: str,
    slack_webhook_url: str,
    now: datetime,
) -> dict[str, object]:
    schedule = await create_schedule_entry(
        store,
        session_id=session_id,
        owner_id=owner_id,
        cron_expression=cron_expression,
        prompt=instructions,
        now=now,
    )
    job = FiredJob(
        id=str(uuid4()),
        session_id=session_id,
        owner_id=owner_id,
        kind="agent",
        name=name,
        slack_webhook_url=slack_webhook_url,
        instructions=instructions,
        agent_name=agent_name,
        schedule_id=schedule.id,
    )
    await store.insert_fired_job(job)
    return {"schedule_id": schedule.id, "kind": "agent", "name": name}


async def _schedule_sql(  # noqa: PLR0913
    tools: DatabricksTools,
    *,
    name: str,
    kind: str,
    query: str,
    agent_name: str,
    instructions: str,
    cron_expression: str,
    timezone_id: str,
    pause_status: str,
    slack_webhook_url: str,
) -> dict[str, object]:
    try:
        identity = tools._resolve_jobs_identity()
    except MissingJobsIdentityError as exc:
        return {"error": str(exc)}
    dest = destination_id(identity.client, hook_url(tools.settings), hook_password(tools.settings))
    if isinstance(dest, dict):
        return dest
    warehouse = tools.effective_warehouse_id
    if not warehouse:
        return {"error": "A SQL job needs a SQL warehouse; none is available."}
    path = _sql_task(name, query, tools, identity.client)
    if path is None or path.startswith("Failed"):
        return {"error": path or "Failed to save SQL file to workspace."}
    from clawhouse.capabilities.fired_sql import SqlFire, _create_sql_job  # noqa: PLC0415

    spec = SqlFire(
        dest=dest,
        warehouse=warehouse,
        path=path,
        name=name,
        kind=_as_kind(kind),
        task_key=_task_key(name),
        agent_name=agent_name,
        instructions=instructions,
        cron_expression=cron_expression,
        timezone_id=timezone_id,
        pause_status=pause_status,
        slack_webhook_url=slack_webhook_url,
    )
    return await _create_sql_job(tools, identity.client, spec)
