"""Turn notice dataclasses, turn context, and stream events."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic_ai.models import Model
from pydantic_ai.toolsets import AbstractToolset

from clawhouse.agent.roster import PLATFORM_AGENT, ActiveAgent
from clawhouse.capabilities.databricks import DatabricksCapability
from clawhouse.capabilities.mcp import MCPServerConfig
from clawhouse.capabilities.workspace import WorkspacePaths
from clawhouse.store.shapes import TurnResult
from clawhouse.store.store import SessionStore


@dataclass(frozen=True, slots=True)
class Token:
    text: str


@dataclass(frozen=True, slots=True)
class ToolCallNotice:
    name: str
    arguments: str
    tool_call_id: str


@dataclass(frozen=True, slots=True)
class ToolResultNotice:
    name: str
    content: str
    tool_call_id: str


@dataclass(frozen=True, slots=True)
class ApprovalNotice:
    approval_id: str
    name: str
    arguments: str
    tool_call_id: str


@dataclass(frozen=True, slots=True)
class QuestionNotice:
    """The run paused on `ask_user`: the card to show, answered by `question_id`."""

    question_id: str
    question: str
    options: tuple[str, ...]
    default: str | None
    multi: bool
    tool_call_id: str


@dataclass(frozen=True, slots=True)
class ProgressNotice:
    """The current state of a progress card. One card per `task_id`, updated in place."""

    task_id: str
    steps: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class Answer:
    """The labels the user clicked on a question card."""

    selected: tuple[str, ...]


Resolution = Literal["approved", "denied"] | Answer


@dataclass(frozen=True, slots=True)
class UsageNotice:
    """Input tokens of the last model request: the context as sent to the model."""

    input_tokens: int
    context_window: int | None


@dataclass(frozen=True, slots=True)
class AgentNotice:
    """Opens a turn: which agent answers it, and on which model."""

    agent_id: str
    name: str
    emoji: str
    model: str


@dataclass(frozen=True, slots=True)
class WarningNotice:
    """A line for the reader, not the model: e.g. an `@agent` that does not exist."""

    text: str


TurnNotice = (
    Token
    | ToolCallNotice
    | ToolResultNotice
    | ApprovalNotice
    | UsageNotice
    | AgentNotice
    | WarningNotice
    | QuestionNotice
    | ProgressNotice
)

Emit = Callable[[TurnNotice], Awaitable[None]]


class _End:
    """Marks the end of the notice queue. Not a stream event."""


_END = _End()
_Queue = asyncio.Queue[TurnNotice | _End]
MCPToolsetFactory = Callable[[MCPServerConfig, str], AbstractToolset[object]]


@dataclass(frozen=True, slots=True)
class TurnContext:
    owner_id: str
    store: SessionStore
    model: Model
    now: Callable[[], datetime]
    emit: Emit | None = None
    workspace: WorkspacePaths | None = None
    workspace_root: Path | None = None
    mcp_servers: tuple[MCPServerConfig, ...] = ()
    user_token: str = ""
    mcp_toolset_factory: MCPToolsetFactory | None = None
    sensitive_tools: tuple[str, ...] = ()
    databricks_capability: DatabricksCapability | None = None
    default_agent: str | None = None
    # No one is watching (scheduled job): questions take their default instead of pausing.
    headless: bool = False


@dataclass(frozen=True, slots=True)
class _Claimed:
    session_id: str
    user_message: str
    run_id: str
    ctx: TurnContext
    agent: ActiveAgent = PLATFORM_AGENT
    model: str | None = None


__all__ = [
    "_END",
    "AgentNotice",
    "Answer",
    "ApprovalNotice",
    "Emit",
    "MCPToolsetFactory",
    "ProgressNotice",
    "QuestionNotice",
    "Resolution",
    "Token",
    "ToolCallNotice",
    "ToolResultNotice",
    "TurnContext",
    "TurnNotice",
    "TurnResult",
    "UsageNotice",
    "WarningNotice",
    "_Claimed",
    "_End",
    "_Queue",
]
