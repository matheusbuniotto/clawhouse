"""Evaluations harness for worked-example traces through run_turn."""

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic_ai.messages import ModelMessage
from pydantic_ai.models import Model
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel
from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import EvaluationReason, Evaluator, EvaluatorContext
from pydantic_evals.reporting import EvaluationReport

from clawhouse.shapes import TranscriptEntry, TurnResult, TurnStatus
from clawhouse.store import MemorySessionStore
from clawhouse.turn import (
    FAILED_TURN,
    ToolCallNotice,
    ToolResultNotice,
    TurnContext,
    TurnNotice,
    run_turn,
)

EVAL_FROZEN_TIME = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)
EVAL_FROZEN_TIME_STR = "2026-10-11T12:00:00Z"


@dataclass(frozen=True, slots=True)
class ToolCallTrace:
    name: str
    arguments: str
    tool_call_id: str
    result: str


@dataclass(frozen=True, slots=True)
class WorkedExampleTrace:
    session_id: str
    status: TurnStatus
    reply: str
    error: str | None
    messages: tuple[str, ...]
    tool_calls: tuple[ToolCallTrace, ...]
    transcript: tuple[TranscriptEntry, ...]
    persisted_transcript: tuple[TranscriptEntry, ...]


@dataclass(frozen=True, slots=True)
class TurnEvalInput:
    session_id: str
    user_message: str
    owner_id: str
    model: Model
    now: Callable[[], datetime] | None = None


def _eval_attr_match(
    ctx: EvaluatorContext[TurnEvalInput, WorkedExampleTrace, object],
    attr_name: str,
    label: str,
) -> EvaluationReason:
    if ctx.expected_output is None:
        return EvaluationReason(value=False, reason="Missing expected_output")
    expected = getattr(ctx.expected_output, attr_name)
    actual = getattr(ctx.output, attr_name)
    if expected == actual:
        return EvaluationReason(value=True, reason=f"{label} matches exact sequence")
    return EvaluationReason(
        value=False,
        reason=f"{label} mismatch: expected {expected}, got {actual}",
    )


@dataclass(repr=False)
class ExactTranscriptMatch(Evaluator[TurnEvalInput, WorkedExampleTrace, object]):
    def evaluate(
        self, ctx: EvaluatorContext[TurnEvalInput, WorkedExampleTrace, object]
    ) -> EvaluationReason:
        if ctx.expected_output is None:
            return EvaluationReason(value=False, reason="Missing expected_output")
        if ctx.output.transcript != ctx.output.persisted_transcript:
            return EvaluationReason(
                value=False,
                reason="Persisted store transcript diverged from result transcript",
            )
        if ctx.output.transcript == ctx.expected_output.transcript:
            return EvaluationReason(
                value=True, reason="Transcript matches exact sequence and persisted effects"
            )
        expected_trans = ctx.expected_output.transcript
        actual_trans = ctx.output.transcript
        return EvaluationReason(
            value=False,
            reason=f"Transcript mismatch: expected {expected_trans}, got {actual_trans}",
        )


@dataclass(repr=False)
class ExactToolCallsMatch(Evaluator[TurnEvalInput, WorkedExampleTrace, object]):
    def evaluate(
        self, ctx: EvaluatorContext[TurnEvalInput, WorkedExampleTrace, object]
    ) -> EvaluationReason:
        return _eval_attr_match(ctx, "tool_calls", "Tool calls")


@dataclass(repr=False)
class ExactMessageSequenceMatch(Evaluator[TurnEvalInput, WorkedExampleTrace, object]):
    def evaluate(
        self, ctx: EvaluatorContext[TurnEvalInput, WorkedExampleTrace, object]
    ) -> EvaluationReason:
        if ctx.expected_output is None:
            return EvaluationReason(value=False, reason="Missing expected_output")
        messages_match = ctx.output.messages == ctx.expected_output.messages
        status_match = (
            ctx.output.status == ctx.expected_output.status
            and ctx.output.error == ctx.expected_output.error
        )
        if messages_match and status_match:
            return EvaluationReason(value=True, reason="Message sequence matches")
        exp_m, act_m = ctx.expected_output.messages, ctx.output.messages
        return EvaluationReason(
            value=False,
            reason=f"Message sequence mismatch: expected {exp_m}, got {act_m}",
        )


@dataclass(repr=False)
class ExactTraceMatch(Evaluator[TurnEvalInput, WorkedExampleTrace, object]):
    def evaluate(
        self, ctx: EvaluatorContext[TurnEvalInput, WorkedExampleTrace, object]
    ) -> EvaluationReason:
        if ctx.expected_output is None:
            return EvaluationReason(value=False, reason="Missing expected_output")
        if ctx.output == ctx.expected_output:
            return EvaluationReason(value=True, reason="Full worked-example trace matches")
        return EvaluationReason(
            value=False,
            reason=f"Trace mismatch: expected {ctx.expected_output}, got {ctx.output}",
        )


def _extract_tool_calls(notices: list[TurnNotice]) -> tuple[ToolCallTrace, ...]:
    calls: list[ToolCallTrace] = []
    call_notices = [n for n in notices if isinstance(n, ToolCallNotice)]
    result_map = {n.tool_call_id: n.content for n in notices if isinstance(n, ToolResultNotice)}

    for call in call_notices:
        calls.append(
            ToolCallTrace(
                name=call.name,
                arguments=call.arguments,
                tool_call_id=call.tool_call_id,
                result=result_map.get(call.tool_call_id, ""),
            )
        )
    return tuple(calls)


async def execute_turn_eval(inputs: TurnEvalInput) -> WorkedExampleTrace:
    store = MemorySessionStore()
    notices: list[TurnNotice] = []

    async def capture(notice: TurnNotice) -> None:
        notices.append(notice)

    ctx = TurnContext(
        owner_id=inputs.owner_id,
        store=store,
        model=inputs.model,
        now=inputs.now or (lambda: datetime.now(tz=UTC)),
        emit=capture,
    )

    result: TurnResult = await run_turn(inputs.session_id, inputs.user_message, ctx=ctx)
    tool_calls = _extract_tool_calls(notices)
    persisted = await store.transcript(inputs.session_id, inputs.owner_id)

    messages = (
        (inputs.user_message, result.reply) if result.status == "ok" else (inputs.user_message,)
    )

    return WorkedExampleTrace(
        session_id=result.session_id,
        status=result.status,
        reply=result.reply,
        error=result.error,
        messages=messages,
        tool_calls=tool_calls,
        transcript=result.transcript,
        persisted_transcript=persisted,
    )


def _clock_trace(call_id: str) -> tuple[ToolCallTrace, ...]:
    return (
        ToolCallTrace(
            name="clock",
            arguments="{}",
            tool_call_id=call_id,
            result=EVAL_FROZEN_TIME_STR,
        ),
    )


def _clock_transcript(user_msg: str, call_id: str) -> tuple[TranscriptEntry, ...]:
    return (
        TranscriptEntry(role="user", content=user_msg),
        TranscriptEntry(role="tool_call", content="{}", tool_name="clock", tool_call_id=call_id),
        TranscriptEntry(
            role="tool_result",
            content=EVAL_FROZEN_TIME_STR,
            tool_name="clock",
            tool_call_id=call_id,
        ),
    )


def _success_case() -> Case[TurnEvalInput, WorkedExampleTrace, object]:
    session_id = "00000000-0000-4000-8000-000000000001"
    user_msg = "ping"
    reply_msg = "pong"

    async def ping_model(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str]:
        del messages, info
        yield reply_msg

    trans = (
        TranscriptEntry(role="user", content=user_msg),
        TranscriptEntry(role="assistant", content=reply_msg),
    )

    return Case(
        name="success_turn_direct_reply",
        inputs=TurnEvalInput(
            session_id=session_id,
            user_message=user_msg,
            owner_id="evals@example.com",
            model=FunctionModel(stream_function=ping_model),
            now=lambda: EVAL_FROZEN_TIME,
        ),
        expected_output=WorkedExampleTrace(
            session_id=session_id,
            status="ok",
            reply=reply_msg,
            error=None,
            messages=(user_msg, reply_msg),
            tool_calls=(),
            transcript=trans,
            persisted_transcript=trans,
        ),
    )


def _tool_call_case() -> Case[TurnEvalInput, WorkedExampleTrace, object]:
    session_id = "00000000-0000-4000-8000-000000000002"
    user_msg = "what time is it?"
    call_id = "call-clock-eval"
    reply_msg = f"The time is {EVAL_FROZEN_TIME_STR}"

    async def clock_model(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        del info
        has_return = any(part.part_kind == "tool-return" for msg in messages for part in msg.parts)
        if not has_return:
            yield {0: DeltaToolCall(name="clock", json_args="{}", tool_call_id=call_id)}
            return
        yield reply_msg

    trans = (
        *_clock_transcript(user_msg, call_id),
        TranscriptEntry(role="assistant", content=reply_msg),
    )

    return Case(
        name="tool_call_clock_turn",
        inputs=TurnEvalInput(
            session_id=session_id,
            user_message=user_msg,
            owner_id="evals@example.com",
            model=FunctionModel(stream_function=clock_model),
            now=lambda: EVAL_FROZEN_TIME,
        ),
        expected_output=WorkedExampleTrace(
            session_id=session_id,
            status="ok",
            reply=reply_msg,
            error=None,
            messages=(user_msg, reply_msg),
            tool_calls=_clock_trace(call_id),
            transcript=trans,
            persisted_transcript=trans,
        ),
    )


def _immediate_error_case() -> Case[TurnEvalInput, WorkedExampleTrace, object]:
    session_id = "00000000-0000-4000-8000-000000000003"
    user_msg = "failing query"

    async def fail_model(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str]:
        del messages, info
        for _ in ():
            yield ""
        raise RuntimeError("Model execution failed")

    trans = (TranscriptEntry(role="user", content=user_msg),)

    return Case(
        name="error_turn_immediate_failure",
        inputs=TurnEvalInput(
            session_id=session_id,
            user_message=user_msg,
            owner_id="evals@example.com",
            model=FunctionModel(stream_function=fail_model),
            now=lambda: EVAL_FROZEN_TIME,
        ),
        expected_output=WorkedExampleTrace(
            session_id=session_id,
            status="error",
            reply="",
            error=FAILED_TURN,
            messages=(user_msg,),
            tool_calls=(),
            transcript=trans,
            persisted_transcript=trans,
        ),
    )


def _after_tool_error_case() -> Case[TurnEvalInput, WorkedExampleTrace, object]:
    session_id = "00000000-0000-4000-8000-000000000004"
    user_msg = "time then fail"
    call_id = "call-clock-err"

    async def fail_after_clock(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        del info
        has_return = any(part.part_kind == "tool-return" for msg in messages for part in msg.parts)
        if not has_return:
            yield {0: DeltaToolCall(name="clock", json_args="{}", tool_call_id=call_id)}
            return
        raise RuntimeError("Exploded after clock execution")

    trans = _clock_transcript(user_msg, call_id)

    return Case(
        name="error_turn_after_tool_call",
        inputs=TurnEvalInput(
            session_id=session_id,
            user_message=user_msg,
            owner_id="evals@example.com",
            model=FunctionModel(stream_function=fail_after_clock),
            now=lambda: EVAL_FROZEN_TIME,
        ),
        expected_output=WorkedExampleTrace(
            session_id=session_id,
            status="error",
            reply="",
            error=FAILED_TURN,
            messages=(user_msg,),
            tool_calls=_clock_trace(call_id),
            transcript=trans,
            persisted_transcript=trans,
        ),
    )


def build_worked_example_dataset() -> Dataset[TurnEvalInput, WorkedExampleTrace, object]:
    return Dataset(
        name="worked_example_traces",
        evaluators=[
            ExactTranscriptMatch(),
            ExactToolCallsMatch(),
            ExactMessageSequenceMatch(),
            ExactTraceMatch(),
        ],
        cases=[
            _success_case(),
            _tool_call_case(),
            _immediate_error_case(),
            _after_tool_error_case(),
        ],
    )


async def run_trace_evals(
    dataset: Dataset[TurnEvalInput, WorkedExampleTrace, object] | None = None,
) -> EvaluationReport[TurnEvalInput, WorkedExampleTrace, object]:
    eval_dataset = dataset or build_worked_example_dataset()
    return await eval_dataset.evaluate(execute_turn_eval, progress=False)
