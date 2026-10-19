"""`/api/jobs` (#97): one list for app schedules and Databricks jobs."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from databricks.sdk import WorkspaceClient
from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel

from clawhouse.agent.roster import PLATFORM_AGENT_ID, find_agent, first_agent_mention
from clawhouse.capabilities.jobs import (
    DATABRICKS_PREFIX,
    SCHEDULE_PREFIX,
    DatabricksJobs,
    JobItem,
    schedule_job,
)
from clawhouse.store.shapes import ScheduleEntry
from clawhouse.store.store import SessionStore


class LastRunOut(BaseModel):
    status: str
    started_at: str
    session_id: str | None = None
    run_url: str | None = None


class JobOut(BaseModel):
    id: str
    source: Literal["schedule", "databricks"]
    name: str
    agent_id: str | None
    cron: str | None
    cron_human: str | None
    next_run_at: str | None
    last_run: LastRunOut | None
    can_run: bool
    can_delete: bool
    session_id: str | None = None


class JobsOut(BaseModel):
    jobs: list[JobOut]
    databricks_visibility: Literal["user", "acl"] | None = None
    databricks_error: str | None = None


class RunOut(BaseModel):
    id: str
    run_id: int | None


def job_out(item: JobItem) -> JobOut:
    last = item.last_run
    return JobOut(
        id=item.id,
        source=item.source,
        name=item.name,
        agent_id=item.agent_id,
        cron=item.cron,
        cron_human=item.cron_human,
        next_run_at=item.next_run_at.isoformat() if item.next_run_at else None,
        last_run=LastRunOut(
            status=last.status,
            started_at=last.started_at.isoformat(),
            session_id=last.session_id,
            run_url=last.run_url,
        )
        if last
        else None,
        can_run=item.can_run,
        can_delete=item.can_delete,
        session_id=item.session_id,
    )


def user_workspace_client(token: str | None) -> Callable[[], WorkspaceClient]:
    """The user's own client. Never the app identity: no token, no client."""

    def make() -> WorkspaceClient:
        if not token:
            raise PermissionError("No user token for Databricks.")
        return WorkspaceClient(token=token, auth_type="pat")

    return make


def default_jobs_factory(token: str | None) -> DatabricksJobs:
    return DatabricksJobs(user_client=user_workspace_client(token), app_client=WorkspaceClient)


async def _schedule_item(
    store: SessionStore, owner_id: str, schedule: ScheduleEntry, now: datetime
) -> JobItem:
    fired = await store.fired_job_by_schedule(schedule.id)
    handle = (fired.agent_name if (fired and fired.agent_name) else None) or first_agent_mention(
        schedule.prompt
    )
    found = await find_agent(store, owner_id, handle)
    agent_id = found.agent_id if found else PLATFORM_AGENT_ID
    name = fired.name if (fired and fired.name) else None
    return schedule_job(schedule, agent_id, now, name=name)


async def schedule_items(store: SessionStore, owner_id: str, now: datetime) -> list[JobItem]:
    schedules = await store.list_schedules(owner_id)
    return [
        await _schedule_item(store, owner_id, s, now) for s in schedules if s.status != "cancelled"
    ]


def _databricks_id(job_id: str) -> int:
    raw = job_id.removeprefix(DATABRICKS_PREFIX)
    if not job_id.startswith(DATABRICKS_PREFIX) or not raw.isdigit():
        raise HTTPException(status_code=404, detail="Job not found")
    return int(raw)


def jobs_routes(
    app: FastAPI,
    caller_dep: Any,
    token_for: Callable[[Any], str],
) -> None:
    def jobs_for(caller: Any) -> DatabricksJobs:
        factory = getattr(app.state, "databricks_jobs_factory", None) or default_jobs_factory
        return factory(token_for(caller))

    @app.get("/api/jobs", response_model=JobsOut)
    async def list_jobs(
        caller: Any = caller_dep, source: Literal["schedule"] | None = None
    ) -> JobsOut:
        """`?source=schedule` answers from the database alone, so the screen paints at once."""
        now = datetime.now(UTC)
        items = await schedule_items(app.state.store, caller.user_id, now)
        if source == "schedule":
            return JobsOut(jobs=[job_out(i) for i in items])
        listing = await jobs_for(caller).list(now)
        return JobsOut(
            jobs=[job_out(i) for i in [*items, *listing.jobs]],
            databricks_visibility=listing.visibility,
            databricks_error=listing.error,
        )

    @app.post("/api/jobs/{job_id}/run", response_model=RunOut)
    async def run_job(job_id: str, caller: Any = caller_dep) -> RunOut:
        return await _run(
            app,
            jobs_for(caller),
            caller.user_id,
            job_id,
            access_token=getattr(caller, "access_token", ""),
        )

    @app.delete("/api/jobs/{job_id}", status_code=204)
    async def delete_job(job_id: str, caller: Any = caller_dep) -> Response:
        await _delete(app.state.store, caller.user_id, job_id)
        return Response(status_code=204)


async def _run_schedule(
    app: FastAPI, owner_id: str, job_id: str, *, access_token: str = ""
) -> RunOut:
    raw = job_id.removeprefix(SCHEDULE_PREFIX)
    try:
        UUID(raw)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc
    store: SessionStore = app.state.store
    schedules = await store.list_schedules(owner_id)
    target = next((s for s in schedules if s.id == raw and s.status == "active"), None)
    if target is None:
        raise HTTPException(status_code=404, detail="Job not found")
    from clawhouse.agent.turn import run_turn  # noqa: PLC0415
    from clawhouse.api.routes.schedules import scheduled_turn_context  # noqa: PLC0415
    from clawhouse.capabilities.schedules import _echo_turn, run_scheduled_turn  # noqa: PLC0415

    ctx = scheduled_turn_context(app, target, access_token=access_token)
    run_fn = (
        (lambda s_id, prompt, c: run_turn(s_id, prompt, ctx=c))
        if ctx.model is not None
        else (lambda s_id, prompt, _c: _echo_turn(s_id, prompt))
    )
    await run_scheduled_turn(target, store, run_fn, lambda _sch: ctx)
    return RunOut(id=job_id, run_id=None)


async def _run(
    app: FastAPI,
    jobs: DatabricksJobs,
    owner_id: str,
    job_id: str,
    *,
    access_token: str = "",
) -> RunOut:
    """Start an immediate run for either an app schedule or a Databricks job."""
    if job_id.startswith(SCHEDULE_PREFIX):
        return await _run_schedule(app, owner_id, job_id, access_token=access_token)
    numeric = _databricks_id(job_id)
    try:
        run_id = await jobs.run_now(numeric)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return RunOut(id=job_id, run_id=run_id)


async def _delete(store: SessionStore, owner_id: str, job_id: str) -> None:
    """Delete exists only for app schedules (it cancels them)."""
    if job_id.startswith(DATABRICKS_PREFIX):
        raise HTTPException(status_code=405, detail="Jobs do Databricks não são apagados aqui.")
    if not job_id.startswith(SCHEDULE_PREFIX):
        raise HTTPException(status_code=404, detail="Job not found")
    raw = job_id.removeprefix(SCHEDULE_PREFIX)
    try:
        UUID(raw)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc
    if not await store.cancel_schedule(raw, owner_id):
        raise HTTPException(status_code=404, detail="Job not found")
