"""FastAPI chat surface. Top-level application factory and router mounting."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager, suppress
from typing import TYPE_CHECKING

from fastapi import FastAPI
from pydantic_ai.models import Model

from clawhouse.agent.demo import demo_chat_model
from clawhouse.agent.model import (
    databricks_chat_model,
    openai_compatible_chat_model,
    select_model,
)
from clawhouse.agent.prompt import AGENT_NAME
from clawhouse.agent.turn import (
    MCPToolsetFactory,
    TurnContext,
    run_turn,
)
from clawhouse.api.identity import Caller
from clawhouse.api.jobs import jobs_routes
from clawhouse.api.routes.agents import (
    _agent_routes,
)
from clawhouse.api.routes.approvals import (
    _approval_routes,
    _question_routes,
)
from clawhouse.api.routes.assets import (
    _asset_routes,
    _cache_headers,
    _page_routes,
)
from clawhouse.api.routes.job_hooks import _job_hook_routes
from clawhouse.api.routes.memory import _memory_routes
from clawhouse.api.routes.schedules import (
    _schedule_routes,
    scheduled_turn_context,
)
from clawhouse.api.routes.sessions import (
    _caller_token,
    _cancel_routes,
    _first_item,
    _model_for_caller,
    _require_caller,
    _session_routes,
)
from clawhouse.api.routes.status import _hatch_routes, _status_routes
from clawhouse.api.routes.suggestions import (
    _composer_routes,
)
from clawhouse.api.sse import (
    _frame,
    _stream_frame,
)
from clawhouse.capabilities.schedules import schedule_worker
from clawhouse.capabilities.workspace import resolve_agent_workspace
from clawhouse.settings import Settings, request_token, settings_from_env
from clawhouse.store.shapes import ScheduleEntry
from clawhouse.store.store import SessionStore, open_store
from clawhouse.telemetry import setup_telemetry

if TYPE_CHECKING:
    from databricks.sdk import WorkspaceClient

OpenStore = Callable[[], Awaitable[SessionStore]]
ModelFor = Callable[[Caller, str | None], Model]

__all__ = [
    "_first_item",
    "_frame",
    "_model_for_caller",
    "_stream_frame",
    "app",
    "create_app",
    "scheduled_turn_context",
    "setup_telemetry",
]


def _routes(app: FastAPI) -> None:
    _cache_headers(app)
    _page_routes(app)
    _asset_routes(app)
    _session_routes(app)
    _hatch_routes(app)
    _approval_routes(app)
    _question_routes(app)
    _cancel_routes(app)
    _status_routes(app)
    _agent_routes(app)
    _schedule_routes(app)
    _job_hook_routes(app)
    jobs_routes(app, _require_caller, lambda caller: _caller_token(app.state.settings, caller))
    _composer_routes(app)
    _memory_routes(app)


def _production_model(settings: Settings, env: Mapping[str, str]) -> ModelFor:
    def model_for(caller: Caller, model_id: str | None) -> Model:
        entry = select_model(settings.models, model_id)
        if entry.provider == "demo":
            return demo_chat_model()
        if entry.provider == "openai_compatible":
            return openai_compatible_chat_model(
                model=entry.model,
                base_url=entry.base_url or "",
                api_key=env.get(entry.api_key_env or "", ""),
            )
        return databricks_chat_model(
            endpoint=entry.model,
            workspace_host=settings.workspace_host or "",
            access_token=request_token(
                forwarded=caller.access_token,
                user_id=caller.user_id,
                dev_user=settings.dev_user,
                dev_token=settings.dev_token,
            ),
        )

    return model_for


def _make_lifespan(
    settings: Settings,
    store: SessionStore | None,
    open_store_fn: OpenStore,
) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        setup_telemetry(settings)
        if store is None:
            app.state.store = await open_store_fn()
        else:
            app.state.store = store

        stop_event = asyncio.Event()

        def _make_turn_ctx(sch: ScheduleEntry) -> TurnContext:
            return scheduled_turn_context(app, sch)

        worker_task = asyncio.create_task(
            schedule_worker(
                store=app.state.store,
                run_turn_fn=lambda s_id, prompt, ctx: run_turn(s_id, prompt, ctx=ctx),
                make_turn_ctx=_make_turn_ctx,
                poll_interval_seconds=15.0,
                stop_event=stop_event,
            )
        )

        try:
            yield
        finally:
            stop_event.set()
            worker_task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await worker_task
            if store is None:
                await app.state.store.close()

    return lifespan


def create_app(  # noqa: PLR0913
    *,
    settings: Settings,
    model_for: ModelFor,
    store: SessionStore | None = None,
    open_store_fn: OpenStore = open_store,
    mcp_toolset_factory: MCPToolsetFactory | None = None,
    workspace_client_factory: Callable[[str], WorkspaceClient] | None = None,
) -> FastAPI:
    app = FastAPI(
        title="Clawhouse",
        lifespan=_make_lifespan(settings, store, open_store_fn),
    )
    app.state.store = store
    app.state.settings = settings
    app.state.model_for = model_for
    app.state.workspace = resolve_agent_workspace(settings.agent_root, AGENT_NAME)
    app.state.mcp_toolset_factory = mcp_toolset_factory
    app.state.workspace_client_factory = workspace_client_factory
    _routes(app)
    return app


_settings = settings_from_env(os.environ)
app = create_app(settings=_settings, model_for=_production_model(_settings, os.environ))
