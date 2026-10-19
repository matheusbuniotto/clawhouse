from fastapi import FastAPI, HTTPException, Request

from clawhouse.api.identity import Caller
from clawhouse.api.routes.sessions import _require_caller, _session_out
from clawhouse.api.schemas import (
    AuthSnapshotOut,
    ConnectionSnapshotOut,
    HatchProfileIn,
    HatchStatusOut,
    SandboxStatusOut,
    StatusOut,
)
from clawhouse.capabilities.databricks.capability import default_workspace_client
from clawhouse.capabilities.databricks.sandbox import (
    sandbox_list_files,
    sandbox_reset,
    user_sandbox_root,
)
from clawhouse.capabilities.databricks.tools import DatabricksTools
from clawhouse.settings import Settings, request_token
from clawhouse.store.shapes import UserProfile
from clawhouse.store.store import MemorySessionStore, SessionStore


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


def _make_sandbox_tools(request: Request, caller: Caller) -> DatabricksTools:
    settings: Settings = request.app.state.settings
    is_dev = bool(settings.dev_user and caller.user_id == settings.dev_user)
    dev_tok = settings.dev_token if is_dev else None
    effective_token = request_token(
        forwarded=caller.access_token,
        user_id=caller.user_id,
        dev_user=settings.dev_user,
        dev_token=dev_tok,
    )
    client = default_workspace_client(effective_token)
    return DatabricksTools(
        client=client,
        warehouse_id=None,
        user_token=effective_token,
        owner_id=caller.user_id,
    )


def _file_count(res: dict[str, object]) -> int:
    raw = res.get("files")
    return len(raw) if isinstance(raw, list) else 0


def _log_tail_url(settings: Settings) -> str:
    if settings.log_tail_url:
        return settings.log_tail_url
    if settings.workspace_host:
        return f"{settings.workspace_host.rstrip('/')}/#job/logs"
    return "#"


def _sandbox_routes(app: FastAPI) -> None:
    @app.get("/api/sandbox")
    async def get_sandbox(
        request: Request,
        caller: Caller = _require_caller,
    ) -> SandboxStatusOut:
        tools = _make_sandbox_tools(request, caller)
        res = await sandbox_list_files(tools)
        return SandboxStatusOut(
            owner_id=caller.user_id,
            workspace_path=user_sandbox_root(caller.user_id),
            backend="databricks_python_exec",
            status="ready",
            file_count=_file_count(res),
        )

    @app.post("/api/sandbox/reset")
    async def reset_sandbox(
        request: Request,
        caller: Caller = _require_caller,
    ) -> SandboxStatusOut:
        tools = _make_sandbox_tools(request, caller)
        res = await sandbox_reset(tools)
        if "error" in res:
            raise HTTPException(status_code=502, detail=str(res["error"]))
        return SandboxStatusOut(
            owner_id=caller.user_id,
            workspace_path=user_sandbox_root(caller.user_id),
            backend="databricks_python_exec",
            status="ready",
            file_count=0,
        )


def _status_routes(app: FastAPI) -> None:
    _sandbox_routes(app)

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

        summaries = await store.list_sessions(caller.user_id)
        tools = _make_sandbox_tools(request, caller)
        sandbox_res = await sandbox_list_files(tools)
        sandbox_status = SandboxStatusOut(
            owner_id=caller.user_id,
            workspace_path=user_sandbox_root(caller.user_id),
            backend="databricks_python_exec",
            status="ready",
            file_count=_file_count(sandbox_res),
        )
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
            log_tail_url=_log_tail_url(settings),
            sandbox=sandbox_status,
        )
