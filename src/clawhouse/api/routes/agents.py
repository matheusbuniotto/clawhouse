"""Custom agent management routes and activity tracking."""

import shutil
from contextlib import suppress
from datetime import datetime
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Response

from clawhouse.agent.prompt import AGENT_NAME
from clawhouse.api.identity import Caller
from clawhouse.api.routes.sessions import _require_caller
from clawhouse.api.schemas import CustomAgentIn, CustomAgentOut
from clawhouse.capabilities.workspace import (
    UnsafeAgentName,
    provision_agent_workspace,
    resolve_agent_workspace,
)
from clawhouse.settings import Settings
from clawhouse.store.shapes import CustomAgent
from clawhouse.store.store import SessionStore, agent_activities


def _default_model_label(settings: Settings) -> str:
    for entry in settings.models:
        if entry.is_default:
            return entry.model or entry.id
    if settings.models:
        return settings.models[0].model or settings.models[0].id
    return settings.serving_endpoint or "databricks"


def _truncate_activity(text: str, limit: int = 120) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1].rstrip() + "…"


def _agent_out_item(
    *,
    agent: CustomAgent,
    is_platform: bool,
    model_name: str,
    activity: tuple[datetime, str] | None,
    fallback_activity: str,
) -> CustomAgentOut:
    last_active_at = activity[0].isoformat() if activity else None
    last_activity = _truncate_activity(activity[1]) if activity else fallback_activity
    return CustomAgentOut(
        id=agent.id,
        owner_id=agent.owner_id,
        name=agent.name,
        description=agent.description,
        system_prompt=agent.system_prompt,
        signature_emoji=agent.signature_emoji,
        is_platform=is_platform,
        model=model_name,
        last_active_at=last_active_at,
        last_activity=last_activity,
    )


async def _list_agents(app: FastAPI, caller: Caller) -> list[CustomAgentOut]:
    settings: Settings = app.state.settings
    store: SessionStore = app.state.store
    model_name = _default_model_label(settings)
    activities = await agent_activities(store, caller.user_id)
    main_agent = CustomAgent(
        id="platform-main",
        owner_id="platform",
        name="main",
        description="Clawhouse platform agent",
        system_prompt="",
        signature_emoji="🦀",
    )
    agents: list[CustomAgentOut] = [
        _agent_out_item(
            agent=main_agent,
            is_platform=True,
            model_name=model_name,
            activity=activities.get("main"),
            fallback_activity="Heartbeat & platform operations",
        )
    ]
    custom = await store.list_custom_agents(caller.user_id)
    for c in custom:
        agents.append(
            _agent_out_item(
                agent=c,
                is_platform=False,
                model_name=model_name,
                activity=activities.get(c.name),
                fallback_activity=c.description,
            )
        )
    return agents


async def _create_agent(app: FastAPI, payload: CustomAgentIn, caller: Caller) -> CustomAgentOut:
    settings: Settings = app.state.settings
    name = payload.name.strip()
    if name == AGENT_NAME:
        raise HTTPException(status_code=422, detail="Agent name 'main' is reserved.")
    try:
        resolve_agent_workspace(settings.agent_root, name)
    except UnsafeAgentName as exc:
        raise HTTPException(status_code=422, detail="Invalid agent name.") from exc
    custom = CustomAgent(
        id=str(uuid4()),
        owner_id=caller.user_id,
        name=name,
        description=payload.description,
        system_prompt=payload.system_prompt,
        signature_emoji=payload.signature_emoji,
    )
    saved = await app.state.store.create_custom_agent(custom)
    provision_agent_workspace(
        root=settings.agent_root,
        agent_name=saved.name,
        agents_text=saved.system_prompt,
        identity_name=saved.name,
        signature_emoji=saved.signature_emoji,
        soul_text=payload.soul,
        context_text=payload.context,
    )
    return _agent_out_item(
        agent=saved,
        is_platform=False,
        model_name=_default_model_label(settings),
        activity=None,
        fallback_activity=saved.description,
    )


async def _delete_agent(app: FastAPI, agent_id: str, caller: Caller) -> Response:
    agents = await app.state.store.list_custom_agents(caller.user_id)
    matching = next((a for a in agents if a.id == agent_id), None)
    deleted = await app.state.store.delete_custom_agent(agent_id, caller.user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Agent not found")
    if matching:
        settings: Settings = app.state.settings
        with suppress(OSError):
            paths = resolve_agent_workspace(settings.agent_root, matching.name)
            if paths.directory.exists():
                shutil.rmtree(paths.directory)
    return Response(status_code=204)


def _agent_routes(app: FastAPI) -> None:
    @app.get("/api/agents", response_model=list[CustomAgentOut])
    async def list_agents(caller: Caller = _require_caller) -> list[CustomAgentOut]:
        return await _list_agents(app, caller)

    @app.post("/api/agents", status_code=201, response_model=CustomAgentOut)
    async def create_agent(
        payload: CustomAgentIn, caller: Caller = _require_caller
    ) -> CustomAgentOut:
        return await _create_agent(app, payload, caller)

    @app.delete("/api/agents/{agent_id}", status_code=204)
    async def delete_agent(agent_id: str, caller: Caller = _require_caller) -> Response:
        return await _delete_agent(app, agent_id, caller)
