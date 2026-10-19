"""The Jobs screen (#97): app schedules and Databricks jobs the user can see, in one list.

Databricks Apps grant no `jobs` user scope, so listing with the user's token usually
fails. Then the app's service principal lists jobs and each one is kept only when its
ACL names the user or one of the user's groups (read with the user's own token).
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import re
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from croniter import croniter
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.jobs import BaseJob

from clawhouse.capabilities.schedules import calculate_next_run
from clawhouse.store.shapes import ScheduleEntry

logger = logging.getLogger("clawhouse.jobs")

Source = Literal["schedule", "databricks"]
Visibility = Literal["user", "acl"]

SCHEDULE_PREFIX = "schedule:"
DATABRICKS_PREFIX = "databricks:"
RUN_LEVELS = frozenset({"CAN_MANAGE_RUN", "CAN_MANAGE", "IS_OWNER"})
JOBS_PAGE = 100
NAME_MAX = 80
PARALLEL_CALLS = 8

_WEEKDAYS = ("domingo", "segunda", "terça", "quarta", "quinta", "sexta", "sábado")
_DOW_NAMES = {name: i for i, name in enumerate(("SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"))}
_NUMBER = re.compile(r"^\d+$")


@dataclass(frozen=True, slots=True)
class LastRun:
    status: str
    started_at: datetime
    session_id: str | None = None
    run_url: str | None = None


@dataclass(frozen=True, slots=True)
class JobItem:
    id: str
    source: Source
    name: str
    agent_id: str | None
    cron: str | None
    cron_human: str | None
    next_run_at: datetime | None
    last_run: LastRun | None
    can_run: bool = False
    can_delete: bool = False
    session_id: str | None = None
    url: str | None = None


@dataclass(frozen=True, slots=True)
class DatabricksListing:
    jobs: tuple[JobItem, ...] = ()
    visibility: Visibility | None = None
    error: str | None = None


# --- cron -------------------------------------------------------------------------------


def _hour(hour: str, minute: str) -> str:
    return f"{int(hour)}h" if int(minute) == 0 else f"{int(hour)}h{int(minute):02d}"


def _day_part(dom: str, dow: str) -> str | None:
    if dom == "*" and dow == "*":
        return "todo dia"
    if dom == "*" and dow == "1-5":
        return "de segunda a sexta"
    if dom == "*" and _NUMBER.match(dow):
        day = _WEEKDAYS[int(dow) % 7]
        return f"todo {day}" if day in {"domingo", "sábado"} else f"toda {day}"
    if _NUMBER.match(dom) and dow == "*":
        return f"todo dia {int(dom)} do mês"
    return None


def _interval(minute: str, hour: str) -> str | None:
    """Every-N rules, which only make sense when day, month and weekday are all `*`."""
    if minute.startswith("*/") and hour == "*":
        return f"a cada {minute[2:]} min"
    if minute == "*" and hour == "*":
        return "a cada minuto"
    if not _NUMBER.match(minute):
        return None
    if hour.startswith("*/"):
        return f"a cada {hour[2:]}h"
    return f"toda hora, no minuto {int(minute)}" if hour == "*" else None


def humanize_cron(expression: str) -> str:
    """A 5-field cron in plain pt-BR ("todo dia às 5h"); the raw text when it is unusual."""
    fields = expression.split()
    if len(fields) != 5 or fields[3] != "*":
        return expression
    minute, hour, dom, _, dow = fields
    if dom == dow == "*":
        every = _interval(minute, hour)
        if every:
            return every
    day = _day_part(dom, dow)
    if day is None or not (_NUMBER.match(minute) and _NUMBER.match(hour)):
        return expression
    return f"{day} às {_hour(hour, minute)}"


def _dow_field(value: str) -> str:
    def one(token: str) -> str:
        if _NUMBER.match(token):
            return str(int(token) - 1)
        return str(_DOW_NAMES.get(token.upper(), token))

    return ",".join("-".join(one(p) for p in part.split("-")) for part in value.split(","))


def quartz_to_cron(quartz: str) -> str | None:
    """Quartz (`s m h dom mon dow [year]`, Sunday = 1) as standard 5-field cron."""
    fields = quartz.split()
    if len(fields) not in (6, 7):
        return None
    _, minute, hour, dom, month, dow = fields[:6]
    dom = "*" if dom == "?" else dom
    dow = "*" if dow in {"?", "*"} else _dow_field(dow)
    cron = f"{minute} {hour} {dom} {month} {dow}"
    return cron if croniter.is_valid(cron) else None


def next_run_in_zone(cron: str, zone: str | None, now: datetime) -> datetime | None:
    try:
        tz = ZoneInfo(zone or "UTC")
    except (KeyError, ValueError):
        tz = UTC
    try:
        local = croniter(cron, now.astimezone(tz)).get_next(datetime)
    except (ValueError, KeyError):
        return None
    return local.astimezone(UTC)


# --- app schedules -----------------------------------------------------------------------


def _shorten(text: str) -> str:
    line = " ".join(text.split())
    return line if len(line) <= NAME_MAX else line[: NAME_MAX - 1] + "…"


def schedule_job(
    schedule: ScheduleEntry,
    agent_id: str,
    now: datetime,
    *,
    name: str | None = None,
) -> JobItem:
    """One app schedule as a Jobs row. Schedules link back to the session they post to."""
    last = (
        LastRun(
            status=schedule.last_status or "done",
            started_at=schedule.last_run_at,
            session_id=schedule.session_id,
        )
        if schedule.last_run_at
        else None
    )
    next_run = schedule.next_run_at if schedule.status == "active" else None
    if next_run is not None and next_run < now:
        next_run = calculate_next_run(schedule.cron_expression, from_time=now)
    return JobItem(
        id=SCHEDULE_PREFIX + schedule.id,
        source="schedule",
        name=_shorten(name or schedule.prompt),
        agent_id=agent_id,
        cron=schedule.cron_expression,
        cron_human=humanize_cron(schedule.cron_expression),
        next_run_at=next_run,
        last_run=last,
        can_run=True,
        can_delete=True,
        session_id=schedule.session_id,
    )


# --- Databricks jobs ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Principal:
    user_name: str
    groups: frozenset[str] = field(default_factory=frozenset)

    @property
    def is_admin(self) -> bool:
        return "admins" in self.groups


def principal_of(user: object) -> Principal:
    name = str(getattr(user, "user_name", "") or "")
    groups = getattr(user, "groups", None) or ()
    names = {str(g.display) for g in groups if getattr(g, "display", None)}
    return Principal(user_name=name, groups=frozenset(names | {"users"}))


def _entry_matches_principal(entry: object, who: Principal) -> bool:
    user = getattr(entry, "user_name", None)
    if user and user.lower() == who.user_name.lower():
        return True
    group = getattr(entry, "group_name", None)
    return bool(group and group in who.groups)


def _entry_permission_levels(entry: object) -> set[str]:
    levels: set[str] = set()
    for perm in getattr(entry, "all_permissions", None) or ():
        level = getattr(perm, "permission_level", None)
        if level is not None:
            levels.add(str(getattr(level, "value", level)))
    return levels


def levels_for(acl: Iterable[object], who: Principal) -> set[str]:
    """Every permission level the ACL grants this user, directly or through a group."""
    levels: set[str] = set()
    for entry in acl:
        if _entry_matches_principal(entry, who):
            levels.update(_entry_permission_levels(entry))
    return levels


def _last_run(client: WorkspaceClient, job_id: int) -> LastRun | None:
    run = next(iter(client.jobs.list_runs(job_id=job_id, limit=1)), None)
    if run is None or run.start_time is None:
        return None
    state = run.state
    status = (
        getattr(state.result_state, "value", None) or getattr(state.life_cycle_state, "value", None)
        if state
        else None
    )
    return LastRun(
        status=str(status or "UNKNOWN"),
        started_at=datetime.fromtimestamp(run.start_time / 1000, tz=UTC),
        run_url=run.run_page_url,
    )


def databricks_job(job: object, *, can_run: bool, last: LastRun | None, now: datetime) -> JobItem:
    settings = getattr(job, "settings", None)
    schedule = getattr(settings, "schedule", None)
    cron = quartz_to_cron(schedule.quartz_cron_expression) if schedule else None
    paused = bool(schedule and getattr(schedule.pause_status, "value", None) == "PAUSED")
    job_id = getattr(job, "job_id", 0)
    return JobItem(
        id=f"{DATABRICKS_PREFIX}{job_id}",
        source="databricks",
        name=str(getattr(settings, "name", None) or f"Job {job_id}"),
        agent_id=None,
        cron=cron,
        cron_human=humanize_cron(cron) if cron else None,
        next_run_at=None
        if cron is None or paused or schedule is None
        else next_run_in_zone(cron, schedule.timezone_id, now),
        last_run=last,
        can_run=can_run,
        can_delete=False,
    )


ClientFactory = Callable[[], WorkspaceClient]


@dataclass(frozen=True, slots=True)
class DatabricksJobs:
    """Lists and runs Databricks jobs as the user sees them."""

    user_client: ClientFactory
    app_client: ClientFactory

    def _with_user(self, now: datetime) -> tuple[JobItem, ...]:
        client = self.user_client()
        jobs = list(itertools.islice(client.jobs.list(limit=25), JOBS_PAGE))
        return tuple(
            databricks_job(job, can_run=True, last=self._safe_last(client, job), now=now)
            for job in jobs
        )

    def _with_acl(self, now: datetime) -> tuple[JobItem, ...]:
        who = principal_of(self.user_client().current_user.me())
        app = self.app_client()
        jobs = list(itertools.islice(app.jobs.list(limit=25), JOBS_PAGE))

        def one(job: BaseJob) -> JobItem | None:
            levels = self._levels(app, job.job_id, who)
            if levels is None:
                return None
            can_run = who.is_admin or bool(levels & RUN_LEVELS)
            return databricks_job(job, can_run=can_run, last=self._safe_last(app, job), now=now)

        # Two calls per job (ACL, last run): in parallel, or the screen waits for seconds.
        with ThreadPoolExecutor(max_workers=PARALLEL_CALLS) as pool:
            return tuple(item for item in pool.map(one, jobs) if item is not None)

    def _levels(self, app: WorkspaceClient, job_id: int | None, who: Principal) -> set[str] | None:
        """The user's levels on a job, or None when the user may not see it."""
        if job_id is None:
            return None
        if who.is_admin:
            return {"CAN_MANAGE"}
        try:
            perms = app.jobs.get_permissions(job_id=str(job_id))
        except Exception as exc:  # noqa: BLE001
            logger.info("Skipping job %s: permissions unreadable (%s)", job_id, exc)
            return None
        levels = levels_for(perms.access_control_list or (), who)
        return levels or None

    @staticmethod
    def _safe_last(client: WorkspaceClient, job: object) -> LastRun | None:
        job_id = getattr(job, "job_id", None)
        if job_id is None:
            return None
        try:
            return _last_run(client, job_id)
        except Exception as exc:  # noqa: BLE001
            logger.info("No last run for job %s (%s)", job_id, exc)
            return None

    def list_sync(self, now: datetime) -> DatabricksListing:
        try:
            return DatabricksListing(jobs=self._with_user(now), visibility="user")
        except Exception as exc:  # noqa: BLE001
            logger.info("Listing jobs with the user token failed (%s); using job ACLs", exc)
        try:
            return DatabricksListing(jobs=self._with_acl(now), visibility="acl")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Listing Databricks jobs failed: %s", exc)
            return DatabricksListing(error=str(exc))

    async def list(self, now: datetime) -> DatabricksListing:
        return await asyncio.to_thread(self.list_sync, now)

    def may_run_sync(self, job_id: int) -> bool:
        try:
            who = principal_of(self.user_client().current_user.me())
        except Exception as exc:  # noqa: BLE001
            logger.info("Cannot tell who is asking to run job %s (%s)", job_id, exc)
            return False
        levels = self._levels(self.app_client(), job_id, who)
        return who.is_admin or bool(levels and levels & RUN_LEVELS)

    def run_now_sync(self, job_id: int) -> int | None:
        """Start a run: the user's token first, the app's identity after the ACL check."""
        try:
            waiter = self.user_client().jobs.run_now(job_id=job_id)
        except Exception as exc:
            if not self.may_run_sync(job_id):
                raise PermissionError("Sem permissão para executar este job.") from exc
            waiter = self.app_client().jobs.run_now(job_id=job_id)
        run_id = getattr(waiter, "run_id", None)
        if run_id is None:
            response = getattr(waiter, "response", None)
            run_id = getattr(response, "run_id", None)
        return run_id

    async def run_now(self, job_id: int) -> int | None:
        return await asyncio.to_thread(self.run_now_sync, job_id)
