"""Structured interaction in the transcript: questions (`ask_user`) and progress cards.

A question reuses the approval pause: the tool defers, the run ends with
`DeferredToolRequests`, the store keeps the pending call, and the answer comes
back as the tool result through `DeferredToolResults.calls`. A headless run
(a scheduled job) has nobody to ask, so it takes the default option instead.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ValidationError
from pydantic_ai import CallDeferred, ModelRetry
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.toolsets import AgentToolset, FunctionToolset

ASK_USER = "ask_user"
ASK_USER_DESCRIPTION = (
    "Ask the user a multiple-choice question and wait for the answer. Use it instead of "
    "asking in prose when you need a decision. `options` are short button labels; "
    "`default` (one of the options) is used when nobody can answer."
)


REPORT_PROGRESS = "report_progress"
REPORT_PROGRESS_DESCRIPTION = (
    "Show the user a checklist for a long task and keep it current. Call it with the full step "
    "list each time a step changes; the same `task_id` updates the same card."
)

StepStatus = Literal["pending", "running", "done", "failed"]


class Step(BaseModel):
    label: str
    status: StepStatus = "pending"


class _ProgressArgs(BaseModel):
    task_id: str
    steps: list[Step]


def parse_progress(arguments: str) -> tuple[str, tuple[Step, ...]] | None:
    """A `report_progress` call's card state, or None when the model sent junk."""
    try:
        args = _ProgressArgs.model_validate_json(arguments or "{}")
    except ValidationError:
        return None
    return args.task_id, tuple(args.steps)


@dataclass(frozen=True, slots=True)
class Question:
    """What the card shows. Stored as the paused call's arguments."""

    question: str
    options: tuple[str, ...]
    default: str | None = None
    multi: bool = False

    @property
    def fallback(self) -> str:
        """The headless choice: `default` when given, else the first option."""
        return self.default or self.options[0]

    @classmethod
    def from_arguments(cls, arguments: str) -> Question:
        data: dict[str, Any] = json.loads(arguments or "{}")
        return cls(
            question=str(data.get("question", "")),
            options=tuple(str(o) for o in data.get("options") or ()),
            default=data.get("default"),
            multi=bool(data.get("multi", False)),
        )


class InvalidAnswer(ValueError):
    """The picked labels do not fit the question."""


def check_answer(question: Question, selected: list[str]) -> tuple[str, ...]:
    picked = tuple(dict.fromkeys(selected))
    if not picked:
        raise InvalidAnswer("pick at least one option")
    if unknown := [label for label in picked if label not in question.options]:
        raise InvalidAnswer(f"not an option: {unknown}")
    if len(picked) > 1 and not question.multi:
        raise InvalidAnswer("this question takes one option")
    return picked


def answer_text(selected: tuple[str, ...]) -> str:
    """The tool result the model reads after the user clicks."""
    return "The user chose: " + ", ".join(selected)


def headless_answer_text(choice: str) -> str:
    """The tool result in a job: recorded in the transcript like any tool result."""
    return f'No user in this run (scheduled job): picked the default option "{choice}".'


def _question(question: str, options: list[str], default: str | None, *, multi: bool) -> Question:
    labels = [label.strip() for label in options if label.strip()]
    if len(labels) < 2:
        raise ModelRetry("ask_user needs at least two options.")
    if default is not None and default not in labels:
        raise ModelRetry("ask_user `default` must be one of the options.")
    return Question(question=question, options=tuple(labels), default=default, multi=multi)


@dataclass
class InteractionCapability(AbstractCapability[Any]):
    """`ask_user` and `report_progress` for every agent.

    `headless` makes `ask_user` answer with the default instead of pausing.
    """

    headless: bool = False

    def get_toolset(self) -> AgentToolset[Any] | None:
        headless = self.headless

        def ask_user(
            question: str,
            options: list[str],
            default: str | None = None,
            multi: bool = False,
        ) -> str:
            """Ask the user a multiple-choice question and wait for the answer."""
            asked = _question(question, options, default, multi=multi)
            if headless:
                return headless_answer_text(asked.fallback)
            raise CallDeferred(
                metadata={
                    "kind": "question",
                    "question": asked.question,
                    "options": list(asked.options),
                    "default": asked.default,
                    "multi": asked.multi,
                }
            )

        def report_progress(task_id: str, steps: list[Step]) -> str:
            """Show or update the progress card for `task_id`."""
            done = sum(step.status == "done" for step in steps)
            return f"Progress card {task_id} updated: {done}/{len(steps)} done."

        toolset: FunctionToolset[Any] = FunctionToolset()
        toolset.add_function(ask_user, name=ASK_USER, description=ASK_USER_DESCRIPTION)
        toolset.add_function(
            report_progress, name=REPORT_PROGRESS, description=REPORT_PROGRESS_DESCRIPTION
        )
        return toolset
