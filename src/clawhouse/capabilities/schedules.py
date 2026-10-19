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
        ctx = replace(ctx, headless=True, fired_job=True)
    next_run = calculate_next_run(schedule.cron_expression, from_time=now)
    slot = schedule.next_run_at
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
