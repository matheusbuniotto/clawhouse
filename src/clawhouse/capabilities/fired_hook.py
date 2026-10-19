"""Databricks job-hook delivery for a fired SQL or SQL-into-agent run."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import clawhouse.capabilities.fired as fired_mod
from clawhouse.capabilities.fired import (
    HookOutcome,
    _log_hook,
    agent_user_message,
    basic_ok,
    cap_sheet_rows,
    failure_slack_text,
    hook_password,
    logger,
    post_slack,
    reply_slack_text,
    sql_slack_text,
)
from clawhouse.capabilities.sheets.geometry import NewSheet
from clawhouse.settings import Settings, request_token
from clawhouse.store.shapes import FiredDelivery, FiredJob

if TYPE_CHECKING:
    from clawhouse.store.store import SessionStore


def sql_output_of(client: Any, run_id: int) -> object:
    out = client.jobs.get_run_output(run_id=run_id)
    sql = getattr(out, "sql_output", None)
    if sql is None:
        return None
    if hasattr(sql, "as_dict"):
        return sql.as_dict()
    return sql


async def claim_run(  # noqa: PLR0917
    store: SessionStore,
    job: FiredJob,
    run_id: int,
    event_type: str,
    sheet_status: str | None,
) -> bool:
    if job.databricks_job_id is None:
        return False
    return await store.try_insert_delivery(
        FiredDelivery(
            id=str(uuid4()),
            fired_job_id=job.id,
            databricks_job_id=job.databricks_job_id,
            run_id=run_id,
            event_type=event_type,
            sheet_status=sheet_status,
        )
    )


async def post_or_release(  # noqa: PLR0913, PLR0917
    store: SessionStore,
    job: FiredJob,
    run_id: int,
    event_type: str,
    text: str,
    poster: Callable[[str, str], int] = post_slack,
) -> HookOutcome:
    if not job.slack_webhook_url:
        return HookOutcome(200, {"delivered": True})
    code = poster(job.slack_webhook_url, text)
    if 200 <= code <= 299:
        return HookOutcome(200, {"delivered": True})
    if job.databricks_job_id is not None:
        await store.delete_delivery_run(job.databricks_job_id, run_id, event_type)
    return HookOutcome(502, {"delivered": False})


def user_token_for(settings: Settings | None, owner_id: str) -> str:
    if settings is None:
        return ""
    return request_token(
        forwarded="",
        user_id=owner_id,
        dev_user=settings.dev_user,
        dev_token=settings.dev_token,
    )


async def sheet_for(token: str, title: str, sql_output: object) -> tuple[str, str | None]:
    if not token.strip():
        return "skipped", None
    rows = cap_sheet_rows(sql_output)
    if not rows:
        return "skipped", None
    created = await fired_mod.write_new_sheet(
        token,
        NewSheet(title=title[:100], rows=rows),  # type: ignore[arg-type]
    )
    url = str(created.get("url", ""))
    if not url.startswith("https://docs.google.com/spreadsheets/d/"):
        return "skipped", None
    return "written", url


def _as_int(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _object_map(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if isinstance(value, dict):
        return value
    return {}


def _hook_ids(payload: dict[str, Any]) -> tuple[str, int | None, int | None]:
    event_type = str(payload.get("event_type") or "")
    job_raw = _object_map(payload, "job")
    run_raw = _object_map(payload, "run")
    return event_type, _as_int(job_raw.get("job_id")), _as_int(run_raw.get("run_id"))


async def _route_job(  # noqa: PLR0913
    store: SessionStore,
    settings: Settings | None,
    *,
    job_id: int,
    run_id: int,
    event_type: str,
    client: Any,
    run_agent: Callable[..., Any],
    poster: Callable[[str, str], int],
) -> HookOutcome:
    _log_hook(job_id, run_id, event_type)
    job = await store.fired_job_by_databricks_id(job_id)
    if job is None:
        return HookOutcome(404, {"error": "unknown job"})
    if event_type == "jobs.on_failure":
        text = failure_slack_text(job_id, run_id)
        return await _deliver_text(store, job, run_id, event_type, text, None, poster)
    if event_type != "jobs.on_success":
        return HookOutcome(200, {"delivered": False})
    sql_output = sql_output_of(client, run_id)
    if job.kind == "sql_agent":
        return await _deliver_agent(
            store, settings, job, run_id, event_type, sql_output, run_agent, poster
        )
    text = sql_slack_text(job_id, run_id, sql_output)
    return await _deliver_text(store, job, run_id, event_type, text, None, poster)


async def handle_hook(  # noqa: PLR0913
    store: SessionStore,
    settings: Settings | None,
    *,
    authorization: str | None,
    payload: dict[str, Any],
    client: Any,
    run_agent: Callable[..., Any],
    poster: Callable[[str, str], int] = post_slack,
) -> HookOutcome:
    if not basic_ok(authorization, hook_password(settings)):
        return HookOutcome(401, {"error": "unauthorized"})
    event_type, job_id, run_id = _hook_ids(payload)
    if event_type == "jobs.on_start":
        return HookOutcome(200, {"delivered": False})
    if job_id is None or run_id is None:
        return HookOutcome(404, {"error": "unknown job"})
    return await _route_job(
        store,
        settings,
        job_id=job_id,
        run_id=run_id,
        event_type=event_type,
        client=client,
        run_agent=run_agent,
        poster=poster,
    )


async def _deliver_text(  # noqa: PLR0913, PLR0917
    store: SessionStore,
    job: FiredJob,
    run_id: int,
    event_type: str,
    text: str,
    sheet_status: str | None,
    poster: Callable[[str, str], int],
) -> HookOutcome:
    claimed = await claim_run(store, job, run_id, event_type, sheet_status)
    if not claimed:
        return HookOutcome(200, {"duplicate": True})
    return await post_or_release(store, job, run_id, event_type, text, poster)


async def _deliver_agent(  # noqa: PLR0913, PLR0917
    store: SessionStore,
    settings: Settings | None,
    job: FiredJob,
    run_id: int,
    event_type: str,
    sql_output: object,
    run_agent: Callable[..., Any],
    poster: Callable[[str, str], int],
) -> HookOutcome:
    token = user_token_for(settings, job.owner_id)
    sheet_status, sheet_url = await sheet_for(token, job.name, sql_output)
    claimed = await claim_run(store, job, run_id, event_type, sheet_status)
    if not claimed:
        return HookOutcome(200, {"duplicate": True})
    message = agent_user_message(job.agent_name or "main", job.instructions, sql_output)
    try:
        reply = await run_agent(job, message, token)
    except Exception:  # noqa: BLE001
        logger.info("job hook agent failed job_id=%s run_id=%s", job.databricks_job_id, run_id)
        if job.databricks_job_id is not None:
            await store.delete_delivery_run(job.databricks_job_id, run_id, event_type)
        return HookOutcome(502, {"delivered": False})
    return await post_or_release(
        store, job, run_id, event_type, reply_slack_text(str(reply), sheet_url), poster
    )


async def deliver_schedule_reply(
    store: SessionStore, job: FiredJob, slot: datetime, reply: str
) -> bool:
    """Post one Slack message for this schedule slot. False when it was already claimed."""
    claimed = await store.try_insert_delivery(
        FiredDelivery(
            id=str(uuid4()),
            fired_job_id=job.id,
            schedule_id=job.schedule_id,
            next_run_at=slot,
            sheet_status="skipped",
        )
    )
    if not claimed:
        return False
    if job.slack_webhook_url:
        fired_mod.post_slack(job.slack_webhook_url, reply_slack_text(reply, None))
    return True
