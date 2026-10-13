"""FastAPI chat surface. Streaming stays here; `run_turn` stays transport-agnostic."""

import asyncio
import json
import os
import shutil
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager, suppress
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel
from pydantic_ai.models import Model

from crabriks.agent.model import (
    MissingAccessToken,
    MissingModelConfig,
    UnknownModel,
    databricks_chat_model,
    openai_compatible_chat_model,
    select_model,
)
from crabriks.agent.prompt import AGENT_NAME
from crabriks.agent.turn import (
    BUSY_TURN,
    FAILED_TURN,
    ApprovalNotice,
    InvalidSessionId,
    MCPToolsetFactory,
    Token,
    ToolCallNotice,
    ToolResultNotice,
    TurnContext,
    TurnNotice,
    TurnResult,
    canonical_session_id,
    iter_turn,
    resume_turn,
    run_turn,
)
from crabriks.api.identity import Caller, Unauthenticated, resolve_caller
from crabriks.capabilities.databricks import DatabricksCapability
from crabriks.capabilities.schedules import (
    calculate_next_run,
    schedule_worker,
)
from crabriks.capabilities.workspace import (
    provision_agent_workspace,
    resolve_agent_workspace,
)
from crabriks.settings import Settings, request_token, settings_from_env
from crabriks.store.shapes import (
    ApprovalEntry,
    CustomAgent,
    RunState,
    ScheduleEntry,
    SessionSummary,
    TranscriptEntry,
    UserProfile,
)
from crabriks.store.store import (
    ApprovalAlreadyResolved,
    ApprovalForbidden,
    ApprovalNotFound,
    ApprovalPending,
    MemorySessionStore,
    RunInProgress,
    SessionForbidden,
    SessionNotFound,
    SessionStore,
    open_store,
)

STATIC = Path(__file__).resolve().parent.parent / "static"
SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
OpenStore = Callable[[], Awaitable[SessionStore]]
ModelFor = Callable[[Caller, str | None], Model]


class TurnIn(BaseModel):
    message: str
    model: str | None = None


class ModelOptionOut(BaseModel):
    id: str
    label: str
    default: bool


class SessionOut(BaseModel):
    id: str
    title: str
    created_at: str
    run_state: RunState = "idle"


class HatchStatusOut(BaseModel):
    user_id: str
    hatched: bool
    assistant_name: str | None = None
    signature_emoji: str | None = None
    user_directives: str | None = None


class HatchProfileIn(BaseModel):
    assistant_name: str | None = None
    signature_emoji: str | None = None
    user_directives: str | None = None
    hatched: bool = True


class CustomAgentIn(BaseModel):
    name: str
    description: str
    system_prompt: str
    signature_emoji: str = "🤖"
    soul: str | None = None
    context: str | None = None


class CustomAgentOut(BaseModel):
    id: str
    owner_id: str
    name: str
    description: str
    system_prompt: str
    signature_emoji: str
    is_platform: bool = False


class ScheduleIn(BaseModel):
    cron_expression: str
    prompt: str


class ScheduleOut(BaseModel):
    id: str
    session_id: str
    owner_id: str
    cron_expression: str
    prompt: str
    status: str
    next_run_at: str
    created_at: str
    last_run_at: str | None = None


class AuthSnapshotOut(BaseModel):
    user_id: str
    token_present: bool
    auth_type: str


class ConnectionSnapshotOut(BaseModel):
    workspace_host: str | None
    serving_endpoint: str | None
    store_type: str


class StatusOut(BaseModel):
    auth: AuthSnapshotOut
    connection: ConnectionSnapshotOut
    sessions: list[SessionOut]
    log_tail_url: str


class EntryOut(BaseModel):
    role: str
    content: str
    tool_name: str | None = None
    tool_call_id: str | None = None


class TranscriptOut(BaseModel):
    entries: list[EntryOut]


class ApprovalOut(BaseModel):
    id: str
    session_id: str
    run_id: str
    tool_name: str
    tool_call_id: str
    arguments: str
    status: str
    created_at: str
    resolved_at: str | None = None
    resolved_by: str | None = None


class ApprovalsListOut(BaseModel):
    approvals: list[ApprovalOut]
    pending: list[ApprovalOut]
    history: list[ApprovalOut]


class ApprovalActionOut(BaseModel):
    status: str
    reply: str
    approval: ApprovalOut


def create_app(
    *,
    settings: Settings,
    model_for: ModelFor,
    store: SessionStore | None = None,
    open_store_fn: OpenStore = open_store,
    mcp_toolset_factory: MCPToolsetFactory | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if store is None:
            app.state.store = await open_store_fn()
        else:
            app.state.store = store

        stop_event = asyncio.Event()

        def _make_turn_ctx(sch: ScheduleEntry) -> TurnContext:
            caller = Caller(user_id=sch.owner_id, access_token=settings.dev_token or "")
            model = model_for(caller, None)
            token = request_token(
                forwarded=caller.access_token,
                user_id=caller.user_id,
                dev_user=settings.dev_user,
                dev_token=settings.dev_token,
            )
            databricks_cap = DatabricksCapability(user_token=token or "")
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
                databricks_capability=databricks_cap,
            )

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

    app = FastAPI(title="Crabriks", lifespan=lifespan)
    app.state.store = store
    app.state.settings = settings
    app.state.model_for = model_for
    app.state.workspace = resolve_agent_workspace(settings.agent_root, AGENT_NAME)
    app.state.mcp_toolset_factory = mcp_toolset_factory
    _routes(app)
    return app


def _routes(app: FastAPI) -> None:
    _cache_headers(app)
    _page_routes(app)
    _asset_routes(app)
    _session_routes(app)
    _hatch_routes(app)
    _approval_routes(app)
    _status_routes(app)
    _agent_routes(app)
    _schedule_routes(app)
    _composer_routes(app)


def _cache_headers(app: FastAPI) -> None:
    """Revalidate on every load so redeploys reach browsers holding stale assets."""

    @app.middleware("http")
    async def disable_http_cache(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)
        if "cache-control" not in response.headers:
            response.headers["cache-control"] = "no-cache"
        return response


def _page_routes(app: FastAPI) -> None:
    @app.get("/")
    @app.get("/chat")
    @app.get("/sessions")
    @app.get("/new")
    @app.get("/approvals")
    @app.get("/status")
    async def shell_page(caller: Caller = _require_caller) -> FileResponse:
        del caller
        return FileResponse(STATIC / "index.html")


def _asset_routes(app: FastAPI) -> None:
    _style_routes(app)
    _script_routes(app)


def _style_routes(app: FastAPI) -> None:
    @app.get("/tokens.css")
    async def tokens_style() -> FileResponse:
        return FileResponse(STATIC / "tokens.css", media_type="text/css")

    @app.get("/shell.css")
    async def shell_style() -> FileResponse:
        return FileResponse(STATIC / "shell.css", media_type="text/css")

    @app.get("/transcript.css")
    async def transcript_style() -> FileResponse:
        return FileResponse(STATIC / "transcript.css", media_type="text/css")

    @app.get("/screens.css")
    async def screens_style() -> FileResponse:
        return FileResponse(STATIC / "screens.css", media_type="text/css")


def _script_routes(app: FastAPI) -> None:
    _core_script_routes(app)
    _screen_script_routes(app)


def _core_script_routes(app: FastAPI) -> None:
    @app.get("/boot.js")
    async def boot_script() -> FileResponse:
        return FileResponse(STATIC / "boot.js", media_type="text/javascript")

    @app.get("/shell.js")
    async def shell_script() -> FileResponse:
        return FileResponse(STATIC / "shell.js", media_type="text/javascript")

    @app.get("/dom.js")
    async def dom_script() -> FileResponse:
        return FileResponse(STATIC / "dom.js", media_type="text/javascript")

    @app.get("/transcript.js")
    async def transcript_script() -> FileResponse:
        return FileResponse(STATIC / "transcript.js", media_type="text/javascript")

    @app.get("/highlight.js")
    async def highlight_script() -> FileResponse:
        return FileResponse(STATIC / "highlight.js", media_type="text/javascript")

    @app.get("/jobs.js")
    async def jobs_script() -> FileResponse:
        return FileResponse(STATIC / "jobs.js", media_type="text/javascript")


def _screen_script_routes(app: FastAPI) -> None:
    @app.get("/chat.js")
    async def chat_script() -> FileResponse:
        return FileResponse(STATIC / "chat.js", media_type="text/javascript")

    @app.get("/sessions.js")
    async def sessions_script() -> FileResponse:
        return FileResponse(STATIC / "sessions.js", media_type="text/javascript")

    @app.get("/new.js")
    async def new_script() -> FileResponse:
        return FileResponse(STATIC / "new.js", media_type="text/javascript")

    @app.get("/approvals.js")
    async def approvals_script() -> FileResponse:
        return FileResponse(STATIC / "approvals.js", media_type="text/javascript")

    @app.get("/status.js")
    async def status_script() -> FileResponse:
        return FileResponse(STATIC / "status.js", media_type="text/javascript")


def _session_routes(app: FastAPI) -> None:
    @app.get("/api/me")
    async def me(caller: Caller = _require_caller) -> dict[str, str]:
        return {"user_id": caller.user_id}

    @app.get("/api/models")
    async def list_models(
        request: Request,
        caller: Caller = _require_caller,
    ) -> dict[str, list[ModelOptionOut]]:
        del caller
        settings: Settings = request.app.state.settings
        return {
            "models": [
                ModelOptionOut(id=entry.id, label=entry.label, default=entry.is_default)
                for entry in settings.models
            ]
        }

    @app.get("/api/sessions")
    async def list_sessions(
        request: Request,
        caller: Caller = _require_caller,
    ) -> dict[str, list[SessionOut]]:
        summaries = await request.app.state.store.list_sessions(caller.user_id)
        return {"sessions": [_session_out(summary) for summary in summaries]}

    @app.post("/api/sessions", status_code=201)
    async def create_session(
        request: Request,
        caller: Caller = _require_caller,
    ) -> SessionOut:
        summary = await request.app.state.store.create_session(caller.user_id)
        return _session_out(summary)

    _session_item_routes(app)


def _session_item_routes(app: FastAPI) -> None:
    @app.delete("/api/sessions/{session_id}", status_code=204)
    async def delete_session(
        session_id: str,
        request: Request,
        caller: Caller = _require_caller,
    ) -> Response:
        try:
            canonical = canonical_session_id(session_id)
            await request.app.state.store.delete_session(canonical, caller.user_id)
            return Response(status_code=204)
        except InvalidSessionId as exc:
            raise HTTPException(status_code=422, detail="Session id must be a UUID.") from exc
        except SessionNotFound as exc:
            raise HTTPException(status_code=404, detail="Session not found.") from exc
        except SessionForbidden as exc:
            raise HTTPException(status_code=403, detail="You do not own this session.") from exc

    @app.get("/api/sessions/{session_id}/transcript")
    async def read_transcript(
        session_id: str,
        request: Request,
        caller: Caller = _require_caller,
    ) -> TranscriptOut:
        entries = await _read_entries(request.app.state.store, session_id, caller.user_id)
        return TranscriptOut(entries=[_entry_out(entry) for entry in entries])

    @app.post("/api/sessions/{session_id}/turns")
    async def post_turn(
        session_id: str,
        body: TurnIn,
        request: Request,
        caller: Caller = _require_caller,
    ) -> Response:
        message = body.message.strip()
        if not message:
            raise HTTPException(status_code=422, detail="message is empty")
        return await _stream_turn(request, session_id, message, caller, model_id=body.model)


def _hatch_routes(app: FastAPI) -> None:
    @app.get("/api/hatch")
    async def get_hatch_status(
        request: Request,
        caller: Caller = _require_caller,
    ) -> HatchStatusOut:
        profile = await request.app.state.store.get_user_profile(caller.user_id)
        if profile is None:
            return HatchStatusOut(user_id=caller.user_id, hatched=False)
        return HatchStatusOut(
            user_id=profile.user_id,
            hatched=profile.hatched,
            assistant_name=profile.assistant_name,
            signature_emoji=profile.signature_emoji,
            user_directives=profile.user_directives,
        )

    @app.post("/api/hatch")
    async def save_hatch_status(
        body: HatchProfileIn,
        request: Request,
        caller: Caller = _require_caller,
    ) -> HatchStatusOut:
        profile = UserProfile(
            user_id=caller.user_id,
            assistant_name=body.assistant_name,
            signature_emoji=body.signature_emoji,
            user_directives=body.user_directives,
            hatched=body.hatched,
        )
        saved = await request.app.state.store.save_user_profile(profile)
        return HatchStatusOut(
            user_id=saved.user_id,
            hatched=saved.hatched,
            assistant_name=saved.assistant_name,
            signature_emoji=saved.signature_emoji,
            user_directives=saved.user_directives,
        )


def _approval_routes(app: FastAPI) -> None:
    @app.get("/api/approvals")
    async def list_approvals(
        request: Request,
        caller: Caller = _require_caller,
    ) -> ApprovalsListOut:
        entries = await request.app.state.store.list_approvals(caller.user_id)
        out = [_approval_out(entry) for entry in entries]
        pending = [a for a in out if a.status == "pending"]
        history = [a for a in out if a.status != "pending"]
        return ApprovalsListOut(approvals=out, pending=pending, history=history)

    @app.post("/api/approvals/{approval_id}/approve")
    async def approve_tool(
        approval_id: str,
        request: Request,
        caller: Caller = _require_caller,
    ) -> ApprovalActionOut:
        return await _resolve_and_resume(request, approval_id, "approved", caller)

    @app.post("/api/approvals/{approval_id}/deny")
    async def deny_tool(
        approval_id: str,
        request: Request,
        caller: Caller = _require_caller,
    ) -> ApprovalActionOut:
        return await _resolve_and_resume(request, approval_id, "denied", caller)


def _status_routes(app: FastAPI) -> None:
    @app.get("/api/status")
    async def get_status(
        request: Request,
        caller: Caller = _require_caller,
    ) -> StatusOut:
        settings: Settings = request.app.state.settings
        store: SessionStore = request.app.state.store
        dev_user = settings.dev_user
        dev_token = settings.dev_token if (dev_user and caller.user_id == dev_user) else None
        effective_token = request_token(
            forwarded=caller.access_token,
            user_id=caller.user_id,
            dev_user=dev_user,
            dev_token=dev_token,
        )
        token_present = bool(effective_token)

        store_type = "memory" if isinstance(store, MemorySessionStore) else "lakebase"

        if settings.log_tail_url:
            log_tail_url = settings.log_tail_url
        elif settings.workspace_host:
            log_tail_url = f"{settings.workspace_host.rstrip('/')}/#job/logs"
        else:
            log_tail_url = "#"

        summaries = await store.list_sessions(caller.user_id)
        return StatusOut(
            auth=AuthSnapshotOut(
                user_id=caller.user_id,
                token_present=token_present,
                auth_type=caller.auth_mode,
            ),
            connection=ConnectionSnapshotOut(
                workspace_host=settings.workspace_host,
                serving_endpoint=settings.serving_endpoint,
                store_type=store_type,
            ),
            sessions=[_session_out(s) for s in summaries],
            log_tail_url=log_tail_url,
        )


def _agent_routes(app: FastAPI) -> None:
    @app.get("/api/agents", response_model=list[CustomAgentOut])
    async def list_agents(caller: Caller = _require_caller) -> list[CustomAgentOut]:
        agents: list[CustomAgentOut] = [
            CustomAgentOut(
                id="platform-main",
                owner_id="platform",
                name="main",
                description="Crabriks platform agent",
                system_prompt="",
                signature_emoji="🦀",
                is_platform=True,
            )
        ]
        custom = await app.state.store.list_custom_agents(caller.user_id)
        for c in custom:
            agents.append(
                CustomAgentOut(
                    id=c.id,
                    owner_id=c.owner_id,
                    name=c.name,
                    description=c.description,
                    system_prompt=c.system_prompt,
                    signature_emoji=c.signature_emoji,
                    is_platform=False,
                )
            )
        return agents

    @app.post("/api/agents", status_code=201, response_model=CustomAgentOut)
    async def create_agent(
        payload: CustomAgentIn, caller: Caller = _require_caller
    ) -> CustomAgentOut:
        agent_id = str(uuid4())
        custom = CustomAgent(
            id=agent_id,
            owner_id=caller.user_id,
            name=payload.name,
            description=payload.description,
            system_prompt=payload.system_prompt,
            signature_emoji=payload.signature_emoji,
        )
        saved = await app.state.store.create_custom_agent(custom)
        settings: Settings = app.state.settings
        provision_agent_workspace(
            root=settings.agent_root,
            agent_name=saved.name,
            agents_text=saved.system_prompt,
            identity_name=saved.name,
            signature_emoji=saved.signature_emoji,
            soul_text=payload.soul,
            context_text=payload.context,
        )
        return CustomAgentOut(
            id=saved.id,
            owner_id=saved.owner_id,
            name=saved.name,
            description=saved.description,
            system_prompt=saved.system_prompt,
            signature_emoji=saved.signature_emoji,
            is_platform=False,
        )

    @app.delete("/api/agents/{agent_id}", status_code=204)
    async def delete_agent(agent_id: str, caller: Caller = _require_caller) -> Response:
        agents = await app.state.store.list_custom_agents(caller.user_id)
        matching = next((a for a in agents if a.id == agent_id), None)
        deleted = await app.state.store.delete_custom_agent(agent_id, caller.user_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Agent not found")
        if matching:
            settings: Settings = app.state.settings
            try:
                paths = resolve_agent_workspace(settings.agent_root, matching.name)
                if paths.directory.exists():
                    shutil.rmtree(paths.directory)
            except OSError:
                pass
        return Response(status_code=204)


def _schedule_routes(app: FastAPI) -> None:
    @app.post("/api/sessions/{session_id}/schedules", response_model=ScheduleOut, status_code=201)
    async def create_session_schedule(
        session_id: str,
        body: ScheduleIn,
        caller: Caller = _require_caller,
    ) -> ScheduleOut:
        canonical = canonical_session_id(session_id)
        sessions = await app.state.store.list_sessions(caller.user_id)
        if not any(s.id == canonical for s in sessions):
            raise HTTPException(status_code=404, detail="Session not found")

        now = datetime.now(UTC)
        try:
            next_run = calculate_next_run(body.cron_expression, from_time=now)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        sch_id = str(uuid4())
        entry = ScheduleEntry(
            id=sch_id,
            session_id=canonical,
            owner_id=caller.user_id,
            cron_expression=body.cron_expression,
            prompt=body.prompt,
            status="active",
            next_run_at=next_run,
            created_at=now,
        )
        saved = await app.state.store.create_schedule(entry)
        return ScheduleOut(
            id=saved.id,
            session_id=saved.session_id,
            owner_id=saved.owner_id,
            cron_expression=saved.cron_expression,
            prompt=saved.prompt,
            status=saved.status,
            next_run_at=saved.next_run_at.isoformat(),
            created_at=saved.created_at.isoformat(),
            last_run_at=saved.last_run_at.isoformat() if saved.last_run_at else None,
        )

    @app.get("/api/schedules", response_model=list[ScheduleOut])
    async def list_user_schedules(
        session_id: str | None = None,
        caller: Caller = _require_caller,
    ) -> list[ScheduleOut]:
        schedules = await app.state.store.list_schedules(
            caller.user_id,
            session_id=canonical_session_id(session_id) if session_id else None,
        )
        return [
            ScheduleOut(
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
            for s in schedules
        ]

    @app.delete("/api/schedules/{schedule_id}", status_code=204)
    async def cancel_schedule_route(
        schedule_id: str,
        caller: Caller = _require_caller,
    ) -> Response:
        cancelled = await app.state.store.cancel_schedule(schedule_id, caller.user_id)
        if not cancelled:
            raise HTTPException(status_code=404, detail="Schedule not found")
        return Response(status_code=204)


def _slash_suggestions(app: FastAPI, q: str) -> dict[str, Any]:
    query = q.lower().strip()
    commands = [
        {
            "id": "/compact",
            "label": "/compact",
            "description": "Compact conversation history using context compaction",
        },
        {
            "id": "/schedule",
            "label": "/schedule",
            "description": 'Schedule recurring turn: /schedule cron "..." or every <N>m',
        },
        {"id": "/clear", "label": "/clear", "description": "Start a fresh conversation"},
        {"id": "/help", "label": "/help", "description": "Show available shortcuts and commands"},
    ]
    filtered_cmds = [
        c
        for c in commands
        if not query or query in c["id"].lower() or query in c["description"].lower()
    ]
    skills: list[dict[str, str]] = []
    workspace = getattr(app.state, "workspace", None)
    if workspace and getattr(workspace, "skills", None) and workspace.skills.is_dir():
        for skill_dir in sorted(workspace.skills.iterdir()):
            if skill_dir.is_dir() and (skill_dir / "SKILL.md").exists():
                s_name = skill_dir.name
                skills.append(
                    {
                        "id": f"/skill:{s_name}",
                        "label": f"/skill:{s_name}",
                        "description": f"Activate {s_name} skill instructions",
                    }
                )
    filtered_skills = [
        s
        for s in skills
        if not query or query in s["id"].lower() or query in s["description"].lower()
    ]
    return {"commands": filtered_cmds, "skills": filtered_skills}


async def _at_suggestions(app: FastAPI, caller: Caller, q: str) -> dict[str, Any]:
    query = q.lower().strip()
    agents_list: list[dict[str, str]] = [
        {"name": "main", "description": "Platform agent", "emoji": "🦀"}
    ]
    custom = await app.state.store.list_custom_agents(caller.user_id)
    for ca in custom:
        agents_list.append(
            {"name": ca.name, "description": ca.description, "emoji": ca.signature_emoji}
        )
    filtered_agents = [
        a
        for a in agents_list
        if not query or query in a["name"].lower() or query in a["description"].lower()
    ]

    files_list: list[dict[str, str]] = [
        {"path": "AGENTS.md", "label": "AGENTS.md"},
        {"path": "SOUL.md", "label": "SOUL.md"},
        {"path": "IDENTITY.md", "label": "IDENTITY.md"},
        {"path": "USER.md", "label": "USER.md"},
        {"path": "MEMORY.md", "label": "MEMORY.md"},
    ]
    filtered_files = [f for f in files_list if not query or query in f["path"].lower()]

    tables_list: list[dict[str, str]] = [
        {"name": "samples.nyctaxi.trips", "description": "NYC Taxi trips sample data"},
        {"name": "main.default.customers", "description": "Customer accounts table"},
        {"name": "main.default.orders", "description": "Order records table"},
    ]
    filtered_tables = [
        t
        for t in tables_list
        if not query or query in t["name"].lower() or query in t["description"].lower()
    ]

    return {
        "agents": filtered_agents,
        "files": filtered_files,
        "tables": filtered_tables,
    }


def _composer_routes(app: FastAPI) -> None:
    @app.get("/api/composer/suggestions")
    async def composer_suggestions(
        *,
        prefix: str | None = None,
        trigger_type: str | None = Query(None, alias="type"),
        q: str | None = None,
        query: str | None = None,
        caller: Caller = _require_caller,
    ) -> dict[str, Any]:
        p = trigger_type if trigger_type is not None else (prefix or "@")
        search_query = query if query is not None else (q or "")
        if p == "/":
            res = _slash_suggestions(app, search_query)
            flat = [
                {
                    "label": s["label"],
                    "insert_text": s["id"],
                    "detail": s["description"],
                    "kind": "skill",
                }
                for s in res.get("skills", [])
            ] + [
                {
                    "label": c["label"],
                    "insert_text": c["id"],
                    "detail": c["description"],
                    "kind": "command",
                }
                for c in res.get("commands", [])
            ]
            res["suggestions"] = flat
            return res

        res = await _at_suggestions(app, caller, search_query)
        flat = (
            [
                {
                    "label": a["name"],
                    "insert_text": f"@{a['name']}",
                    "detail": a["description"],
                    "kind": "agent",
                }
                for a in res.get("agents", [])
            ]
            + [
                {
                    "label": f["label"],
                    "insert_text": f"@{f['path']}",
                    "detail": "file",
                    "kind": "file",
                }
                for f in res.get("files", [])
            ]
            + [
                {
                    "label": t["name"],
                    "insert_text": f"@{t['name']}",
                    "detail": t["description"],
                    "kind": "table",
                }
                for t in res.get("tables", [])
            ]
        )
        res["suggestions"] = flat
        return res


def _caller(request: Request) -> Caller:
    settings: Settings = request.app.state.settings
    try:
        return resolve_caller(request.headers, dev_user=settings.dev_user)
    except Unauthenticated as exc:
        raise HTTPException(status_code=401, detail="Sign in with Databricks to continue.") from exc


_require_caller = Depends(_caller)


async def _read_entries(
    store: SessionStore,
    session_id: str,
    owner_id: str,
) -> tuple[TranscriptEntry, ...]:
    try:
        return await store.transcript(canonical_session_id(session_id), owner_id)
    except InvalidSessionId as exc:
        raise HTTPException(status_code=422, detail="Session id must be a UUID.") from exc
    except SessionNotFound:
        return ()
    except SessionForbidden as exc:
        raise HTTPException(status_code=403, detail="You do not own this session.") from exc


def _build_turn_context(
    request: Request,
    caller: Caller,
    model_id: str | None = None,
) -> TurnContext:
    model = _model_for_caller(request, caller, model_id)
    settings: Settings = request.app.state.settings
    # The forwarded caller token wins. Dev token fallback applies strictly to dev_user.
    dev_user = settings.dev_user
    dev_token = settings.dev_token if (dev_user and caller.user_id == dev_user) else None
    token = request_token(
        forwarded=caller.access_token,
        user_id=caller.user_id,
        dev_user=dev_user,
        dev_token=dev_token,
    )
    databricks_cap = DatabricksCapability(user_token=token or "")
    return TurnContext(
        owner_id=caller.user_id,
        store=request.app.state.store,
        model=model,
        now=lambda: datetime.now(UTC),
        workspace=request.app.state.workspace,
        mcp_servers=settings.mcp_servers,
        user_token=token,
        sensitive_tools=settings.sensitive_tools,
        mcp_toolset_factory=getattr(request.app.state, "mcp_toolset_factory", None),
        databricks_capability=databricks_cap,
    )


async def _stream_turn(
    request: Request,
    session_id: str,
    message: str,
    caller: Caller,
    *,
    model_id: str | None,
) -> Response:
    ctx = _build_turn_context(request, caller, model_id)
    iterator = iter_turn(session_id, message, ctx=ctx)
    first = await _first_item(iterator)
    if isinstance(first, JSONResponse):
        return first
    return StreamingResponse(
        _frames(iterator, first),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


async def _resolve_and_resume(
    request: Request,
    approval_id: str,
    decision: Literal["approved", "denied"],
    caller: Caller,
) -> ApprovalActionOut:
    store: SessionStore = request.app.state.store
    try:
        approval = await store.get_approval(approval_id)
    except ApprovalNotFound as exc:
        raise HTTPException(status_code=404, detail="Approval not found.") from exc

    if approval.status != "pending":
        raise HTTPException(status_code=409, detail="Approval already resolved.")

    ctx = _build_turn_context(request, caller)
    try:
        resumed = await resume_turn(
            session_id=approval.session_id,
            approval_id=approval_id,
            decision=decision,
            ctx=ctx,
        )
    except (SessionForbidden, ApprovalForbidden) as exc:
        raise HTTPException(status_code=403, detail="You do not own this session.") from exc
    except ApprovalAlreadyResolved as exc:
        raise HTTPException(status_code=409, detail="Approval already resolved.") from exc
    except RunInProgress as exc:
        raise HTTPException(status_code=409, detail=BUSY_TURN) from exc

    updated = await store.get_approval(approval_id)
    return ApprovalActionOut(
        status=resumed.status,
        reply=resumed.reply,
        approval=_approval_out(updated),
    )


def _model_for_caller(request: Request, caller: Caller, model_id: str | None) -> Model:
    try:
        return request.app.state.model_for(caller, model_id)
    except MissingAccessToken as exc:
        raise HTTPException(
            status_code=401,
            detail="Databricks did not forward a user token.",
        ) from exc
    except UnknownModel as exc:
        raise HTTPException(status_code=422, detail="Unknown model.") from exc
    except MissingModelConfig as exc:
        raise HTTPException(
            status_code=503,
            detail="The model endpoint is not configured.",
        ) from exc


async def _first_item(
    iterator: AsyncGenerator[TurnNotice | TurnResult, None],
) -> TurnNotice | TurnResult | JSONResponse:
    try:
        return await anext(iterator)
    except ApprovalPending:
        await iterator.aclose()
        return JSONResponse(
            status_code=409,
            content={"error": "A tool call is pending approval for this session."},
        )
    except RunInProgress:
        await iterator.aclose()
        return JSONResponse(status_code=409, content={"error": BUSY_TURN})
    except SessionForbidden:
        await iterator.aclose()
        return JSONResponse(status_code=403, content={"error": "You do not own this session."})
    except InvalidSessionId:
        await iterator.aclose()
        return JSONResponse(status_code=422, content={"error": "Session id must be a UUID."})


async def _frames(
    iterator: AsyncGenerator[TurnNotice | TurnResult, None],
    first: TurnNotice | TurnResult,
) -> AsyncIterator[bytes]:
    try:
        yield _encode(first)
        async for item in iterator:
            yield _encode(item)
    finally:
        await iterator.aclose()


def _encode(item: TurnNotice | TurnResult) -> bytes:
    event, payload = _frame(item)
    data = json.dumps(payload, separators=(",", ":"))
    return f"event: {event}\ndata: {data}\n\n".encode()


def _notice_frame(item: TurnNotice) -> tuple[str, dict[str, str]]:
    if isinstance(item, Token):
        return "token", {"text": item.text}
    if isinstance(item, ToolCallNotice):
        return "tool_call", {"name": item.name, "arguments": item.arguments}
    if isinstance(item, ToolResultNotice):
        return "tool_result", {"name": item.name, "content": item.content}
    if isinstance(item, ApprovalNotice):
        return "approval_required", {
            "approval_id": item.approval_id,
            "name": item.name,
            "arguments": item.arguments,
        }
    return "error", {"status": "error", "reply": "", "error": FAILED_TURN}


def _frame(item: TurnNotice | TurnResult) -> tuple[str, dict[str, str]]:
    if isinstance(item, TurnNotice):
        return _notice_frame(item)
    if item.status == "ok":
        return "done", {"status": "ok", "reply": item.reply}
    if item.status == "pending_approval":
        return "done", {
            "status": "pending_approval",
            "reply": item.reply,
            "approval_id": item.approval_id or "",
        }
    return "error", {"status": "error", "reply": "", "error": item.error or FAILED_TURN}


def _approval_out(entry: ApprovalEntry) -> ApprovalOut:
    return ApprovalOut(
        id=entry.id,
        session_id=entry.session_id,
        run_id=entry.run_id,
        tool_name=entry.tool_name,
        tool_call_id=entry.tool_call_id,
        arguments=entry.arguments,
        status=entry.status,
        created_at=entry.created_at.isoformat(),
        resolved_at=entry.resolved_at.isoformat() if entry.resolved_at else None,
        resolved_by=entry.resolved_by,
    )


def _entry_out(entry: TranscriptEntry) -> EntryOut:
    return EntryOut.model_validate(asdict(entry))


def _session_out(summary: SessionSummary) -> SessionOut:
    return SessionOut(
        id=summary.id,
        title=summary.title,
        created_at=summary.created_at.isoformat(),
        run_state=summary.run_state,
    )


def _production_model(settings: Settings, env: Mapping[str, str]) -> ModelFor:
    def model_for(caller: Caller, model_id: str | None) -> Model:
        entry = select_model(settings.models, model_id)
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


_settings = settings_from_env(os.environ)
app = create_app(settings=_settings, model_for=_production_model(_settings, os.environ))
