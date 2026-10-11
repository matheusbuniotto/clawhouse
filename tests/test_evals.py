"""Evaluations harness asserting exact worked-example traces through run_turn."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel
from pydantic_evals import Case, Dataset

from crabriks.evals import (
    ExactMessageSequenceMatch,
    ExactToolCallsMatch,
    ExactTraceMatch,
    ExactTranscriptMatch,
    ToolCallTrace,
    TurnEvalInput,
    WorkedExampleTrace,
    build_worked_example_dataset,
    execute_turn_eval,
    run_trace_evals,
)
from crabriks.shapes import TranscriptEntry
from crabriks.turn import FAILED_TURN

SESSION_ID = "22222222-2222-4222-8222-222222222222"
OWNER_ID = "eval-user@example.com"
FROZEN_TIME = datetime(2026, 10, 11, 10, 0, tzinfo=UTC)


def _text_reply_model(reply_text: str) -> FunctionModel:
    async def stream(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str]:
        del messages, info
        yield reply_text

    return FunctionModel(stream_function=stream)


@pytest.mark.asyncio
async def test_execute_turn_eval_captures_success_trace() -> None:
    inputs = TurnEvalInput(
        session_id=SESSION_ID,
        user_message="Hello Crabriks",
        owner_id=OWNER_ID,
        model=_text_reply_model("Greetings from Crabriks!"),
        now=lambda: FROZEN_TIME,
    )

    trace: WorkedExampleTrace = await execute_turn_eval(inputs)

    expected_transcript = (
        TranscriptEntry(role="user", content="Hello Crabriks"),
        TranscriptEntry(role="assistant", content="Greetings from Crabriks!"),
    )

    assert trace.session_id == SESSION_ID
    assert trace.status == "ok"
    assert trace.reply == "Greetings from Crabriks!"
    assert trace.error is None
    assert trace.messages == ("Hello Crabriks", "Greetings from Crabriks!")
    assert trace.tool_calls == ()
    assert trace.transcript == expected_transcript
    assert trace.persisted_transcript == expected_transcript


@pytest.mark.asyncio
async def test_execute_turn_eval_captures_tool_call_trace() -> None:
    call_id = "call-clock-eval"
    expected_time = "2026-10-11T10:00:00Z"

    async def clock_model(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        del info
        has_tool_return = any(
            part.part_kind == "tool-return" for msg in messages for part in msg.parts
        )
        if not has_tool_return:
            yield {0: DeltaToolCall(name="clock", json_args="{}", tool_call_id=call_id)}
            return
        yield f"Current time is {expected_time}"

    inputs = TurnEvalInput(
        session_id=SESSION_ID,
        user_message="what time is it?",
        owner_id=OWNER_ID,
        model=FunctionModel(stream_function=clock_model),
        now=lambda: FROZEN_TIME,
    )

    trace: WorkedExampleTrace = await execute_turn_eval(inputs)

    expected_tool_calls = (
        ToolCallTrace(
            name="clock",
            arguments="{}",
            tool_call_id=call_id,
            result=expected_time,
        ),
    )
    expected_transcript = (
        TranscriptEntry(role="user", content="what time is it?"),
        TranscriptEntry(
            role="tool_call",
            content="{}",
            tool_name="clock",
            tool_call_id=call_id,
        ),
        TranscriptEntry(
            role="tool_result",
            content=expected_time,
            tool_name="clock",
            tool_call_id=call_id,
        ),
        TranscriptEntry(role="assistant", content=f"Current time is {expected_time}"),
    )

    assert trace.status == "ok"
    assert trace.reply == f"Current time is {expected_time}"
    assert trace.error is None
    assert trace.messages == ("what time is it?", f"Current time is {expected_time}")
    assert trace.tool_calls == expected_tool_calls
    assert trace.transcript == expected_transcript
    assert trace.persisted_transcript == expected_transcript


@pytest.mark.asyncio
async def test_execute_turn_eval_captures_error_trace() -> None:
    async def exploding_model(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str]:
        del messages, info
        for _ in ():
            yield ""
        raise RuntimeError("Immediate backend failure")

    inputs = TurnEvalInput(
        session_id=SESSION_ID,
        user_message="kaboom",
        owner_id=OWNER_ID,
        model=FunctionModel(stream_function=exploding_model),
        now=lambda: FROZEN_TIME,
    )

    trace: WorkedExampleTrace = await execute_turn_eval(inputs)

    expected_transcript = (TranscriptEntry(role="user", content="kaboom"),)

    assert trace.status == "error"
    assert trace.reply == ""
    assert trace.error == FAILED_TURN
    assert trace.messages == ("kaboom",)
    assert trace.tool_calls == ()
    assert trace.transcript == expected_transcript
    assert trace.persisted_transcript == expected_transcript


@pytest.mark.asyncio
async def test_worked_example_dataset_runs_and_passes_all_assertions() -> None:
    dataset = build_worked_example_dataset()
    assert len(dataset.cases) == 4

    report = await run_trace_evals(dataset)

    assert len(report.failures) == 0
    assert len(report.cases) == 4

    for case in report.cases:
        assert len(case.evaluator_failures) == 0
        for eval_name, result in case.assertions.items():
            msg = f"Assertion {eval_name} failed on case {case.name}: {result.reason}"
            assert result.value is True, msg


@pytest.mark.asyncio
async def test_evaluator_fails_on_divergent_trace() -> None:
    divergent_case = Case(
        name="deliberate_divergence",
        inputs=TurnEvalInput(
            session_id=SESSION_ID,
            user_message="Hello",
            owner_id=OWNER_ID,
            model=_text_reply_model("Actual reply"),
            now=lambda: FROZEN_TIME,
        ),
        expected_output=WorkedExampleTrace(
            session_id=SESSION_ID,
            status="ok",
            reply="WRONG EXPECTED REPLY",
            error=None,
            messages=("Hello", "WRONG EXPECTED REPLY"),
            tool_calls=(),
            transcript=(
                TranscriptEntry(role="user", content="Hello"),
                TranscriptEntry(role="assistant", content="WRONG EXPECTED REPLY"),
            ),
            persisted_transcript=(
                TranscriptEntry(role="user", content="Hello"),
                TranscriptEntry(role="assistant", content="WRONG EXPECTED REPLY"),
            ),
        ),
    )

    dataset = Dataset(
        name="divergence_test",
        evaluators=[
            ExactTranscriptMatch(),
            ExactToolCallsMatch(),
            ExactMessageSequenceMatch(),
            ExactTraceMatch(),
        ],
        cases=[divergent_case],
    )

    report = await run_trace_evals(dataset)
    assert len(report.cases) == 1
    case_result = report.cases[0]

    assert case_result.assertions["ExactTranscriptMatch"].value is False
    assert case_result.assertions["ExactToolCallsMatch"].value is True
    assert case_result.assertions["ExactMessageSequenceMatch"].value is False
    assert case_result.assertions["ExactTraceMatch"].value is False
