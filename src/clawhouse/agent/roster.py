"""Which agent executes a turn: the session default, or the one `@mentioned` in the message."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from clawhouse.store.shapes import CustomAgent
    from clawhouse.store.store import SessionStore

PLATFORM_AGENT_ID = "main"
PLATFORM_EMOJI = "🦀"

# `@handle` at a word start. Tables (`@a.b.c`), files (`@x.md`, `@file:x`), emails: not agents.
_MENTION = re.compile(r"(?<![\w@])@([A-Za-z0-9][A-Za-z0-9_-]*)(?![\w.:/@-])")


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


@dataclass(frozen=True, slots=True)
class AgentChoice:
    """Who answers this message, and the handle that was asked for but does not exist."""

    agent: ActiveAgent
    missing: str | None = None


def first_agent_mention(text: str) -> str | None:
    match = _MENTION.search(text)
    return match.group(1) if match else None


async def choose_agent(
    text: str, *, store: SessionStore, owner_id: str, default_handle: str | None
) -> AgentChoice:
    """`@x` picks the agent for this message only; otherwise the session default answers.

    An unknown `@x`, or one the owner may not use, falls back to the default and is reported.
    """
    default = await session_default(store, owner_id, default_handle)
    handle = first_agent_mention(text)
    if handle is None:
        return AgentChoice(agent=default)
    found = await find_agent(store, owner_id, handle)
    if found is None:
        return AgentChoice(agent=default, missing=handle)
    return AgentChoice(agent=found)


def missing_agent_warning(handle: str) -> str:
    return f"@{handle} não encontrado. Quem respondeu foi o agente padrão da sessão."
