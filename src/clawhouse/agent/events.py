"""Parsing Pydantic AI stream events, transcript appending, and notice scrubbing."""

from __future__ import annotations

import json
from collections.abc import AsyncIterable
from dataclasses import replace

from pydantic_ai import RunContext
from pydantic_ai.messages import (
    AgentStreamEvent,
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    PartDeltaEvent,
    PartStartEvent,
    TextPart,
    TextPartDelta,
)
from pydantic_ai_harness.compaction import ContextUsageEvent

from clawhouse.agent.core import TurnDeps
from clawhouse.agent.notices import (
    ApprovalNotice,
    ProgressNotice,
    Token,
    ToolCallNotice,
    ToolResultNotice,
    TurnContext,
    TurnNotice,
    UsageNotice,
    _Claimed,
    _Queue,
)
from clawhouse.capabilities.interaction import REPORT_PROGRESS, parse_progress
from clawhouse.capabilities.mcp import scrub_token
from clawhouse.capabilities.skills import loaded_skill_text
from clawhouse.store.shapes import TranscriptEntry


def _text_delta(event: object) -> str | None:
    if isinstance(event, PartStartEvent) and isinstance(event.part, TextPart):
        return event.part.content or None
    if isinstance(event, PartDeltaEvent) and isinstance(event.delta, TextPartDelta):
        return event.delta.content_delta or None
    return None


def _as_text(content: object) -> str:
    if isinstance(content, str):
        return content
    loaded = loaded_skill_text(content)
    if loaded is not None:
        return loaded
    if isinstance(content, dict | list | tuple):
        return json.dumps(content, default=str)
    return str(content)


def notice_from(event: object) -> TurnNotice | None:
    if isinstance(event, FunctionToolCallEvent):
        return ToolCallNotice(
            name=event.part.tool_name,
            arguments=event.part.args_as_json_str(),
            tool_call_id=event.part.tool_call_id,
        )
    if isinstance(event, FunctionToolResultEvent):
        return ToolResultNotice(
            name=event.part.tool_name or "",
            content=_as_text(event.part.content),
            tool_call_id=event.tool_call_id,
        )
    text = _text_delta(event)
    if text:
        return Token(text)
    return None


def entry_from(notice: TurnNotice) -> TranscriptEntry | None:
    if isinstance(notice, ToolCallNotice):
        return TranscriptEntry(
            role="tool_call",
            content=notice.arguments,
            tool_name=notice.name,
            tool_call_id=notice.tool_call_id,
        )
    if isinstance(notice, ToolResultNotice):
        return TranscriptEntry(
            role="tool_result",
            content=notice.content,
            tool_name=notice.name,
            tool_call_id=notice.tool_call_id,
        )
    return None


def _as_progress(notice: TurnNotice) -> TurnNotice | None:
    """`report_progress` streams as its card, not as tool rows; the rows stay in the store."""
    if not isinstance(notice, ToolCallNotice | ToolResultNotice) or notice.name != REPORT_PROGRESS:
        return notice
    if isinstance(notice, ToolResultNotice):
        return None
    parsed = parse_progress(notice.arguments)
    if parsed is None:
        return None
    task_id, steps = parsed
    return ProgressNotice(task_id=task_id, steps=tuple((s.label, s.status) for s in steps))


def _scrub_entry(entry: TranscriptEntry, token: str) -> TranscriptEntry:
    if not token:
        return entry
    has_token = token in entry.content or (entry.tool_name is not None and token in entry.tool_name)
    if not has_token:
        return entry
    return replace(
        entry,
        content=scrub_token(entry.content, token),
        tool_name=scrub_token(entry.tool_name, token) if entry.tool_name else None,
    )


def _scrub_tool_notice(notice: TurnNotice, token: str) -> TurnNotice:
    if isinstance(notice, ToolCallNotice):
        return ToolCallNotice(
            name=notice.name,
            arguments=scrub_token(notice.arguments, token),
            tool_call_id=notice.tool_call_id,
        )
    if isinstance(notice, ToolResultNotice):
        return ToolResultNotice(
            name=notice.name,
            content=scrub_token(notice.content, token),
            tool_call_id=notice.tool_call_id,
        )
    if isinstance(notice, ApprovalNotice):
        return ApprovalNotice(
            approval_id=notice.approval_id,
            name=notice.name,
            arguments=scrub_token(notice.arguments, token),
            tool_call_id=notice.tool_call_id,
        )
    return notice


def _scrub_notice(notice: TurnNotice, token: str) -> TurnNotice:
    if not token:
        return notice
    if isinstance(notice, Token):
        return Token(scrub_token(notice.text, token))
    return _scrub_tool_notice(notice, token)


async def _publish(ctx: TurnContext, queue: _Queue, notice: TurnNotice) -> None:
    scrubbed = _scrub_notice(notice, ctx.user_token)
    await queue.put(scrubbed)
    if ctx.emit is not None:
        await ctx.emit(scrubbed)


def _usage_notice(event: ContextUsageEvent) -> UsageNotice:
    return UsageNotice(
        input_tokens=event.used_tokens,
        context_window=event.window_tokens if event.resolved else None,
    )


async def _append_user(claimed: _Claimed) -> None:
    await _append(claimed, TranscriptEntry(role="user", content=claimed.user_message))


async def _append(claimed: _Claimed, entry: TranscriptEntry) -> None:
    if entry.agent_id is None:
        entry = replace(entry, agent_id=claimed.agent.agent_id)
    if entry.model is None and entry.role != "user":
        entry = replace(entry, model=claimed.model)
    scrubbed = _scrub_entry(entry, claimed.ctx.user_token)
    await claimed.ctx.store.append_entry(claimed.session_id, claimed.run_id, scrubbed)


async def _record(claimed: _Claimed, notice: TurnNotice) -> None:
    entry = entry_from(notice)
    if entry is not None:
        await _append(claimed, entry)


def _is_skipped_tool(notice: TurnNotice, skip_tool_call_id: str | None) -> bool:
    return bool(
        skip_tool_call_id
        and isinstance(notice, ToolCallNotice)
        and notice.tool_call_id == skip_tool_call_id
    )


async def _process_stream_event(
    event: AgentStreamEvent,
    claimed: _Claimed,
    queue: _Queue,
    *,
    skip_tool_call_id: str | None,
    usage: list[UsageNotice] | None,
) -> None:
    if isinstance(event, ContextUsageEvent):
        if usage is not None:
            usage[:] = [_usage_notice(event)]
        return
    notice = notice_from(event)
    if notice is None or _is_skipped_tool(notice, skip_tool_call_id):
        return
    scrubbed = _scrub_notice(notice, claimed.ctx.user_token)
    await _record(claimed, scrubbed)
    shown = _as_progress(scrubbed)
    if shown is not None:
        await _publish(claimed.ctx, queue, shown)


def _persist_and_emit(
    claimed: _Claimed,
    queue: _Queue,
    *,
    skip_tool_call_id: str | None = None,
    usage: list[UsageNotice] | None = None,
):
    async def handle(
        run_ctx: RunContext[TurnDeps],
        events: AsyncIterable[AgentStreamEvent],
    ) -> None:
        del run_ctx
        async for event in events:
            await _process_stream_event(
                event, claimed, queue, skip_tool_call_id=skip_tool_call_id, usage=usage
            )

    return handle


__all__ = [
    "_append",
    "_append_user",
    "_as_progress",
    "_as_text",
    "_persist_and_emit",
    "_publish",
    "_record",
    "_scrub_entry",
    "_scrub_notice",
    "_scrub_tool_notice",
    "_text_delta",
    "_usage_notice",
    "entry_from",
    "notice_from",
]
