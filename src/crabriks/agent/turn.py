"""One serialized chat turn: prompt, tool dispatch, guardrails, and transcript persistence."""

import asyncio
import logging
from collections.abc import AsyncGenerator, AsyncIterable, AsyncIterator, Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic_ai import DeferredToolRequests, RunContext
from pydantic_ai.messages import (
    AgentStreamEvent,
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    ModelResponse,
    PartDeltaEvent,
    PartStartEvent,
    TextPart,
    TextPartDelta,
    ToolCallPart,
)
from pydantic_ai.models import Model
from pydantic_ai.tools import DeferredToolResults, ToolApproved, ToolDenied
from pydantic_ai.toolsets import AbstractToolset, ApprovalRequiredToolset

from crabriks.agent.core import TurnDeps, crabriks_agent, format_utc
from crabriks.agent.history import to_model_messages
from crabriks.agent.prompt import (
    BUILTIN_TOOLS,
    RuntimeMeta,
    SystemPrompt,
    ToolCard,
    build_system_prompt,
)
from crabriks.capabilities.bootstrap import BootstrapContext, load_bootstrap
from crabriks.capabilities.mcp import MCPServerConfig, load_mcp_tools, scrub_token
from crabriks.capabilities.skills import SkillsCache, SkillsCatalog, load_skills
from crabriks.capabilities.workspace import WorkspacePaths
from crabriks.store.shapes import ApprovalEntry, TranscriptEntry, TurnResult, TurnStatus
from crabriks.store.store import (
    ApprovalForbidden,
    ApprovalPending,
    RunInProgress,
    SessionForbidden,
    SessionStore,
)

logger = logging.getLogger("crabriks.turn")

FAILED_TURN = "The turn failed before a reply was completed."
BUSY_TURN = "A turn is already running for this session."


class InvalidSessionId(Exception):
    """Session ids are UUIDs."""


class _End:
    """Marks the end of the notice queue. Not a stream event."""


_END = _End()


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


TurnNotice = Token | ToolCallNotice | ToolResultNotice | ApprovalNotice
Emit = Callable[[TurnNotice], Awaitable[None]]
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
    skills_cache: SkillsCache | None = None
    mcp_servers: tuple[MCPServerConfig, ...] = ()
    user_token: str = ""
    mcp_toolset_factory: MCPToolsetFactory | None = None
    sensitive_tools: tuple[str, ...] = ()


def canonical_session_id(value: str) -> str:
    try:
        return str(UUID(value))
    except ValueError as exc:
        raise InvalidSessionId(value) from exc


async def run_turn(session_id: str, user_message: str, *, ctx: TurnContext) -> TurnResult:
    """Run one turn. A second in-flight run on the same session raises `RunInProgress`."""
    result: TurnResult | None = None
    async for item in iter_turn(session_id, user_message, ctx=ctx):
        if isinstance(item, TurnResult):
            result = item
    if result is None:
        raise RuntimeError("turn produced no result")
    return result


async def resume_turn(
    session_id: str,
    approval_id: str,
    decision: Literal["approved", "denied"],
    *,
    ctx: TurnContext,
) -> TurnResult:
    """Resume a turn paused for approval."""
    result: TurnResult | None = None
    async for item in iter_resume_turn(session_id, approval_id, decision, ctx=ctx):
        if isinstance(item, TurnResult):
            result = item
    if result is None:
        raise RuntimeError("resume turn produced no result")
    return result


@dataclass(frozen=True, slots=True)
class _Claimed:
    session_id: str
    user_message: str
    run_id: str
    ctx: TurnContext


async def iter_turn(
    session_id: str,
    user_message: str,
    *,
    ctx: TurnContext,
) -> AsyncGenerator[TurnNotice | TurnResult, None]:
    """Yield stream notices, release the run lock, then yield the terminal result."""
    claimed = await _claim(canonical_session_id(session_id), user_message, ctx)
    queue: _Queue = asyncio.Queue()
    holder: list[TurnResult] = []
    task = asyncio.create_task(_worker(claimed, queue, holder))
    try:
        async for notice in _drain(queue):
            yield notice
    finally:
        await _stop(task)
        await claimed.ctx.store.finish_run(claimed.session_id, claimed.run_id, _status(holder))
    if not holder:
        holder.append(await _error_result(claimed.session_id, claimed.ctx))
    res = holder[0]
    token = claimed.ctx.user_token
    if token and res.error and token in res.error:
        res = replace(res, error=scrub_token(res.error, token))
    yield res


async def iter_resume_turn(
    session_id: str,
    approval_id: str,
    decision: Literal["approved", "denied"],
    *,
    ctx: TurnContext,
) -> AsyncGenerator[TurnNotice | TurnResult, None]:
    """Resume turn execution after human decision."""
    claimed = await _claim_resume(session_id, approval_id, decision, ctx)
    approval = await ctx.store.get_approval(approval_id)
    queue: _Queue = asyncio.Queue()
    holder: list[TurnResult] = []
    task = asyncio.create_task(
        _worker_resume(claimed, approval, decision, queue=queue, holder=holder)
    )
    try:
        async for notice in _drain(queue):
            yield notice
    finally:
        await _stop(task)
        await claimed.ctx.store.finish_run(claimed.session_id, claimed.run_id, _status(holder))
    if not holder:
        holder.append(await _error_result(claimed.session_id, claimed.ctx))
    res = holder[0]
    token = claimed.ctx.user_token
    if token and res.error and token in res.error:
        res = replace(res, error=scrub_token(res.error, token))
    yield res


async def _claim(session_id: str, user_message: str, ctx: TurnContext) -> _Claimed:
    await ctx.store.open_session(session_id, ctx.owner_id)
    run_id = await ctx.store.claim_run(session_id)
    return _Claimed(
        session_id=session_id,
        user_message=user_message,
        run_id=run_id,
        ctx=ctx,
    )


async def _claim_resume(
    session_id: str,
    approval_id: str,
    decision: Literal["approved", "denied"],
    ctx: TurnContext,
) -> _Claimed:
    canonical = canonical_session_id(session_id)
    approval = await ctx.store.get_approval(approval_id)
    if approval.session_id != canonical:
        raise ApprovalForbidden(approval_id)
    await ctx.store.open_session(canonical, ctx.owner_id)
    await ctx.store.resolve_approval(approval_id, decision, ctx.owner_id, ctx.now())
    run_id = await ctx.store.claim_run(canonical)
    return _Claimed(
        session_id=canonical,
        user_message="",
        run_id=run_id,
        ctx=ctx,
    )


async def _worker(claimed: _Claimed, queue: _Queue, holder: list[TurnResult]) -> None:
    try:
        holder.append(await _run_model(claimed, queue))
    except Exception as exc:  # noqa: BLE001 — a failed turn is an empty reply, never a partial one
        # Model failures can echo request headers. Log the type only.
        logger.error("turn failed: %s", type(exc).__name__)  # noqa: TRY400
        holder.append(await _error_result(claimed.session_id, claimed.ctx))
    finally:
        await queue.put(_END)


async def _worker_resume(
    claimed: _Claimed,
    approval: ApprovalEntry,
    decision: Literal["approved", "denied"],
    *,
    queue: _Queue,
    holder: list[TurnResult],
) -> None:
    try:
        holder.append(await _run_model_resume(claimed, approval, decision, queue))
    except Exception as exc:  # noqa: BLE001
        logger.error("resume turn failed: %s", type(exc).__name__)  # noqa: TRY400
        holder.append(await _error_result(claimed.session_id, claimed.ctx))
    finally:
        await queue.put(_END)


async def _drain(queue: _Queue) -> AsyncIterator[TurnNotice]:
    while True:
        item = await queue.get()
        if isinstance(item, _End):
            return
        yield item


async def _stop(task: asyncio.Task[None]) -> None:
    if task.done():
        return
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


def _status(holder: list[TurnResult]) -> TurnStatus:
    if not holder:
        return "error"
    return holder[0].status


def _skills_for_session(claimed: _Claimed) -> SkillsCatalog:
    if claimed.ctx.skills_cache is not None:
        return claimed.ctx.skills_cache.get_or_discover(claimed.session_id, claimed.ctx.workspace)
    skills_dir = claimed.ctx.workspace.skills if claimed.ctx.workspace else None
    return load_skills(skills_dir)


def _wrap_toolsets(
    toolsets: tuple[AbstractToolset[object], ...] | tuple[()],
    sensitive_tools: tuple[str, ...],
) -> tuple[AbstractToolset[object], ...]:
    if not toolsets or not sensitive_tools:
        return toolsets
    return tuple(
        ApprovalRequiredToolset(
            ts,
            approval_required_func=lambda _ctx, tdef, _args: tdef.name in sensitive_tools,
        )
        for ts in toolsets
    )


def _prompt_for(claimed: _Claimed, skills: SkillsCatalog, mcp_bundle: object) -> SystemPrompt:
    ctx = claimed.ctx
    tools_list = getattr(mcp_bundle, "tools", ())
    mcp_cards = tuple(ToolCard(name=t.safe_name, description=t.description) for t in tools_list)
    return build_system_prompt(
        tools=(*BUILTIN_TOOLS, *mcp_cards),
        runtime=RuntimeMeta(session_id=claimed.session_id, time=format_utc(ctx.now())),
        bootstrap=_bootstrap(ctx),
        workspace=ctx.workspace,
        skills=skills.cards(),
    )


async def _run_model(claimed: _Claimed, queue: _Queue) -> TurnResult:
    ctx = claimed.ctx
    prior = await ctx.store.transcript(claimed.session_id, ctx.owner_id)
    await _append_user(claimed)
    skills = _skills_for_session(claimed)
    mcp_bundle = await load_mcp_tools(
        ctx.mcp_servers,
        ctx.user_token,
        toolset_factory=ctx.mcp_toolset_factory,
    )
    prompt = _prompt_for(claimed, skills, mcp_bundle)
    toolsets = _wrap_toolsets(mcp_bundle.toolsets, ctx.sensitive_tools)
    result = await crabriks_agent().run(
        claimed.user_message,
        message_history=to_model_messages(prior) or None,
        model=ctx.model,
        instructions=prompt.text,
        deps=TurnDeps(now=ctx.now, skills=skills, sensitive_tools=ctx.sensitive_tools),
        event_stream_handler=_persist_and_emit(claimed, queue),
        toolsets=toolsets or None,
    )
    if isinstance(result.output, DeferredToolRequests):
        return await _handle_deferred_approvals(claimed, queue, result.output)
    raw_reply = result.output if isinstance(result.output, str) else str(result.output)
    reply = scrub_token(raw_reply, ctx.user_token) if ctx.user_token else raw_reply
    await _append(claimed, TranscriptEntry(role="assistant", content=reply))
    transcript = await ctx.store.transcript(claimed.session_id, ctx.owner_id)
    return TurnResult(
        session_id=claimed.session_id,
        status="ok",
        reply=reply,
        error=None,
        transcript=transcript,
    )


async def _run_model_resume(
    claimed: _Claimed,
    approval: ApprovalEntry,
    decision: Literal["approved", "denied"],
    queue: _Queue,
) -> TurnResult:
    ctx = claimed.ctx
    prior = await ctx.store.transcript(claimed.session_id, ctx.owner_id)
    skills = _skills_for_session(claimed)
    mcp_bundle = await load_mcp_tools(
        ctx.mcp_servers,
        ctx.user_token,
        toolset_factory=ctx.mcp_toolset_factory,
    )
    prompt = _prompt_for(claimed, skills, mcp_bundle)
    toolsets = _wrap_toolsets(mcp_bundle.toolsets, ctx.sensitive_tools)
    history = to_model_messages(prior)
    call_args = approval.arguments
    if ctx.user_token and "[REDACTED]" in call_args:
        call_args = call_args.replace("[REDACTED]", ctx.user_token)
    history.append(
        ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name=approval.tool_name,
                    args=call_args,
                    tool_call_id=approval.tool_call_id,
                )
            ]
        )
    )
    deferred_results = _deferred_results(approval, decision)
    result = await crabriks_agent().run(
        message_history=history,
        deferred_tool_results=deferred_results,
        model=ctx.model,
        instructions=prompt.text,
        deps=TurnDeps(now=ctx.now, skills=skills, sensitive_tools=ctx.sensitive_tools),
        event_stream_handler=_persist_and_emit(
            claimed, queue, skip_tool_call_id=approval.tool_call_id
        ),
        toolsets=toolsets or None,
    )
    if isinstance(result.output, DeferredToolRequests):
        return await _handle_deferred_approvals(claimed, queue, result.output)
    raw_reply = result.output if isinstance(result.output, str) else str(result.output)
    reply = scrub_token(raw_reply, ctx.user_token) if ctx.user_token else raw_reply
    await _append(claimed, TranscriptEntry(role="assistant", content=reply))
    transcript = await ctx.store.transcript(claimed.session_id, ctx.owner_id)
    return TurnResult(
        session_id=claimed.session_id,
        status="ok",
        reply=reply,
        error=None,
        transcript=transcript,
    )


def _deferred_results(
    approval: ApprovalEntry,
    decision: Literal["approved", "denied"],
) -> DeferredToolResults:
    if decision == "approved":
        return DeferredToolResults(approvals={approval.tool_call_id: ToolApproved()})
    return DeferredToolResults(
        approvals={approval.tool_call_id: ToolDenied(message="The user denied the tool call.")}
    )


async def _handle_deferred_approvals(
    claimed: _Claimed,
    queue: _Queue,
    output: DeferredToolRequests,
) -> TurnResult:
    ctx = claimed.ctx
    first_id: str | None = None
    for call in output.approvals:
        raw_args = call.args_as_json_str()
        scrubbed = scrub_token(raw_args, ctx.user_token) if ctx.user_token else raw_args
        entry = await ctx.store.create_approval(
            session_id=claimed.session_id,
            run_id=claimed.run_id,
            tool_name=call.tool_name,
            tool_call_id=call.tool_call_id,
            arguments=scrubbed,
        )
        if first_id is None:
            first_id = entry.id
        notice = ApprovalNotice(
            approval_id=entry.id,
            name=call.tool_name,
            arguments=scrubbed,
            tool_call_id=call.tool_call_id,
        )
        await _publish(ctx, queue, notice)
    transcript = await ctx.store.transcript(claimed.session_id, ctx.owner_id)
    return TurnResult(
        session_id=claimed.session_id,
        status="pending_approval",
        reply="",
        error=None,
        transcript=transcript,
        approval_id=first_id,
    )


def _bootstrap(ctx: TurnContext) -> BootstrapContext | None:
    if ctx.workspace is None:
        return None
    return load_bootstrap(ctx.workspace)


async def _append_user(claimed: _Claimed) -> None:
    await _append(claimed, TranscriptEntry(role="user", content=claimed.user_message))


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


async def _append(claimed: _Claimed, entry: TranscriptEntry) -> None:
    scrubbed = _scrub_entry(entry, claimed.ctx.user_token)
    await claimed.ctx.store.append_entry(claimed.session_id, claimed.run_id, scrubbed)


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


def _persist_and_emit(
    claimed: _Claimed,
    queue: _Queue,
    *,
    skip_tool_call_id: str | None = None,
):
    async def handle(
        run_ctx: RunContext[TurnDeps],
        events: AsyncIterable[AgentStreamEvent],
    ) -> None:
        del run_ctx
        token = claimed.ctx.user_token
        async for event in events:
            notice = notice_from(event)
            if notice is None:
                continue
            if (
                skip_tool_call_id
                and isinstance(notice, ToolCallNotice)
                and notice.tool_call_id == skip_tool_call_id
            ):
                continue
            scrubbed = _scrub_notice(notice, token)
            await _record(claimed, scrubbed)
            await _publish(claimed.ctx, queue, scrubbed)

    return handle


async def _record(claimed: _Claimed, notice: TurnNotice) -> None:
    entry = entry_from(notice)
    if entry is None:
        return
    await _append(claimed, entry)


async def _publish(ctx: TurnContext, queue: _Queue, notice: TurnNotice) -> None:
    scrubbed = _scrub_notice(notice, ctx.user_token)
    await queue.put(scrubbed)
    if ctx.emit is not None:
        await ctx.emit(scrubbed)


async def _error_result(
    session_id: str,
    ctx: TurnContext,
    error: str = FAILED_TURN,
) -> TurnResult:
    transcript = await ctx.store.transcript(session_id, ctx.owner_id)
    scrubbed = scrub_token(error, ctx.user_token) if ctx.user_token else error
    return TurnResult(
        session_id=session_id,
        status="error",
        reply="",
        error=scrubbed,
        transcript=transcript,
    )


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


def _text_delta(event: object) -> str | None:
    if isinstance(event, PartStartEvent) and isinstance(event.part, TextPart):
        return event.part.content or None
    if isinstance(event, PartDeltaEvent) and isinstance(event.delta, TextPartDelta):
        return event.delta.content_delta or None
    return None


def _as_text(content: object) -> str:
    if isinstance(content, str):
        return content
    return str(content)


__all__ = [
    "BUSY_TURN",
    "FAILED_TURN",
    "ApprovalForbidden",
    "ApprovalNotice",
    "ApprovalPending",
    "InvalidSessionId",
    "RunInProgress",
    "SessionForbidden",
    "Token",
    "ToolCallNotice",
    "ToolResultNotice",
    "TurnContext",
    "TurnNotice",
    "iter_resume_turn",
    "iter_turn",
    "resume_turn",
    "run_turn",
]
