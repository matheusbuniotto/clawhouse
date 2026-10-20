"""Tool approval and interactive question resolution routes."""

from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from clawhouse.agent.turn import (
    BUSY_TURN,
    Answer,
    canonical_session_id,
    iter_resume_turn,
    resume_turn,
)
from clawhouse.api.identity import Caller
from clawhouse.api.routes.sessions import _build_turn_context, _first_item, _require_caller
from clawhouse.api.schemas import (
    AnswerIn,
    AnswerOut,
    ApprovalActionOut,
    ApprovalOut,
    ApprovalsListOut,
    QuestionOut,
)
from clawhouse.api.sse import SSE_HEADERS, _frames
from clawhouse.capabilities.interaction import ASK_USER, InvalidAnswer, Question, check_answer
from clawhouse.store.shapes import ApprovalEntry
from clawhouse.store.store import (
    ApprovalAlreadyResolved,
    ApprovalForbidden,
    ApprovalNotFound,
    RunInProgress,
    SessionForbidden,
    SessionStore,
)


def _approval_out(entry: ApprovalEntry) -> ApprovalOut:
    return ApprovalOut(
        id=entry.id,
        session_id=entry.session_id,
        run_id=entry.run_id,
        tool_name=entry.tool_name,
        tool_call_id=entry.tool_call_id,
        arguments=entry.arguments,
        status=entry.status,
        created_at=entry.created_at.isoformat(),
        resolved_at=entry.resolved_at.isoformat() if entry.resolved_at else None,
        resolved_by=entry.resolved_by,
    )


def _question_out(entry: ApprovalEntry) -> QuestionOut:
    asked = Question.from_arguments(entry.arguments)
    return QuestionOut(
        id=entry.id,
        session_id=entry.session_id,
        question=asked.question,
        options=list(asked.options),
        default=asked.default,
        multi=asked.multi,
        status=entry.status,
    )


async def _pending_questions(
    store: SessionStore, owner_id: str, session_id: str
) -> list[QuestionOut]:
    pending = await store.list_approvals(owner_id, status="pending")
    return [
        _question_out(entry)
        for entry in reversed(pending)
        if entry.tool_name == ASK_USER and entry.session_id == session_id
    ]


async def _answer_and_resume(
    request: Request,
    question_id: str,
    selected: list[str],
    caller: Caller,
) -> AnswerOut:
    store: SessionStore = request.app.state.store
    try:
        entry = await store.get_approval(question_id)
    except ApprovalNotFound as exc:
        raise HTTPException(status_code=404, detail="Question not found.") from exc
    if entry.tool_name != ASK_USER:
        raise HTTPException(status_code=404, detail="Question not found.")
    if entry.status != "pending":
        raise HTTPException(status_code=409, detail="Question already answered.")
    try:
        picked = check_answer(Question.from_arguments(entry.arguments), selected)
    except InvalidAnswer as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        resumed = await resume_turn(
            session_id=entry.session_id,
            approval_id=question_id,
            decision=Answer(selected=picked),
            ctx=_build_turn_context(request, caller),
        )
    except (SessionForbidden, ApprovalForbidden) as exc:
        raise HTTPException(status_code=403, detail="You do not own this session.") from exc
    except ApprovalAlreadyResolved as exc:
        raise HTTPException(status_code=409, detail="Question already answered.") from exc
    except RunInProgress as exc:
        raise HTTPException(status_code=409, detail=BUSY_TURN) from exc
    return AnswerOut(
        status=resumed.status,
        reply=resumed.reply,
        question=_question_out(await store.get_approval(question_id)),
        pending=await _pending_questions(store, caller.user_id, entry.session_id),
    )


async def _resolve_and_resume(
    request: Request,
    approval_id: str,
    decision: Literal["approved", "denied"],
    caller: Caller,
) -> ApprovalActionOut:
    store: SessionStore = request.app.state.store
    try:
        approval = await store.get_approval(approval_id)
    except ApprovalNotFound as exc:
        raise HTTPException(status_code=404, detail="Approval not found.") from exc

    if approval.status != "pending":
        raise HTTPException(status_code=409, detail="Approval already resolved.")
    if approval.tool_name == ASK_USER:
        raise HTTPException(status_code=409, detail="Questions are answered on their card.")

    ctx = _build_turn_context(request, caller)
    try:
        resumed = await resume_turn(
            session_id=approval.session_id,
            approval_id=approval_id,
            decision=decision,
            ctx=ctx,
        )
    except (SessionForbidden, ApprovalForbidden) as exc:
        raise HTTPException(status_code=403, detail="You do not own this session.") from exc
    except ApprovalAlreadyResolved as exc:
        raise HTTPException(status_code=409, detail="Approval already resolved.") from exc
    except RunInProgress as exc:
        raise HTTPException(status_code=409, detail=BUSY_TURN) from exc

    updated = await store.get_approval(approval_id)
    return ApprovalActionOut(
        status=resumed.status,
        reply=resumed.reply,
        approval=_approval_out(updated),
    )


async def _stream_resolve(
    request: Request,
    approval_id: str,
    decision: Literal["approved", "denied"],
    caller: Caller,
) -> Response:
    store: SessionStore = request.app.state.store
    try:
        approval = await store.get_approval(approval_id)
    except ApprovalNotFound as exc:
        raise HTTPException(status_code=404, detail="Approval not found.") from exc

    if approval.status != "pending":
        raise HTTPException(status_code=409, detail="Approval already resolved.")
    if approval.tool_name == ASK_USER:
        raise HTTPException(status_code=409, detail="Questions are answered on their card.")

    ctx = _build_turn_context(request, caller)
    iterator = iter_resume_turn(
        session_id=approval.session_id,
        approval_id=approval_id,
        decision=decision,
        ctx=ctx,
    )
    first = await _first_item(iterator)
    if isinstance(first, JSONResponse):
        return first
    return StreamingResponse(
        _frames(iterator, first),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


async def _stream_answer(
    request: Request,
    question_id: str,
    selected: list[str],
    caller: Caller,
) -> Response:
    store: SessionStore = request.app.state.store
    try:
        entry = await store.get_approval(question_id)
    except ApprovalNotFound as exc:
        raise HTTPException(status_code=404, detail="Question not found.") from exc
    if entry.tool_name != ASK_USER:
        raise HTTPException(status_code=404, detail="Question not found.")
    if entry.status != "pending":
        raise HTTPException(status_code=409, detail="Question already answered.")
    try:
        picked = check_answer(Question.from_arguments(entry.arguments), selected)
    except InvalidAnswer as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    ctx = _build_turn_context(request, caller)
    iterator = iter_resume_turn(
        session_id=entry.session_id,
        approval_id=question_id,
        decision=Answer(selected=picked),
        ctx=ctx,
    )
    first = await _first_item(iterator)
    if isinstance(first, JSONResponse):
        return first
    return StreamingResponse(
        _frames(iterator, first),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


async def _handle_approval_decision(
    request: Request,
    approval_id: str,
    decision: Literal["approved", "denied"],
    caller: Caller,
) -> Response | ApprovalActionOut:
    if "text/event-stream" in request.headers.get("accept", ""):
        return await _stream_resolve(request, approval_id, decision, caller)
    return await _resolve_and_resume(request, approval_id, decision, caller)


def _approval_routes(app: FastAPI) -> None:
    @app.get("/api/approvals")
    async def list_approvals(
        request: Request,
        caller: Caller = _require_caller,
    ) -> ApprovalsListOut:
        entries = await request.app.state.store.list_approvals(caller.user_id)
        out = [_approval_out(entry) for entry in entries if entry.tool_name != ASK_USER]
        pending = [a for a in out if a.status == "pending"]
        history = [a for a in out if a.status != "pending"]
        return ApprovalsListOut(approvals=out, pending=pending, history=history)

    @app.post("/api/approvals/{approval_id}/approve", response_model=None)
    async def approve_tool(
        approval_id: str,
        request: Request,
        caller: Caller = _require_caller,
    ) -> Response | ApprovalActionOut:
        return await _handle_approval_decision(request, approval_id, "approved", caller)

    @app.post("/api/approvals/{approval_id}/deny", response_model=None)
    async def deny_tool(
        approval_id: str,
        request: Request,
        caller: Caller = _require_caller,
    ) -> Response | ApprovalActionOut:
        return await _handle_approval_decision(request, approval_id, "denied", caller)


def _question_routes(app: FastAPI) -> None:
    @app.get("/api/sessions/{session_id}/questions")
    async def pending_questions_endpoint(
        session_id: str,
        request: Request,
        caller: Caller = _require_caller,
    ) -> list[QuestionOut]:
        canonical = canonical_session_id(session_id)
        return await _pending_questions(request.app.state.store, caller.user_id, canonical)

    @app.post("/api/questions/{question_id}/answer", response_model=None)
    async def answer_question(
        question_id: str,
        body: AnswerIn,
        request: Request,
        caller: Caller = _require_caller,
    ) -> Response | AnswerOut:
        if "text/event-stream" in request.headers.get("accept", ""):
            return await _stream_answer(request, question_id, body.selected, caller)
        return await _answer_and_resume(request, question_id, body.selected, caller)
