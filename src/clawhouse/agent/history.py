"""Replay a transcript as Pydantic AI model messages. Pure: no I/O."""

from collections.abc import Sequence

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from clawhouse.store.shapes import TranscriptEntry


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
