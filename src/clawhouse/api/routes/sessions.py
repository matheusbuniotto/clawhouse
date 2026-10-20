"""Session management, turns, transcripts, and model resolution."""

from collections.abc import AsyncGenerator, Iterator
from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, datetime

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic_ai.models import Model

from clawhouse.agent.model import (
    MissingAccessToken,
    MissingModelConfig,
    UnknownModel,
)
from clawhouse.agent.turn import (
    BUSY_TURN,
    InvalidSessionId,
    TurnContext,
    TurnNotice,
    TurnResult,
    cancel_turn,
    canonical_session_id,
    iter_turn,
)
from clawhouse.api.identity import Caller, Unauthenticated, resolve_caller
from clawhouse.api.schemas import (
    EntryOut,
    ModelOptionOut,
    SessionOut,
    SessionTitleIn,
    TranscriptOut,
    TurnIn,
)
from clawhouse.api.sse import SSE_HEADERS, _frames
from clawhouse.capabilities.databricks import DatabricksCapability
from clawhouse.settings import Settings, request_token
from clawhouse.store.shapes import RunState, SessionSummary, TranscriptEntry
from clawhouse.store.store import (
    ApprovalAlreadyResolved,
    ApprovalForbidden,
    ApprovalPending,
    RunInProgress,
    SessionForbidden,
    SessionNotFound,
    SessionStore,
)

NO_MODEL_DETAIL = (
    "No model is connected. Set SERVING_ENDPOINT (Databricks Model Serving) or "
    "CLAWHOUSE_MODELS (any OpenAI-compatible endpoint), or run `make demo` to try "
    "Clawhouse with a scripted model and no keys."
)


def _caller(request: Request) -> Caller:
    settings: Settings = request.app.state.settings
    try:
        return resolve_caller(request.headers, dev_user=settings.dev_user)
    except Unauthenticated as exc:
        raise HTTPException(status_code=401, detail="Sign in with Databricks to continue.") from exc


_require_caller = Depends(_caller)


def _caller_token(settings: Settings, caller: Caller) -> str:
    """The forwarded caller token wins. Dev token fallback applies strictly to dev_user."""
    dev_user = settings.dev_user
    dev_token = settings.dev_token if (dev_user and caller.user_id == dev_user) else None
    return request_token(
        forwarded=caller.access_token,
        user_id=caller.user_id,
        dev_user=dev_user,
        dev_token=dev_token,
    )


@contextmanager
def _session_errors() -> Iterator[None]:
    """Map store ownership errors on a single session to HTTP statuses."""
    try:
        yield
    except InvalidSessionId as exc:
        raise HTTPException(status_code=422, detail="Session id must be a UUID.") from exc
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail="Session not found.") from exc
    except SessionForbidden as exc:
        raise HTTPException(status_code=403, detail="You do not own this session.") from exc


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


async def _run_state(store: SessionStore, session_id: str, owner_id: str) -> RunState:
    try:
        canonical = canonical_session_id(session_id)
    except InvalidSessionId:
        return "idle"
    sessions = await store.list_sessions(owner_id)
    for summary in sessions:
        if summary.id == canonical:
            return summary.run_state
    return "idle"


def _entry_out(entry: TranscriptEntry) -> EntryOut:
    return EntryOut.model_validate(asdict(entry))


def _session_out(summary: SessionSummary) -> SessionOut:
    return SessionOut(
        id=summary.id,
        title=summary.title,
        created_at=summary.created_at.isoformat(),
        run_state=summary.run_state,
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
            detail=NO_MODEL_DETAIL,
        ) from exc


def _turn_error_response(exc: Exception) -> JSONResponse:
    if isinstance(exc, (SessionForbidden, ApprovalForbidden)):
        return JSONResponse(status_code=403, content={"error": "You do not own this session."})
    if isinstance(exc, ApprovalPending):
        return JSONResponse(
            status_code=409,
            content={"error": "A tool call is pending approval for this session."},
        )
    if isinstance(exc, RunInProgress):
        return JSONResponse(status_code=409, content={"error": BUSY_TURN})
    if isinstance(exc, ApprovalAlreadyResolved):
        return JSONResponse(status_code=409, content={"error": "Approval already resolved."})
    return JSONResponse(status_code=422, content={"error": "Session id must be a UUID."})


async def _first_item(
    iterator: AsyncGenerator[TurnNotice | TurnResult, None],
) -> TurnNotice | TurnResult | JSONResponse:
    try:
        return await anext(iterator)
    except (
        ApprovalPending,
        RunInProgress,
        SessionForbidden,
        ApprovalForbidden,
        ApprovalAlreadyResolved,
        InvalidSessionId,
    ) as exc:
        await iterator.aclose()
        return _turn_error_response(exc)


def _build_turn_context(
    request: Request,
    caller: Caller,
    model_id: str | None = None,
    default_agent: str | None = None,
) -> TurnContext:
    model = _model_for_caller(request, caller, model_id)
    settings: Settings = request.app.state.settings
    token = _caller_token(settings, caller)
    databricks_cap = DatabricksCapability(user_token=token or "", settings=settings)
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
        default_agent=default_agent,
    )


async def _stream_turn(  # noqa: PLR0913
    request: Request,
    session_id: str,
    message: str,
    caller: Caller,
    *,
    model_id: str | None,
    default_agent: str | None = None,
) -> Response:
    ctx = _build_turn_context(request, caller, model_id, default_agent=default_agent)
    iterator = iter_turn(session_id, message, ctx=ctx)
    first = await _first_item(iterator)
    if isinstance(first, JSONResponse):
        return first
    return StreamingResponse(
        _frames(iterator, first),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


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
    _session_meta_routes(app)


def _session_meta_routes(app: FastAPI) -> None:
    """Read, rename, and clear one session without touching its id or created_at."""

    @app.get("/api/sessions/{session_id}")
    async def get_session(
        session_id: str,
        request: Request,
        caller: Caller = _require_caller,
    ) -> SessionOut:
        store: SessionStore = request.app.state.store
        with _session_errors():
            summary = await store.get_session(canonical_session_id(session_id), caller.user_id)
        return _session_out(summary)

    @app.patch("/api/sessions/{session_id}")
    async def rename_session(
        session_id: str,
        body: SessionTitleIn,
        request: Request,
        caller: Caller = _require_caller,
    ) -> SessionOut:
        store: SessionStore = request.app.state.store
        with _session_errors():
            summary = await store.rename_session(
                canonical_session_id(session_id), caller.user_id, body.title
            )
        return _session_out(summary)

    @app.post("/api/sessions/{session_id}/clear")
    async def clear_session(
        session_id: str,
        request: Request,
        caller: Caller = _require_caller,
    ) -> dict[str, bool]:
        store: SessionStore = request.app.state.store
        with _session_errors():
            canonical = canonical_session_id(session_id)
            summary = await store.get_session(canonical, caller.user_id)
            if summary.run_state == "running":
                raise HTTPException(status_code=409, detail="A turn is running in this session.")
            await store.clear_transcript(canonical, caller.user_id)
        return {"cleared": True}


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
        store: SessionStore = request.app.state.store
        entries = await _read_entries(store, session_id, caller.user_id)
        return TranscriptOut(
            entries=[_entry_out(entry) for entry in entries],
            run_state=await _run_state(store, session_id, caller.user_id),
        )

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
        return await _stream_turn(
            request,
            session_id,
            message,
            caller,
            model_id=body.model,
            default_agent=body.agent,
        )


def _cancel_routes(app: FastAPI) -> None:
    """The Stop button: a turn no longer ends when its request does."""

    @app.post("/api/sessions/{session_id}/cancel")
    async def cancel_session_turn(
        session_id: str, caller: Caller = _require_caller
    ) -> dict[str, bool]:
        state = await _run_state(app.state.store, session_id, caller.user_id)
        if state != "running":
            return {"cancelled": False}
        return {"cancelled": await cancel_turn(session_id)}
