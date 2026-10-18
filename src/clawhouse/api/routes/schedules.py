"""Schedule management routes and headless execution context."""

from datetime import UTC, datetime

from fastapi import FastAPI, HTTPException, Response

from clawhouse.agent.turn import TurnContext, canonical_session_id
from clawhouse.api.identity import Caller
from clawhouse.api.routes.sessions import _require_caller
from clawhouse.api.schemas import ScheduleIn, ScheduleOut
from clawhouse.capabilities.databricks import DatabricksCapability
from clawhouse.capabilities.schedules import create_schedule_entry
from clawhouse.settings import Settings, request_token
from clawhouse.store.shapes import ScheduleEntry


def scheduled_turn_context(app: FastAPI, sch: ScheduleEntry) -> TurnContext:
    """A schedule runs with nobody watching: questions take their default (`headless`)."""
    settings: Settings = app.state.settings
    caller = Caller(user_id=sch.owner_id, access_token=settings.dev_token or "")
    model = app.state.model_for(caller, None)
    token = request_token(
        forwarded=caller.access_token,
        user_id=caller.user_id,
        dev_user=settings.dev_user,
        dev_token=settings.dev_token,
    )
    return TurnContext(
        owner_id=sch.owner_id,
        store=app.state.store,
        model=model,
        now=lambda: datetime.now(UTC),
        workspace=app.state.workspace,
        mcp_servers=settings.mcp_servers,
        user_token=token,
        sensitive_tools=settings.sensitive_tools,
        mcp_toolset_factory=getattr(app.state, "mcp_toolset_factory", None),
        databricks_capability=DatabricksCapability(user_token=token or "", settings=settings),
        headless=True,
    )


def _schedule_out(s: ScheduleEntry) -> ScheduleOut:
    return ScheduleOut(
        id=s.id,
        session_id=s.session_id,
        owner_id=s.owner_id,
        cron_expression=s.cron_expression,
        prompt=s.prompt,
        status=s.status,
        next_run_at=s.next_run_at.isoformat(),
        created_at=s.created_at.isoformat(),
        last_run_at=s.last_run_at.isoformat() if s.last_run_at else None,
    )


async def _create_schedule(
    app: FastAPI,
    session_id: str,
    body: ScheduleIn,
    caller: Caller,
) -> ScheduleOut:
    canonical = canonical_session_id(session_id)
    sessions = await app.state.store.list_sessions(caller.user_id)
    if not any(s.id == canonical for s in sessions):
        raise HTTPException(status_code=404, detail="Session not found")

    now = datetime.now(UTC)
    try:
        saved = await create_schedule_entry(
            app.state.store,
            session_id=canonical,
            owner_id=caller.user_id,
            cron_expression=body.cron_expression,
            prompt=body.prompt,
            now=now,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _schedule_out(saved)


async def _list_schedules(
    app: FastAPI,
    session_id: str | None,
    caller: Caller,
) -> list[ScheduleOut]:
    schedules = await app.state.store.list_schedules(
        caller.user_id,
        session_id=canonical_session_id(session_id) if session_id else None,
    )
    return [_schedule_out(s) for s in schedules]


async def _cancel_schedule(
    app: FastAPI,
    schedule_id: str,
    caller: Caller,
) -> Response:
    cancelled = await app.state.store.cancel_schedule(schedule_id, caller.user_id)
    if not cancelled:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return Response(status_code=204)


def _schedule_routes(app: FastAPI) -> None:
    @app.post("/api/sessions/{session_id}/schedules", response_model=ScheduleOut, status_code=201)
    async def create_session_schedule(
        session_id: str,
        body: ScheduleIn,
        caller: Caller = _require_caller,
    ) -> ScheduleOut:
        return await _create_schedule(app, session_id, body, caller)

    @app.get("/api/schedules", response_model=list[ScheduleOut])
    async def list_user_schedules(
        session_id: str | None = None,
        caller: Caller = _require_caller,
    ) -> list[ScheduleOut]:
        return await _list_schedules(app, session_id, caller)

    @app.delete("/api/schedules/{schedule_id}", status_code=204)
    async def cancel_schedule_route(
        schedule_id: str,
        caller: Caller = _require_caller,
    ) -> Response:
        return await _cancel_schedule(app, schedule_id, caller)
