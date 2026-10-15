"""Which agent executes a turn: the session default, or the one `@mentioned` in the message."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from clawhouse.store.shapes import CustomAgent
    from clawhouse.store.store import SessionStore

PLATFORM_AGENT_ID = "main"
PLATFORM_EMOJI = "🦀"


@dataclass(frozen=True, slots=True)
class ActiveAgent:
    """The agent answering a turn. `agent_id` is its handle, the name after `@`."""

    agent_id: str
    name: str
    emoji: str
    custom: CustomAgent | None = None


PLATFORM_AGENT = ActiveAgent(
    agent_id=PLATFORM_AGENT_ID, name=PLATFORM_AGENT_ID, emoji=PLATFORM_EMOJI
)


def _as_active(agent: CustomAgent) -> ActiveAgent:
    return ActiveAgent(
        agent_id=agent.name,
        name=agent.name,
        emoji=agent.signature_emoji,
        custom=agent,
    )


async def find_agent(store: SessionStore, owner_id: str, handle: str | None) -> ActiveAgent | None:
    """The agent the owner may use under `handle`; None when there is no such agent."""
    if not handle:
        return None
    wanted = handle.strip().lstrip("@").lower()
    if wanted == PLATFORM_AGENT_ID:
        return PLATFORM_AGENT
    for agent in await store.list_custom_agents(owner_id):
        if agent.name.lower() == wanted:
            return _as_active(agent)
    return None


async def session_default(store: SessionStore, owner_id: str, handle: str | None) -> ActiveAgent:
    """The session's default agent, falling back to the platform agent."""
    return await find_agent(store, owner_id, handle) or PLATFORM_AGENT
