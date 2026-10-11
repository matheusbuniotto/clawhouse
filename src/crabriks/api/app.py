"""FastAPI chat surface. Streaming stays here; `run_turn` stays transport-agnostic."""

import json
import os
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request
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
)
from crabriks.api.identity import Caller, Unauthenticated, resolve_caller
from crabriks.capabilities.workspace import resolve_agent_workspace
from crabriks.settings import Settings, request_token, settings_from_env
from crabriks.store.shapes import (
    ApprovalEntry,
    RunState,
    SessionSummary,
    TranscriptEntry,
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
            try:
                yield
            finally:
                await app.state.store.close()
        else:
            app.state.store = store
            yield

    app = FastAPI(title="Crabriks", lifespan=lifespan)
    app.state.store = store
    app.state.settings = settings
    app.state.model_for = model_for
    app.state.workspace = resolve_agent_workspace(settings.agent_root, AGENT_NAME)
    app.state.mcp_toolset_factory = mcp_toolset_factory
    _routes(app)
    return app


def _routes(app: FastAPI) -> None:
    _page_routes(app)
    _asset_routes(app)
    _session_routes(app)
    _approval_routes(app)
    _status_routes(app)


def _page_routes(app: FastAPI) -> None:
    @app.get("/")
    @app.get("/chat")
    async def chat_page(caller: Caller = _require_caller) -> FileResponse:
        del caller
        return FileResponse(STATIC / "index.html")

    @app.get("/sessions")
    async def sessions_page(caller: Caller = _require_caller) -> FileResponse:
        del caller
        return FileResponse(STATIC / "sessions.html")

    @app.get("/new")
    async def new_page(caller: Caller = _require_caller) -> FileResponse:
        del caller
        return FileResponse(STATIC / "new.html")

    @app.get("/approvals")
    async def approvals_page(caller: Caller = _require_caller) -> FileResponse:
        del caller
        return FileResponse(STATIC / "approvals.html")

    @app.get("/status")
    async def status_page(caller: Caller = _require_caller) -> FileResponse:
        del caller
        return FileResponse(STATIC / "status.html")


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
    @app.get("/chat.js")
    async def chat_script() -> FileResponse:
        return FileResponse(STATIC / "chat.js", media_type="text/javascript")

    @app.get("/sessions.js")
    async def sessions_script() -> FileResponse:
        return FileResponse(STATIC / "sessions.js", media_type="text/javascript")

    @app.get("/transcript.js")
    async def transcript_script() -> FileResponse:
        return FileResponse(STATIC / "transcript.js", media_type="text/javascript")

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
