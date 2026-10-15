"""`ask_user` (#97): a question card pauses the run like an approval; jobs take the default."""

import json
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic_ai.messages import ModelMessage, RetryPromptPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel

from clawhouse.turn import (  # isort: skip
    Answer,
    QuestionNotice,
    TurnContext,
    TurnNotice,
    resume_turn,
    run_turn,
)
from clawhouse.api.app import scheduled_turn_context
from clawhouse.app import create_app
from clawhouse.identity import Caller
from clawhouse.settings import Settings
from clawhouse.shapes import ScheduleEntry
from clawhouse.store import ApprovalPending, MemorySessionStore

SESSION = "44444444-4444-4444-8444-444444444444"
OWNER = "ada@example.com"
HEADERS = {"x-forwarded-email": OWNER, "x-forwarded-access-token": "dapi-secret"}
ASK = {"question": "Which month?", "options": ["Sept", "Oct"], "default": "Oct"}


def _returns(messages: list[ModelMessage]) -> list[ToolReturnPart]:
    return [p for m in messages for p in m.parts if isinstance(p, ToolReturnPart)]


class _Asker:
    """Calls `ask_user` once, then echoes the tool result it got back."""

    def __init__(self, args: dict[str, Any] = ASK) -> None:
        self.args = args
        self.seen: list[list[ModelMessage]] = []

    async def stream(
        self, messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        del info
        self.seen.append(list(messages))
        returns = _returns(messages)
        if returns:
            yield f"got: {returns[-1].content}"
            return
        retries = [p for m in messages for p in m.parts if isinstance(p, RetryPromptPart)]
        if retries:
            yield "retried"
            return
        yield {
            0: DeltaToolCall(name="ask_user", json_args=json.dumps(self.args), tool_call_id="q1")
        }

    def model(self) -> FunctionModel:
        return FunctionModel(stream_function=self.stream)


def _ctx(
    model: FunctionModel,
    store: MemorySessionStore,
    notices: list[TurnNotice] | None = None,
    **extra: Any,
) -> TurnContext:
    async def capture(notice: TurnNotice) -> None:
        if notices is not None:
            notices.append(notice)

    ctx = TurnContext(
        owner_id=OWNER,
        store=store,
        model=model,
        now=lambda: datetime.now(UTC),
        emit=capture,
    )
    return replace(ctx, **extra)


async def test_ask_user_pauses_the_run_and_emits_a_question_card() -> None:
    store = MemorySessionStore()
    notices: list[TurnNotice] = []
    result = await run_turn(SESSION, "report", ctx=_ctx(_Asker().model(), store, notices))

    assert result.status == "pending_approval"
    questions = [n for n in notices if isinstance(n, QuestionNotice)]
    assert len(questions) == 1
    assert questions[0].question == "Which month?"
    assert questions[0].options == ("Sept", "Oct")
    assert questions[0].default == "Oct"
    assert questions[0].question_id == result.approval_id


async def test_a_pending_question_blocks_new_messages() -> None:
    store = MemorySessionStore()
    await run_turn(SESSION, "report", ctx=_ctx(_Asker().model(), store))

    with pytest.raises(ApprovalPending):
        await run_turn(SESSION, "hello?", ctx=_ctx(_Asker().model(), store))


async def test_the_answer_returns_as_the_tool_result_not_a_user_message() -> None:
    store = MemorySessionStore()
    asker = _Asker()
    paused = await run_turn(SESSION, "report", ctx=_ctx(asker.model(), store))
    assert paused.approval_id is not None

    resumed = await resume_turn(
        SESSION, paused.approval_id, Answer(selected=("Sept",)), ctx=_ctx(asker.model(), store)
    )

    assert resumed.status == "ok"
    assert resumed.reply == "got: The user chose: Sept"
    assert [e.role for e in resumed.transcript] == ["user", "tool_call", "tool_result", "assistant"]
    assert resumed.transcript[2].tool_name == "ask_user"
    assert resumed.transcript[2].content == "The user chose: Sept"
    assert (await store.get_approval(paused.approval_id)).status == "approved"


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (ASK, "Oct"),
        ({"question": "Which?", "options": ["A", "B"]}, "A"),
    ],
)
async def test_a_headless_job_takes_the_default_and_records_it(
    args: dict[str, Any], expected: str
) -> None:
    """Decision 2: no pause in a job; `default`, else the first option, lands in the transcript."""
    store = MemorySessionStore()
    notices: list[TurnNotice] = []
    result = await run_turn(
        SESSION, "report", ctx=_ctx(_Asker(args).model(), store, notices, headless=True)
    )

    assert result.status == "ok"
    assert not any(isinstance(n, QuestionNotice) for n in notices)
    recorded = next(e for e in result.transcript if e.role == "tool_result")
    assert recorded.tool_name == "ask_user"
    assert f'picked the default option "{expected}"' in recorded.content
    assert await store.list_approvals(OWNER) == ()


async def test_a_default_outside_the_options_is_sent_back_to_the_model() -> None:
    store = MemorySessionStore()
    bad = {"question": "Which?", "options": ["A", "B"], "default": "C"}
    result = await run_turn(SESSION, "report", ctx=_ctx(_Asker(bad).model(), store))

    assert result.status == "ok"
    assert result.reply == "retried"


async def test_a_question_left_unanswered_for_a_day_expires_on_the_next_message() -> None:
    store = MemorySessionStore()
    await run_turn(SESSION, "report", ctx=_ctx(_Asker().model(), store))
    later = datetime.now(UTC) + timedelta(hours=25)

    async def reply(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str]:
        del messages, info
        yield "fresh start"

    result = await run_turn(
        SESSION,
        "anyone there?",
        ctx=_ctx(FunctionModel(stream_function=reply), store, now=lambda: later),
    )

    assert result.status == "ok"
    notices = [e.content for e in result.transcript if e.role == "notice"]
    assert notices == ["Pergunta encerrada sem resposta depois de 24h."]
    assert [a.status for a in await store.list_approvals(OWNER)] == ["denied"]


# --- API -----------------------------------------------------------------------------------


def _app(store: MemorySessionStore, model: FunctionModel):
    settings = Settings(dev_user=None, dev_token=None, serving_endpoint=None, workspace_host=None)

    def model_for(caller: Caller, model_id: str | None) -> FunctionModel:
        del caller, model_id
        return model

    return create_app(settings=settings, model_for=model_for, store=store)


def _events(body: str) -> list[tuple[str, dict[str, Any]]]:
    frames = []
    for raw in body.split("\n\n"):
        if not raw.strip():
            continue
        lines = dict(line.split(":", 1) for line in raw.split("\n"))
        frames.append((lines["event"].strip(), json.loads(lines["data"])))
    return frames


async def test_the_question_card_round_trips_through_the_api() -> None:
    store = MemorySessionStore()
    asker = _Asker()
    app = _app(store, asker.model())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        streamed = await client.post(
            f"/api/sessions/{SESSION}/turns", headers=HEADERS, json={"message": "report"}
        )
        frames = dict(_events(streamed.text))
        question = frames["question"]
        pending = await client.get(f"/api/sessions/{SESSION}/questions", headers=HEADERS)
        approvals = await client.get("/api/approvals", headers=HEADERS)
        blocked = await client.post(
            f"/api/sessions/{SESSION}/turns", headers=HEADERS, json={"message": "hi"}
        )
        via_approval = await client.post(
            f"/api/approvals/{question['question_id']}/approve", headers=HEADERS
        )
        wrong = await client.post(
            f"/api/questions/{question['question_id']}/answer",
            headers=HEADERS,
            json={"selected": ["Nov"]},
        )
        both = await client.post(
            f"/api/questions/{question['question_id']}/answer",
            headers=HEADERS,
            json={"selected": ["Sept", "Oct"]},
        )
        answered = await client.post(
            f"/api/questions/{question['question_id']}/answer",
            headers=HEADERS,
            json={"selected": ["Oct"]},
        )
        again = await client.post(
            f"/api/questions/{question['question_id']}/answer",
            headers=HEADERS,
            json={"selected": ["Oct"]},
        )

    assert question == {
        "question_id": question["question_id"],
        "question": "Which month?",
        "options": ["Sept", "Oct"],
        "default": "Oct",
        "multi": False,
    }
    assert [q["id"] for q in pending.json()] == [question["question_id"]]
    assert approvals.json()["approvals"] == []
    assert blocked.status_code == 409
    assert via_approval.status_code == 409
    assert wrong.status_code == 422
    assert both.status_code == 422
    assert answered.status_code == 200
    assert answered.json()["reply"] == "got: The user chose: Oct"
    assert answered.json()["question"]["status"] == "approved"
    assert answered.json()["pending"] == []
    assert again.status_code == 409


def test_scheduled_turns_run_headless() -> None:
    store = MemorySessionStore()
    app = _app(store, _Asker().model())
    now = datetime.now(UTC)
    schedule = ScheduleEntry(
        id="s1",
        session_id=SESSION,
        owner_id=OWNER,
        cron_expression="0 5 * * *",
        prompt="daily report",
        status="active",
        next_run_at=now,
        created_at=now,
    )

    ctx = scheduled_turn_context(app, schedule)

    assert ctx.headless is True
    assert ctx.owner_id == OWNER
