"""A scripted, keyless chat model for `make demo`.

`CLAWHOUSE_DEMO=1` swaps every model for this `FunctionModel`, so a visitor with
no Databricks workspace and no API key can watch the whole turn UX: streamed
text, a progress card, a question card, and an approval card. The script reads
the turn so far (the tool results since the last user message) to pick its
next step, so it resumes correctly after the question and the approval.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from uuid import uuid4

from pydantic_ai.messages import ModelMessage, ModelRequest, ToolReturnPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel

from clawhouse.agent.model import ModelEntry
from clawhouse.capabilities.interaction import ASK_USER, REPORT_PROGRESS

DEMO_MODEL_ID = "demo"
DEMO_MODEL_NAME = "clawhouse-demo"
# The demo's approval card. `remember` only writes a memory row to the
# session store, so approving it is harmless even outside a demo.
DEMO_APPROVAL_TOOL = "remember"
DEMO_TASK_ID = "demo-tour"
DEMO_OPTIONS = ("Show me an approval", "Skip the approval")
TOKEN_DELAY_SECONDS = 0.02

STEPS = ("Read your message", "Ask you a question", "Ask before acting", "Wrap up")

DemoChunk = str | dict[int, DeltaToolCall]


def demo_model_entry() -> ModelEntry:
    return ModelEntry(
        id=DEMO_MODEL_ID,
        label="Demo · scripted, no keys",
        provider="demo",
        model=DEMO_MODEL_NAME,
        is_default=True,
    )


def demo_chat_model() -> FunctionModel:
    return FunctionModel(stream_function=demo_stream, model_name=DEMO_MODEL_NAME)


@dataclass(frozen=True, slots=True)
class _Turn:
    """What the scripted turn has done since the user's last message."""

    prompt: str
    progress_updates: int
    choice: str | None
    approval_result: str | None


def _tail_start(messages: Sequence[ModelMessage]) -> int:
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if isinstance(message, ModelRequest) and any(
            isinstance(part, UserPromptPart) for part in message.parts
        ):
            return index
    return 0


def _prompt_text(message: ModelMessage) -> str:
    for part in message.parts:
        if isinstance(part, UserPromptPart) and isinstance(part.content, str):
            return part.content
    return ""


def read_turn(messages: Sequence[ModelMessage]) -> _Turn:
    start = _tail_start(messages)
    tail = messages[start:]
    returns = [
        part for message in tail for part in message.parts if isinstance(part, ToolReturnPart)
    ]
    by_name = {part.tool_name: part.model_response_str() for part in returns}
    return _Turn(
        prompt=_prompt_text(messages[start]) if messages else "",
        progress_updates=sum(part.tool_name == REPORT_PROGRESS for part in returns),
        choice=by_name.get(ASK_USER),
        approval_result=by_name.get(DEMO_APPROVAL_TOOL),
    )


def _call(name: str, args: dict[str, object]) -> dict[int, DeltaToolCall]:
    return {
        0: DeltaToolCall(
            name=name, json_args=json.dumps(args), tool_call_id=f"demo-{uuid4().hex[:12]}"
        )
    }


def _progress(done: int, *, failed_step: int | None = None) -> dict[int, DeltaToolCall]:
    steps: list[dict[str, str]] = []
    for index, label in enumerate(STEPS):
        status = "done" if index < done else "running" if index == done else "pending"
        if index == failed_step:
            status = "failed"
        steps.append({"label": label, "status": status})
    return _call(REPORT_PROGRESS, {"task_id": DEMO_TASK_ID, "steps": steps})


async def _words(text: str) -> AsyncIterator[str]:
    words = text.split(" ")
    for index, word in enumerate(words):
        yield word if index == len(words) - 1 else word + " "
        await asyncio.sleep(TOKEN_DELAY_SECONDS)


def _picked_skip(turn: _Turn) -> bool:
    return turn.choice is not None and DEMO_OPTIONS[1] in turn.choice


def _approved(turn: _Turn) -> bool:
    return turn.approval_result is not None and "denied" not in turn.approval_result.lower()


def _final_text(turn: _Turn) -> str:
    if _picked_skip(turn):
        outcome = "You skipped the approval, so nothing was saved."
    elif _approved(turn):
        outcome = "You approved the `remember` call, so a memory row was written."
    else:
        outcome = "You denied the `remember` call, so the tool never ran."
    return (
        f"Tour finished. {outcome}\n\n"
        "That's the Clawhouse turn loop: streamed replies, a live progress card, "
        "a question card, and approvals before anything with side effects. "
        "Connect a real model (`SERVING_ENDPOINT` on Databricks, or any "
        "OpenAI-compatible endpoint via `CLAWHOUSE_MODELS`) to use it on your data."
    )


def _intro_text(turn: _Turn) -> str:
    said = turn.prompt.strip().replace("\n", " ")[:80] or "hello"
    return (
        f'Demo mode: no model or keys needed. You said "{said}". '
        "I'll walk you through what a Clawhouse turn looks like."
    )


Step = tuple[str, dict[int, DeltaToolCall] | None]


def _opening_step(turn: _Turn) -> Step:
    """Before the answer: intro text with the first progress card, then the question."""
    if turn.progress_updates == 0:
        return _intro_text(turn), _progress(1)
    question = "Which part of the tour do you want next?"
    args = {"question": question, "options": list(DEMO_OPTIONS), "default": DEMO_OPTIONS[0]}
    return "", _call(ASK_USER, args)


def _closing_step(turn: _Turn) -> Step:
    """After the answer: advance the card, ask to run a gated tool, then wrap up."""
    if turn.progress_updates == 1:
        return "", _progress(2)
    if turn.approval_result is None and not _picked_skip(turn):
        note = "Clawhouse demo: the visitor took the guided tour."
        return "Saving that needs your OK first.", _call(DEMO_APPROVAL_TOOL, {"text": note})
    if turn.progress_updates == 2:
        skipped = _picked_skip(turn) or not _approved(turn)
        return "", _progress(len(STEPS), failed_step=2 if skipped else None)
    return _final_text(turn), None


def _next_step(turn: _Turn) -> Step:
    """The text to stream and the tool call (if any) for the next model response."""
    return _opening_step(turn) if turn.choice is None else _closing_step(turn)


async def demo_stream(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[DemoChunk]:
    """The `FunctionModel` stream: one scripted step of the tour per model response."""
    del info
    text, call = _next_step(read_turn(messages))
    if text:
        async for chunk in _words(text):
            yield chunk
    if call is not None:
        yield call
