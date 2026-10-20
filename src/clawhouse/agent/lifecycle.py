"""Run claim locking, worker background detachment, and queue draining."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator, AsyncIterator, Coroutine
from contextlib import suppress
from dataclasses import replace
from typing import Any
from uuid import UUID

from clawhouse.agent.notices import (
    _END,
    Answer,
    Resolution,
    TurnContext,
    TurnNotice,
    TurnResult,
    _Claimed,
    _End,
    _Queue,
)
from clawhouse.agent.pauses import QUESTION_EXPIRED, _expire_questions
from clawhouse.agent.runner import _append, _run_model, _run_model_resume
from clawhouse.capabilities.mcp import scrub_token
from clawhouse.store.shapes import ApprovalEntry, TranscriptEntry, TurnStatus
from clawhouse.store.store import ApprovalForbidden
from clawhouse.telemetry import (
    async_flush_telemetry,
    record_turn_status,
    turn_span,
)

logger = logging.getLogger("clawhouse.turn")

FAILED_TURN = "The turn failed before a reply was completed."
BUSY_TURN = "A turn is already running for this session."

_RUNNING: dict[str, asyncio.Task[None]] = {}


class InvalidSessionId(Exception):
    """Session ids are UUIDs."""


def canonical_session_id(value: str) -> str:
    try:
        return str(UUID(value))
    except ValueError as exc:
        raise InvalidSessionId(value) from exc


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


def _status(holder: list[TurnResult]) -> TurnStatus:
    if not holder:
        return "error"
    return holder[0].status


async def _drain(queue: _Queue) -> AsyncIterator[TurnNotice]:
    while True:
        item = await queue.get()
        if isinstance(item, _End):
            return
        yield item


def _detach(
    claimed: _Claimed, work: Coroutine[Any, Any, None], holder: list[TurnResult]
) -> asyncio.Task[None]:
    async def run() -> None:
        try:
            await work
        except asyncio.CancelledError:
            logger.info("turn cancelled for session %s", claimed.session_id)
        finally:
            _RUNNING.pop(claimed.session_id, None)
            await claimed.ctx.store.finish_run(claimed.session_id, claimed.run_id, _status(holder))

    task = asyncio.create_task(run())
    _RUNNING[claimed.session_id] = task
    return task


async def cancel_turn(session_id: str) -> bool:
    """Stop the session's running turn (the Stop button). False when none is running here."""
    task = _RUNNING.get(canonical_session_id(session_id))
    if task is None or task.done():
        return False
    task.cancel()
    with suppress(asyncio.CancelledError):
        await asyncio.shield(task)
    return True


async def _worker(claimed: _Claimed, queue: _Queue, holder: list[TurnResult]) -> None:
    with turn_span(claimed.session_id, claimed.ctx.owner_id, claimed.run_id):
        try:
            res = await _run_model(claimed, queue)
            record_turn_status(res.status)
            holder.append(res)
        except Exception as exc:  # noqa: BLE001
            logger.error("turn failed: %s", type(exc).__name__)  # noqa: TRY400
            record_turn_status("error", exc)
            holder.append(await _error_result(claimed.session_id, claimed.ctx))
        finally:
            await queue.put(_END)
            await async_flush_telemetry()


async def _worker_resume(
    claimed: _Claimed,
    approval: ApprovalEntry,
    decision: Resolution,
    *,
    queue: _Queue,
    holder: list[TurnResult],
) -> None:
    with turn_span(claimed.session_id, claimed.ctx.owner_id, claimed.run_id):
        try:
            res = await _run_model_resume(claimed, approval, decision, queue)
            record_turn_status(res.status)
            holder.append(res)
        except Exception as exc:  # noqa: BLE001
            logger.error("resume turn failed: %s", type(exc).__name__)  # noqa: TRY400
            record_turn_status("error", exc)
            holder.append(await _error_result(claimed.session_id, claimed.ctx))
        finally:
            await queue.put(_END)
            await async_flush_telemetry()


async def _claim(session_id: str, user_message: str, ctx: TurnContext) -> _Claimed:
    await ctx.store.open_session(session_id, ctx.owner_id)
    expired = await _expire_questions(session_id, ctx)
    run_id = await ctx.store.claim_run(session_id)
    claimed = _Claimed(
        session_id=session_id,
        user_message=user_message,
        run_id=run_id,
        ctx=ctx,
    )
    for _ in range(expired):
        await _append(claimed, TranscriptEntry(role="notice", content=QUESTION_EXPIRED))
    return claimed


async def _claim_resume(
    session_id: str,
    approval_id: str,
    decision: Resolution,
    ctx: TurnContext,
) -> _Claimed:
    canonical = canonical_session_id(session_id)
    approval = await ctx.store.get_approval(approval_id)
    if approval.session_id != canonical:
        raise ApprovalForbidden(approval_id)
    await ctx.store.open_session(canonical, ctx.owner_id)
    status = "approved" if isinstance(decision, Answer) else decision
    await ctx.store.resolve_approval(approval_id, status, ctx.owner_id, ctx.now())
    run_id = await ctx.store.claim_run(canonical)
    return _Claimed(
        session_id=canonical,
        user_message="",
        run_id=run_id,
        ctx=ctx,
    )


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
    task = _detach(claimed, _worker(claimed, queue, holder), holder)
    async for notice in _drain(queue):
        yield notice
    await asyncio.shield(task)
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
    decision: Resolution,
    *,
    ctx: TurnContext,
) -> AsyncGenerator[TurnNotice | TurnResult, None]:
    """Resume turn execution after human decision."""
    claimed = await _claim_resume(session_id, approval_id, decision, ctx)
    approval = await ctx.store.get_approval(approval_id)
    queue: _Queue = asyncio.Queue()
    holder: list[TurnResult] = []
    task = _detach(
        claimed, _worker_resume(claimed, approval, decision, queue=queue, holder=holder), holder
    )
    async for notice in _drain(queue):
        yield notice
    await asyncio.shield(task)
    if not holder:
        holder.append(await _error_result(claimed.session_id, claimed.ctx))
    res = holder[0]
    token = claimed.ctx.user_token
    if token and res.error and token in res.error:
        res = replace(res, error=scrub_token(res.error, token))
    yield res


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
    decision: Resolution,
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


__all__ = [
    "BUSY_TURN",
    "FAILED_TURN",
    "InvalidSessionId",
    "_Claimed",
    "_End",
    "_Queue",
    "_claim",
    "_claim_resume",
    "_detach",
    "_drain",
    "_status",
    "_worker",
    "_worker_resume",
    "cancel_turn",
    "canonical_session_id",
    "iter_resume_turn",
    "iter_turn",
    "resume_turn",
    "run_turn",
]
