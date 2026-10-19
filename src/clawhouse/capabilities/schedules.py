"""Schedule command parser and cron calculation."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from croniter import croniter

from clawhouse.store.shapes import ScheduleEntry

logger = logging.getLogger("clawhouse.schedules")

if TYPE_CHECKING:
    from clawhouse.agent.turn import TurnContext
    from clawhouse.store.shapes import TurnResult
    from clawhouse.store.store import SessionStore


class InvalidScheduleCommand(ValueError):
    """The /schedule command format is invalid."""


@dataclass(frozen=True, slots=True)
class ParsedSchedule:
    cron_expression: str
    prompt: str


_CRON_PATTERN = re.compile(r'^\s*/schedule\s+cron\s+["\']([^"\']+)["\']\s+(.+)$', re.DOTALL)
_EVERY_PATTERN = re.compile(r"^\s*/schedule\s+every\s+(\d+)([mh])\s+(.+)$", re.DOTALL)


def _parse_cron(match: re.Match[str]) -> ParsedSchedule:
    expr = match.group(1).strip()
    prompt = match.group(2).strip()
    if not croniter.is_valid(expr):
        raise InvalidScheduleCommand(f"Invalid cron expression: {expr}")
    return ParsedSchedule(cron_expression=expr, prompt=prompt)


def _interval_to_cron(count: int, unit: str) -> str:
    if unit == "m":
        if count <= 0 or count > 59:
            raise InvalidScheduleCommand("Minute intervals must be between 1 and 59")
        return f"*/{count} * * * *"
    if unit == "h":
        if count <= 0 or count > 23:
            raise InvalidScheduleCommand("Hour intervals must be between 1 and 23")
        return f"0 */{count} * * *"
    raise InvalidScheduleCommand(f"Unsupported unit: {unit}")


def _parse_every(match: re.Match[str]) -> ParsedSchedule:
    count = int(match.group(1))
    unit = match.group(2)
    prompt = match.group(3).strip()
    expr = _interval_to_cron(count, unit)
    return ParsedSchedule(cron_expression=expr, prompt=prompt)


def parse_schedule_command(text: str) -> ParsedSchedule | None:
    """Parse `/schedule cron "..." <prompt>` or `/schedule every <N>m <prompt>`."""
    stripped = text.strip()
    if not stripped.startswith("/schedule"):
        return None

    cron_match = _CRON_PATTERN.match(stripped)
    if cron_match:
        return _parse_cron(cron_match)

    every_match = _EVERY_PATTERN.match(stripped)
    if every_match:
        return _parse_every(every_match)

    raise InvalidScheduleCommand(
        'Usage: /schedule cron "<cron_expression>" <prompt> or /schedule every <N>m <prompt>'
    )


def calculate_next_run(cron_expression: str, from_time: datetime | None = None) -> datetime:
    """Calculate the next UTC datetime for a cron expression."""
    now = from_time or datetime.now(UTC)
    itr = croniter(cron_expression, now)
    next_ts = itr.get_next(float)
    return datetime.fromtimestamp(next_ts, tz=UTC)


async def create_schedule_entry(  # noqa: PLR0913
    store: SessionStore,
    *,
    session_id: str,
    owner_id: str,
    cron_expression: str,
    prompt: str,
    now: datetime,
) -> ScheduleEntry:
    """Persist an active schedule and return the stored row."""
    return await store.create_schedule(
        ScheduleEntry(
            id=str(uuid4()),
            session_id=session_id,
            owner_id=owner_id,
            cron_expression=cron_expression,
            prompt=prompt,
            status="active",
            next_run_at=calculate_next_run(cron_expression, from_time=now),
            created_at=now,
        )
    )


async def run_scheduled_turn(
    schedule: ScheduleEntry,
    store: SessionStore,
    run_turn_fn: Callable[[str, str, TurnContext], Awaitable[TurnResult]],
    make_turn_ctx: Callable[[ScheduleEntry], TurnContext],
    *,
    now_fn: Callable[[], datetime] | None = None,
) -> TurnResult | None:
    """Run one due schedule and advance its next_run_at timestamp."""
    now = now_fn() if now_fn else datetime.now(UTC)
    ctx = make_turn_ctx(schedule)
    fired = await store.fired_job_by_schedule(schedule.id)
    if fired is not None:
        ctx = replace(
            ctx,
            headless=True,
            fired_job=True,
            default_agent=fired.agent_name or ctx.default_agent,
        )
    next_run = calculate_next_run(schedule.cron_expression, from_time=now)
    slot = schedule.next_run_at if now >= schedule.next_run_at else now
    try:
        result = await run_turn_fn(schedule.session_id, schedule.prompt, ctx)
    except Exception as exc:
        await store.update_schedule_run(
            schedule.id,
            last_run_at=now,
            next_run_at=next_run,
            last_status="error",
            last_error=str(exc),
        )
        raise
    else:
        status = "error" if result and result.status == "error" else "ok"
        error_msg = result.error if (result and result.status == "error") else None
        await store.update_schedule_run(
            schedule.id,
            last_run_at=now,
            next_run_at=next_run,
            last_status=status,
            last_error=error_msg,
        )
        if fired is not None and result is not None and result.reply:
            from clawhouse.capabilities.fired_hook import deliver_schedule_reply  # noqa: PLC0415

            await deliver_schedule_reply(store, fired, slot, result.reply)
        return result


def _schedule_row(sch: ScheduleEntry, fired: object) -> dict[str, object]:
    return {
        "schedule_id": sch.id,
        "name": getattr(fired, "name", None) or sch.prompt,
        "kind": getattr(fired, "kind", None) or "agent",
        "agent_name": getattr(fired, "agent_name", None),
        "cron_expression": sch.cron_expression,
        "status": sch.status,
        "next_run_at": sch.next_run_at.isoformat(),
        "last_run_at": sch.last_run_at.isoformat() if sch.last_run_at else None,
        "last_status": sch.last_status,
    }


async def list_active_schedules(store: SessionStore, owner_id: str) -> list[dict[str, object]]:
    """Format active schedules for the jobs_list tool."""
    active = [s for s in await store.list_schedules(owner_id) if s.status != "cancelled"]
    return [_schedule_row(s, await store.fired_job_by_schedule(s.id)) for s in active]


async def find_user_schedule(
    store: SessionStore, owner_id: str, target: str
) -> tuple[ScheduleEntry, object] | None:
    """Find an active schedule by schedule ID, fired job ID, or fired job name."""
    cleaned = target.strip().removeprefix("schedule:")
    if not cleaned:
        return None
    for sch in await store.list_schedules(owner_id):
        if sch.status == "cancelled":
            continue
        fired = await store.fired_job_by_schedule(sch.id)
        if sch.id == cleaned or (fired is not None and cleaned in (fired.id, fired.name)):
            return sch, fired
    return None


async def _echo_turn(session_id: str, prompt: str) -> TurnResult:
    from clawhouse.store.shapes import TurnResult as _TurnResult  # noqa: PLC0415

    return _TurnResult(
        session_id=session_id,
        status="ok",
        reply=prompt,
        error=None,
        transcript=(),
    )


def _databricks_cap_from_tools(tools: object, user_token: str) -> object:
    from clawhouse.capabilities.databricks.capability import (  # noqa: PLC0415
        DatabricksCapability,
        default_workspace_client,
    )

    client = getattr(tools, "client", None)
    settings = getattr(tools, "settings", None)
    warehouse_id = getattr(tools, "warehouse_id", None)
    if client is None and settings is None and not user_token:
        return None
    factory = (lambda _tok: client) if client is not None else default_workspace_client
    return DatabricksCapability(
        client_factory=factory,
        warehouse_id=warehouse_id,
        user_token=user_token,
        settings=settings,
    )


def _tool_turn_context(
    tools: object,
    store: SessionStore,
    sch: ScheduleEntry,
    *,
    agent_name: str | None,
    now: datetime,
) -> TurnContext:
    from clawhouse.agent.turn import TurnContext as _TurnContext  # noqa: PLC0415

    user_token = str(getattr(tools, "user_token", ""))
    settings = getattr(tools, "settings", None)
    return _TurnContext(
        owner_id=sch.owner_id,
        store=store,
        model=getattr(tools, "model", None),  # type: ignore[arg-type]
        now=lambda: now,
        workspace=getattr(tools, "workspace", None),
        mcp_servers=settings.mcp_servers if settings else (),
        user_token=user_token,
        sensitive_tools=settings.sensitive_tools if settings else (),
        databricks_capability=_databricks_cap_from_tools(tools, user_token),  # type: ignore[arg-type]
        headless=True,
        fired_job=True,
        default_agent=agent_name,
    )


async def _run_schedule_from_tool(
    tools: object, store: SessionStore, sch: ScheduleEntry, *, fired: object, now: datetime
) -> TurnResult | None:
    from clawhouse.agent.turn import TurnContext, run_turn  # noqa: PLC0415

    model = getattr(tools, "model", None)
    if model is None:
        return await run_scheduled_turn(
            sch,
            store,
            lambda s_id, prompt, _ctx: _echo_turn(s_id, prompt),
            lambda s: TurnContext(owner_id=s.owner_id, store=store, model=None, now=lambda: now),  # type: ignore[arg-type]
            now_fn=lambda: now,
        )
    owner_id = str(getattr(tools, "owner_id", sch.owner_id))
    agent_name = getattr(fired, "agent_name", None) if fired is not None else None
    temp = await store.create_session(owner_id)
    try:
        return await run_scheduled_turn(
            sch,
            store,
            lambda _s_id, prompt, ctx: run_turn(temp.id, prompt, ctx=ctx),
            lambda s: _tool_turn_context(tools, store, s, agent_name=agent_name, now=now),
            now_fn=lambda: now,
        )
    finally:
        with suppress(Exception):
            await store.delete_session(temp.id, owner_id)


async def trigger_schedule_now(tools: object, target: str) -> dict[str, object]:
    """Run an app schedule immediately from chat tools (`jobs_run_now`)."""
    store: SessionStore | None = getattr(tools, "store", None)
    if store is None:
        return {"error": "no session store"}
    owner_id = str(getattr(tools, "owner_id", ""))
    matched = await find_user_schedule(store, owner_id, target)
    if matched is None:
        return {"error": f"Schedule not found: {target}"}
    sch, fired = matched
    now = datetime.now(UTC)
    result = await _run_schedule_from_tool(tools, store, sch, fired=fired, now=now)
    status = "error" if (result and result.status == "error") else "ok"
    name = getattr(fired, "name", None) if fired is not None else None
    return {
        "schedule_id": sch.id,
        "name": name or sch.prompt,
        "status": status,
        "reply": result.reply if result else "",
    }


async def delete_schedule_from_tool(tools: object, target: str) -> dict[str, object]:
    """Cancel an app schedule from chat tools (`jobs_delete`)."""
    store: SessionStore | None = getattr(tools, "store", None)
    if store is None:
        return {"error": "no session store"}
    owner_id = str(getattr(tools, "owner_id", ""))
    matched = await find_user_schedule(store, owner_id, target)
    if matched is None:
        return {"error": f"Schedule not found: {target}"}
    sch, fired = matched
    await store.cancel_schedule(sch.id, owner_id)
    name = getattr(fired, "name", None) if fired is not None else None
    return {
        "schedule_id": sch.id,
        "name": name or sch.prompt,
        "status": "cancelled",
        "deleted": True,
    }


async def _execute_due_turn(
    due: ScheduleEntry,
    store: SessionStore,
    run_turn_fn: Callable[[str, str, TurnContext], Awaitable[TurnResult]],
    make_turn_ctx: Callable[[ScheduleEntry], TurnContext],
) -> None:
    try:
        await run_scheduled_turn(
            due,
            store=store,
            run_turn_fn=run_turn_fn,
            make_turn_ctx=make_turn_ctx,
            now_fn=lambda: datetime.now(UTC),
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("scheduled turn failed: %s", type(exc).__name__)  # noqa: TRY400


async def schedule_worker(
    store: SessionStore,
    run_turn_fn: Callable[[str, str, TurnContext], Awaitable[TurnResult]],
    make_turn_ctx: Callable[[ScheduleEntry], TurnContext],
    *,
    poll_interval_seconds: float = 15.0,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Background polling loop executing due schedules."""
    event = stop_event or asyncio.Event()
    while not event.is_set():
        try:
            now = datetime.now(UTC)
            due_list = await store.claim_due_schedules(now)
            for due in due_list:
                await _execute_due_turn(due, store, run_turn_fn, make_turn_ctx)
        except Exception as exc:  # noqa: BLE001
            logger.error("schedule worker loop error: %s", type(exc).__name__)  # noqa: TRY400

        with suppress(TimeoutError):
            await asyncio.wait_for(event.wait(), timeout=poll_interval_seconds)
