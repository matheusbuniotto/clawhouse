"""Server-Sent Events framing, JSON serialization, and notice formatting."""

import json
from collections.abc import AsyncGenerator, AsyncIterator

from clawhouse.agent.turn import (
    FAILED_TURN,
    AgentNotice,
    ApprovalNotice,
    ProgressNotice,
    QuestionNotice,
    Token,
    ToolCallNotice,
    ToolResultNotice,
    TurnNotice,
    TurnResult,
    UsageNotice,
    WarningNotice,
)

SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


async def _frames(
    iterator: AsyncGenerator[TurnNotice | TurnResult, None],
    first: TurnNotice | TurnResult,
) -> AsyncIterator[bytes]:
    try:
        yield _encode(first)
        async for item in iterator:
            yield _encode(item)
    finally:
        await iterator.aclose()


def _encode(item: TurnNotice | TurnResult) -> bytes:
    event, payload = _frame(item)
    data = json.dumps(payload, separators=(",", ":"))
    return f"event: {event}\ndata: {data}\n\n".encode()


def _notice_frame(item: TurnNotice) -> tuple[str, dict[str, object]]:
    frame = _stream_frame(item) or _interaction_frame(item) or _card_frame(item)
    if frame is None:
        return "error", {"status": "error", "reply": "", "error": FAILED_TURN}
    return frame


def _stream_frame(item: TurnNotice) -> tuple[str, dict[str, object]] | None:
    """Tokens, tool rows and approvals."""
    if isinstance(item, Token):
        return "token", {"text": item.text}
    if isinstance(item, ToolCallNotice):
        return "tool_call", {"name": item.name, "arguments": item.arguments}
    if isinstance(item, ToolResultNotice):
        return "tool_result", {"name": item.name, "content": item.content}
    if isinstance(item, ApprovalNotice):
        return "approval_required", {
            "approval_id": item.approval_id,
            "name": item.name,
            "arguments": item.arguments,
        }
    return None


def _interaction_frame(item: TurnNotice) -> tuple[str, dict[str, object]] | None:
    """Usage, who answers, and notices for the reader."""
    if isinstance(item, UsageNotice):
        return "usage", {
            "input_tokens": item.input_tokens,
            "context_window": item.context_window,
        }
    if isinstance(item, AgentNotice):
        return "agent", {
            "type": "agent",
            "agent_id": item.agent_id,
            "name": item.name,
            "emoji": item.emoji,
            "model": item.model,
        }
    if isinstance(item, WarningNotice):
        return "notice", {"text": item.text}
    return None


def _card_frame(item: TurnNotice) -> tuple[str, dict[str, object]] | None:
    """Question and progress cards."""
    if isinstance(item, ProgressNotice):
        steps = [{"label": label, "status": status} for label, status in item.steps]
        return "progress", {"type": "progress", "task_id": item.task_id, "steps": steps}
    if isinstance(item, QuestionNotice):
        return "question", {
            "question_id": item.question_id,
            "question": item.question,
            "options": list(item.options),
            "default": item.default,
            "multi": item.multi,
        }
    return None


def _frame(item: TurnNotice | TurnResult) -> tuple[str, dict[str, object]]:
    if isinstance(item, TurnNotice):
        return _notice_frame(item)
    if item.status == "ok":
        return "done", {"status": "ok", "reply": item.reply}
    if item.status == "pending_approval":
        return "done", {
            "status": "pending_approval",
            "reply": item.reply,
            "approval_id": item.approval_id or "",
        }
    return "error", {"status": "error", "reply": "", "error": item.error or FAILED_TURN}
