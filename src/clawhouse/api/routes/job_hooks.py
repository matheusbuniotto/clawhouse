"""Databricks job webhook: one fired SQL or SQL-into-agent run."""

from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from clawhouse.agent.turn import TurnContext, run_turn
from clawhouse.api.identity import Caller
from clawhouse.capabilities import fired as fired_mod
from clawhouse.capabilities.databricks import DatabricksCapability
from clawhouse.capabilities.fired_hook import handle_hook
from clawhouse.store.shapes import FiredJob


def _job_hook_routes(app: FastAPI) -> None:
    @app.post("/api/job-hooks")
    async def job_hook(request: Request) -> JSONResponse:
        payload: dict[str, Any] = await request.json()
        client = getattr(app.state, "job_hook_client", None)
        outcome = await handle_hook(
            app.state.store,
            app.state.settings,
            authorization=request.headers.get("authorization"),
            payload=payload,
            client=client,
            run_agent=lambda job, message, token: _run_fired_agent(app, job, message, token),
            poster=fired_mod.post_slack,
        )
        return JSONResponse(outcome.body, status_code=outcome.status)


async def _run_fired_agent(app: FastAPI, job: FiredJob, message: str, token: str) -> str:
    caller = Caller(user_id=job.owner_id, access_token=token)
    ctx = TurnContext(
        owner_id=job.owner_id,
        store=app.state.store,
        model=app.state.model_for(caller, None),
        now=lambda: datetime.now(UTC),
        user_token=token,
        headless=True,
        fired_job=True,
        default_agent=job.agent_name,
        databricks_capability=DatabricksCapability(
            user_token=token, settings=app.state.settings, store=app.state.store
        ),
    )
    result = await run_turn(job.session_id, message, ctx=ctx)
    return result.reply
