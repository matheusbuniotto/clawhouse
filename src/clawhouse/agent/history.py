"""Replay a transcript as Pydantic AI model messages, and trim it for the agent that reads it."""

from __future__ import annotations

import logging
from collections.abc import Collection, Sequence
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from pydantic_ai import RunContext
from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from clawhouse.store.shapes import TranscriptEntry

if TYPE_CHECKING:
    from clawhouse.store.store import SessionStore

logger = logging.getLogger("clawhouse.turn")


def to_model_messages(entries: Sequence[TranscriptEntry]) -> list[ModelMessage]:
    messages: list[ModelMessage] = []
    index = 0
    while index < len(entries):
        consumed = _append_entry(messages, entries, index)
        # An unpaired tool call is omitted. Later turns still replay.
        index += consumed or 1
    return messages


def _append_entry(
    messages: list[ModelMessage],
    entries: Sequence[TranscriptEntry],
    index: int,
) -> int:
    entry = entries[index]
    if entry.role == "user":
        messages.append(ModelRequest(parts=[UserPromptPart(content=entry.content)]))
        return 1
    if entry.role == "assistant":
        messages.append(ModelResponse(parts=[TextPart(content=entry.content)]))
        return 1
    if entry.role == "tool_call":
        return _append_tool_pair(messages, entries, index)
    return 0


def _append_tool_pair(
    messages: list[ModelMessage],
    entries: Sequence[TranscriptEntry],
    index: int,
) -> int:
    call = entries[index]
    if index + 1 >= len(entries):
        return 0
    result = entries[index + 1]
    if result.role != "tool_result":
        return 0
    call_id = call.tool_call_id or result.tool_call_id or "call"
    name = call.tool_name or result.tool_name or ""
    messages.append(
        ModelResponse(parts=[ToolCallPart(tool_name=name, args=call.content, tool_call_id=call_id)])
    )
    messages.append(
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name=result.tool_name or name,
                    content=result.content,
                    tool_call_id=call_id,
                )
            ]
        )
    )
    return 2


def drop_foreign_tool_parts(
    messages: Sequence[ModelMessage], known_tools: Collection[str]
) -> list[ModelMessage]:
    """Keep only tool calls and returns the current agent knows; text always survives.

    The history is shared between agents, so a mentioned agent can inherit calls to tools it
    does not have. Replaying them would make the model call (or the provider reject) a tool
    outside its toolset. Messages left empty are dropped.
    """
    kept: list[ModelMessage] = []
    for message in messages:
        parts = [part for part in message.parts if _known(part, known_tools)]
        if not parts:
            continue
        if len(parts) == len(message.parts):
            kept.append(message)
        else:
            kept.append(replace(message, parts=parts))
    return kept


def _known(part: object, known_tools: Collection[str]) -> bool:
    if isinstance(part, ToolCallPart | ToolReturnPart):
        return part.tool_name in known_tools
    return True


def foreign_tool_filter(ctx: RunContext[Any], messages: list[ModelMessage]) -> list[ModelMessage]:
    """History processor: filter against the tools this run actually exposes."""
    known = ctx.tools
    if not known:
        return messages
    return drop_foreign_tool_parts(messages, known.keys())


def _collect_return_ids(messages: Sequence[ModelMessage]) -> set[str]:
    return_ids: set[str] = set()
    for m in messages:
        for p in getattr(m, "parts", []):
            if isinstance(p, ToolReturnPart):
                return_ids.add(p.tool_call_id)
    return return_ids


def _is_unreturned_call(part: object, return_ids: set[str]) -> bool:
    return isinstance(part, ToolCallPart) and part.tool_call_id not in return_ids


def _filter_response_parts(message: ModelResponse, return_ids: set[str]) -> ModelResponse | None:
    parts = [p for p in message.parts if not _is_unreturned_call(p, return_ids)]
    if not parts:
        return None
    return replace(message, parts=parts)


def drop_unreturned_tool_calls(messages: Sequence[ModelMessage]) -> list[ModelMessage]:
    """Drop any ToolCallPart that does not have a matching ToolReturnPart in messages."""
    return_ids = _collect_return_ids(messages)
    result: list[ModelMessage] = []
    for m in messages:
        if not isinstance(m, ModelResponse):
            result.append(m)
            continue
        filtered = _filter_response_parts(m, return_ids)
        if filtered is not None:
            result.append(filtered)
    return result


async def load_session_history(
    store: SessionStore,
    session_id: str,
    owner_id: str,
    prior: tuple[TranscriptEntry, ...] | None = None,
) -> list[ModelMessage]:
    raw = await store.messages(session_id)
    if raw:
        try:
            return ModelMessagesTypeAdapter.validate_json(raw)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to deserialize native messages for session %s: %s", session_id, exc
            )
    if prior is None:
        prior = await store.transcript(session_id, owner_id)
    return to_model_messages(prior)
