"""FastAPI chat surface. Streaming stays here; `run_turn` stays transport-agnostic."""

import json
import os
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel
from pydantic_ai.models import Model

from crabriks.identity import Caller, Unauthenticated, resolve_caller
from crabriks.model import (
    MissingAccessToken,
    MissingModelConfig,
    UnknownModel,
    databricks_chat_model,
    openai_compatible_chat_model,
    select_model,
)
from crabriks.prompt import AGENT_NAME
from crabriks.settings import Settings, request_token, settings_from_env
from crabriks.shapes import SessionSummary, TranscriptEntry
from crabriks.skills import SkillsCache
from crabriks.store import (
    RunInProgress,
    SessionForbidden,
    SessionNotFound,
    SessionStore,
    open_store,
)
from crabriks.turn import (
    BUSY_TURN,
    FAILED_TURN,
    InvalidSessionId,
    Token,
    ToolCallNotice,
    ToolResultNotice,
    TurnContext,
    TurnNotice,
    TurnResult,
    canonical_session_id,
    iter_turn,
)
from crabriks.workspace import resolve_agent_workspace

STATIC = Path(__file__).parent / "static"
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


class EntryOut(BaseModel):
    role: str
    content: str
    tool_name: str | None = None
    tool_call_id: str | None = None


class TranscriptOut(BaseModel):
    entries: list[EntryOut]


def create_app(
    *,
    settings: Settings,
    model_for: ModelFor,
    store: SessionStore | None = None,
    open_store_fn: OpenStore = open_store,
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
    app.state.skills_cache = SkillsCache()
    _routes(app)
    return app


def _routes(app: FastAPI) -> None:
    _page_routes(app)
    _api_routes(app)


def _page_routes(app: FastAPI) -> None:
    @app.get("/")
    @app.get("/chat")
    async def chat_page(caller: Caller = _require_caller) -> FileResponse:
        del caller
        return FileResponse(STATIC / "index.html")

    @app.get("/chat.js")
    async def chat_script() -> FileResponse:
        return FileResponse(STATIC / "chat.js", media_type="text/javascript")

    @app.get("/chat.css")
    async def chat_style() -> FileResponse:
        return FileResponse(STATIC / "chat.css", media_type="text/css")

    @app.get("/sessions")
    async def sessions_page(caller: Caller = _require_caller) -> FileResponse:
        del caller
        return FileResponse(STATIC / "sessions.html")

    @app.get("/new")
    async def new_page(caller: Caller = _require_caller) -> FileResponse:
        del caller
        return FileResponse(STATIC / "new.html")

    @app.get("/sessions.js")
    async def sessions_script() -> FileResponse:
        return FileResponse(STATIC / "sessions.js", media_type="text/javascript")

    @app.get("/new.js")
    async def new_script() -> FileResponse:
        return FileResponse(STATIC / "new.js", media_type="text/javascript")


def _api_routes(app: FastAPI) -> None:
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


async def _stream_turn(
    request: Request,
    session_id: str,
    message: str,
    caller: Caller,
    *,
    model_id: str | None,
) -> Response:
    model = _model_for_caller(request, caller, model_id)
    ctx = TurnContext(
        owner_id=caller.user_id,
        store=request.app.state.store,
        model=model,
        now=lambda: datetime.now(UTC),
        workspace=request.app.state.workspace,
        skills_cache=request.app.state.skills_cache,
    )
    iterator = iter_turn(session_id, message, ctx=ctx)
    first = await _first_item(iterator)
    if isinstance(first, JSONResponse):
        return first
    return StreamingResponse(
        _frames(iterator, first),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
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


def _frame(item: TurnNotice | TurnResult) -> tuple[str, dict[str, str]]:
    if isinstance(item, Token):
        return "token", {"text": item.text}
    if isinstance(item, ToolCallNotice):
        return "tool_call", {"name": item.name, "arguments": item.arguments}
    if isinstance(item, ToolResultNotice):
        return "tool_result", {"name": item.name, "content": item.content}
    if item.status == "ok":
        return "done", {"status": "ok", "reply": item.reply}
    return "error", {"status": "error", "reply": "", "error": item.error or FAILED_TURN}


def _entry_out(entry: TranscriptEntry) -> EntryOut:
    return EntryOut.model_validate(asdict(entry))


def _session_out(summary: SessionSummary) -> SessionOut:
    return SessionOut(
        id=summary.id,
        title=summary.title,
        created_at=summary.created_at.isoformat(),
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
