"""App status, workspace health, and hatch profile routes."""

from fastapi import FastAPI, Request

from clawhouse.api.identity import Caller
from clawhouse.api.routes.sessions import _require_caller, _session_out
from clawhouse.api.schemas import (
    AuthSnapshotOut,
    ConnectionSnapshotOut,
    HatchProfileIn,
    HatchStatusOut,
    StatusOut,
)
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
