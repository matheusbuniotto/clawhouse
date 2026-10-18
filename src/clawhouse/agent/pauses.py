"""Approval and question pause/resume handlers and sensitive tool guardrails."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta

from pydantic_ai import DeferredToolRequests
from pydantic_ai.messages import ToolCallPart
from pydantic_ai.tools import DeferredToolResults, ToolApproved, ToolDenied
from pydantic_ai_harness.guardrails import GuardrailResult, ToolCallInfo, ToolGuardrail

from clawhouse.agent.core import TurnDeps
from clawhouse.agent.events import _publish
from clawhouse.agent.notices import (
    Answer,
    ApprovalNotice,
    QuestionNotice,
    Resolution,
    TurnContext,
    TurnResult,
    _Claimed,
    _Queue,
)
from clawhouse.capabilities.databricks import is_readonly_query
from clawhouse.capabilities.interaction import ASK_USER, Question, answer_text
from clawhouse.capabilities.mcp import scrub_token
from clawhouse.store.shapes import ApprovalEntry

QUESTION_TTL = timedelta(hours=24)
QUESTION_EXPIRED = "Pergunta encerrada sem resposta depois de 24h."

DEFAULT_APPROVAL_REQUIRED_TOOLS = frozenset(
    {
        "jobs_run_now",
        "jobs_cancel_run",
        "jobs_create",
        "jobs_edit",
        "jobs_delete",
        "delivery_send_webhook",
        "create_google_sheet",
        "update_google_sheet",
        "run_python_analysis",
    }
)


def sensitive_tool_guard(names: frozenset[str] = frozenset()) -> ToolGuardrail[TurnDeps]:
    """Defer every sensitive or mutating tool through the harness-native approval flow."""
    sensitive = DEFAULT_APPROVAL_REQUIRED_TOOLS | names

    def guard(call: ToolCallInfo) -> GuardrailResult:
        if call.name in sensitive:
            return GuardrailResult.approve()
        if call.name == "dbsql_query":
            args = call.args if isinstance(call.args, Mapping) else {}
            if not is_readonly_query(str(args.get("query", ""))):
                return GuardrailResult.approve()
        return GuardrailResult.allow()

    return ToolGuardrail(guard=guard)


_sensitive_tool_guard = sensitive_tool_guard


async def _expire_questions(session_id: str, ctx: TurnContext) -> int:
    """Close questions nobody answered in `QUESTION_TTL`, so the session is not stuck."""
    pending = await ctx.store.list_approvals(ctx.owner_id, status="pending")
    cutoff = ctx.now() - QUESTION_TTL
    stale = [
        entry
        for entry in pending
        if entry.session_id == session_id
        and entry.tool_name == ASK_USER
        and entry.created_at < cutoff
    ]
    for entry in stale:
        await ctx.store.resolve_approval(entry.id, "denied", "system:expired", ctx.now())
    return len(stale)


def _deferred_results(
    approval: ApprovalEntry,
    decision: Resolution,
) -> DeferredToolResults:
    if isinstance(decision, Answer):
        return DeferredToolResults(calls={approval.tool_call_id: answer_text(decision.selected)})
    if decision == "approved":
        return DeferredToolResults(approvals={approval.tool_call_id: ToolApproved()})
    return DeferredToolResults(
        approvals={approval.tool_call_id: ToolDenied(message="The user denied the tool call.")}
    )


async def _pause_record(claimed: _Claimed, call: ToolCallPart) -> tuple[str, str]:
    ctx = claimed.ctx
    raw_args = call.args_as_json_str()
    scrubbed = scrub_token(raw_args, ctx.user_token) if ctx.user_token else raw_args
    entry = await ctx.store.create_approval(
        session_id=claimed.session_id,
        run_id=claimed.run_id,
        tool_name=call.tool_name,
        tool_call_id=call.tool_call_id,
        arguments=scrubbed,
    )
    return entry.id, scrubbed


async def _pause_for_approval(claimed: _Claimed, queue: _Queue, call: ToolCallPart) -> str:
    approval_id, arguments = await _pause_record(claimed, call)
    notice = ApprovalNotice(
        approval_id=approval_id,
        name=call.tool_name,
        arguments=arguments,
        tool_call_id=call.tool_call_id,
    )
    await _publish(claimed.ctx, queue, notice)
    return approval_id


async def _pause_for_question(claimed: _Claimed, queue: _Queue, call: ToolCallPart) -> str:
    """A question pauses like an approval: same row, same lock on the session."""
    question_id, arguments = await _pause_record(claimed, call)
    asked = Question.from_arguments(arguments)
    notice = QuestionNotice(
        question_id=question_id,
        question=asked.question,
        options=asked.options,
        default=asked.default,
        multi=asked.multi,
        tool_call_id=call.tool_call_id,
    )
    await _publish(claimed.ctx, queue, notice)
    return question_id


async def _handle_deferred_approvals(
    claimed: _Claimed,
    queue: _Queue,
    output: DeferredToolRequests,
) -> TurnResult:
    ctx = claimed.ctx
    ids: list[str] = []
    for call in output.approvals:
        ids.append(await _pause_for_approval(claimed, queue, call))
    for call in output.calls:
        if call.tool_name == ASK_USER:
            ids.append(await _pause_for_question(claimed, queue, call))
    first_id = ids[0] if ids else None
    transcript = await ctx.store.transcript(claimed.session_id, ctx.owner_id)
    return TurnResult(
        session_id=claimed.session_id,
        status="pending_approval",
        reply="",
        error=None,
        transcript=transcript,
        approval_id=first_id,
    )


__all__ = [
    "DEFAULT_APPROVAL_REQUIRED_TOOLS",
    "QUESTION_EXPIRED",
    "QUESTION_TTL",
    "_deferred_results",
    "_expire_questions",
    "_handle_deferred_approvals",
    "_pause_for_approval",
    "_pause_for_question",
    "_pause_record",
    "_sensitive_tool_guard",
    "sensitive_tool_guard",
]
