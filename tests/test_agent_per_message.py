"""Agent per message (#97): who answers a turn, and what the transcript records about it."""

from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel

from clawhouse.agent.history import drop_foreign_tool_parts
from clawhouse.agent.roster import first_agent_mention, missing_agent_warning
from clawhouse.agent.turn import (
    AgentNotice,
    TurnContext,
    TurnNotice,
    WarningNotice,
    resume_turn,
    run_turn,
)
from clawhouse.store.shapes import CustomAgent, TranscriptEntry
from clawhouse.store.store import MemorySessionStore

SESSION = "22222222-2222-4222-8222-222222222222"
OWNER = "ada@example.com"
FROZEN = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)


async def _reply(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str]:
    del messages, info
    yield "ok"


def _ctx(
    store: MemorySessionStore,
    *,
    default_agent: str | None = None,
    notices: list[TurnNotice] | None = None,
    model: FunctionModel | None = None,
) -> TurnContext:
    async def capture(notice: TurnNotice) -> None:
        if notices is not None:
            notices.append(notice)

    return TurnContext(
        owner_id=OWNER,
        store=store,
        model=model or FunctionModel(stream_function=_reply),
        now=lambda: FROZEN,
        emit=capture,
        default_agent=default_agent,
    )


async def _fraud(store: MemorySessionStore, owner: str = OWNER) -> CustomAgent:
    return await store.create_custom_agent(
        CustomAgent(
            id="33333333-3333-4333-8333-333333333333",
            owner_id=owner,
            name="fraud",
            description="Fraud analyst",
            system_prompt="You investigate chargebacks.",
            signature_emoji="🕵️",
        )
    )


async def test_every_assistant_entry_records_the_default_agent() -> None:
    store = MemorySessionStore()
    result = await run_turn(SESSION, "hi", ctx=_ctx(store))

    assistant = [e for e in result.transcript if e.role == "assistant"]
    assert assistant
    assert all(e.agent_id == "main" for e in assistant)


async def test_the_turn_opens_with_an_agent_notice() -> None:
    store = MemorySessionStore()
    notices: list[TurnNotice] = []
    await run_turn(SESSION, "hi", ctx=_ctx(store, notices=notices))

    assert notices[0] == AgentNotice(
        agent_id="main", name="main", emoji="🦀", model="function::_reply"
    )


async def test_the_session_default_agent_answers_when_nothing_is_mentioned() -> None:
    store = MemorySessionStore()
    await _fraud(store)
    notices: list[TurnNotice] = []
    result = await run_turn(
        SESSION, "chargebacks?", ctx=_ctx(store, default_agent="fraud", notices=notices)
    )

    assert isinstance(notices[0], AgentNotice)
    assert notices[0].agent_id == "fraud"
    assert notices[0].emoji == "🕵️"
    assert [e.agent_id for e in result.transcript] == ["fraud", "fraud"]


async def test_an_unknown_session_default_falls_back_to_the_platform_agent() -> None:
    store = MemorySessionStore()
    result = await run_turn(SESSION, "hi", ctx=_ctx(store, default_agent="ghost"))

    assert [e.agent_id for e in result.transcript] == ["main", "main"]


async def test_slash_commands_are_answered_by_the_turn_agent() -> None:
    store = MemorySessionStore()
    result = await run_turn(SESSION, "/clear", ctx=_ctx(store))

    assert result.transcript[-1].role == "assistant"
    assert result.transcript[-1].agent_id == "main"


# --- Slice 2: `@agent` picks the executor ------------------------------------------------


class _Recorder:
    """A model that remembers what each request carried, and answers `ok`."""

    def __init__(self) -> None:
        self.instructions: list[str] = []
        self.histories: list[list[ModelMessage]] = []

    async def stream(self, messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str]:
        self.instructions.append(info.instructions or "")
        self.histories.append(list(messages))
        yield "ok"

    def model(self) -> FunctionModel:
        return FunctionModel(stream_function=self.stream, function=_summarize)


def _summarize(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    del messages, info
    return ModelResponse(parts=[TextPart(content="SUMMARY: talked about chargebacks.")])


def _texts(messages: list[ModelMessage]) -> list[str]:
    return [
        part.content
        for message in messages
        for part in message.parts
        if isinstance(part, UserPromptPart | TextPart | SystemPromptPart)
        and isinstance(part.content, str)
    ]


async def test_a_mention_runs_the_mentioned_agent_for_real() -> None:
    store = MemorySessionStore()
    await _fraud(store)
    recorder = _Recorder()
    notices: list[TurnNotice] = []
    result = await run_turn(
        SESSION,
        "@fraud chargebacks above 5k this week",
        ctx=_ctx(store, notices=notices, model=recorder.model()),
    )

    assert isinstance(notices[0], AgentNotice)
    assert notices[0].agent_id == "fraud"
    assert "agent @fraud" in recorder.instructions[0]
    assert "You investigate chargebacks." in recorder.instructions[0]
    assert "platform agent main" not in recorder.instructions[0]
    assert {e.agent_id for e in result.transcript} == {"fraud"}


async def test_a_mention_holds_for_one_message_only() -> None:
    """Invariant 2: the session default does not change."""
    store = MemorySessionStore()
    await _fraud(store)
    recorder = _Recorder()
    await run_turn(SESSION, "@fraud chargebacks?", ctx=_ctx(store, model=recorder.model()))
    second = await run_turn(SESSION, "and last month?", ctx=_ctx(store, model=recorder.model()))

    assert "platform agent main" in recorder.instructions[1]
    assert [e.agent_id for e in second.transcript if e.role == "assistant"] == ["fraud", "main"]


async def test_an_unknown_mention_falls_back_to_the_default_and_warns() -> None:
    """Invariant 3: `@x` that does not exist is answered by the default, with a notice."""
    store = MemorySessionStore()
    notices: list[TurnNotice] = []
    result = await run_turn(SESSION, "@ghost help", ctx=_ctx(store, notices=notices))

    assert isinstance(notices[0], AgentNotice)
    assert notices[0].agent_id == "main"
    assert WarningNotice(missing_agent_warning("ghost")) in notices
    assert [(e.role, e.agent_id) for e in result.transcript] == [
        ("user", "main"),
        ("notice", "main"),
        ("assistant", "main"),
    ]
    assert result.transcript[1].content.startswith("@ghost não encontrado")


async def test_another_owners_agent_cannot_be_mentioned() -> None:
    """Invariant 3: an agent the user may not use counts as not found."""
    store = MemorySessionStore()
    await _fraud(store, owner="grace@example.com")
    recorder = _Recorder()
    notices: list[TurnNotice] = []
    await run_turn(SESSION, "@fraud help", ctx=_ctx(store, notices=notices, model=recorder.model()))

    assert isinstance(notices[0], AgentNotice)
    assert notices[0].agent_id == "main"
    assert WarningNotice(missing_agent_warning("fraud")) in notices
    assert "You investigate chargebacks." not in recorder.instructions[0]


async def test_notices_are_shown_but_never_replayed_to_the_model() -> None:
    store = MemorySessionStore()
    recorder = _Recorder()
    await run_turn(SESSION, "@ghost help", ctx=_ctx(store, model=recorder.model()))
    await run_turn(SESSION, "again", ctx=_ctx(store, model=recorder.model()))

    assert not any("não encontrado" in text for text in _texts(recorder.histories[1]))


async def test_the_mentioned_agent_sees_the_whole_conversation() -> None:
    """Invariant 5 / decision 1: the history is shared."""
    store = MemorySessionStore()
    await _fraud(store)
    recorder = _Recorder()
    await run_turn(SESSION, "first question", ctx=_ctx(store, model=recorder.model()))
    await run_turn(SESSION, "@fraud and now?", ctx=_ctx(store, model=recorder.model()))

    seen = _texts(recorder.histories[1])
    assert seen[:3] == ["first question", "ok", "@fraud and now?"]


async def test_after_compaction_the_mentioned_agent_starts_at_the_summary() -> None:
    """Decision 1: when the session was compacted, history starts at the summary."""
    store = MemorySessionStore()
    await _fraud(store)
    recorder = _Recorder()
    await run_turn(SESSION, "secret old detail", ctx=_ctx(store, model=recorder.model()))
    await run_turn(SESSION, "/compact", ctx=_ctx(store, model=recorder.model()))
    await run_turn(SESSION, "@fraud continue", ctx=_ctx(store, model=recorder.model()))

    seen = _texts(recorder.histories[-1])
    assert seen[0] == "SUMMARY: talked about chargebacks."
    assert not any("secret old detail" in text for text in seen)
    assert seen[-1] == "@fraud continue"


async def test_tool_parts_unknown_to_the_current_agent_are_dropped_from_history() -> None:
    store = MemorySessionStore()
    await store.open_session(SESSION, OWNER)
    run_id = await store.claim_run(SESSION)
    for entry in (
        TranscriptEntry(role="user", content="use your private tool"),
        TranscriptEntry(role="tool_call", content="{}", tool_name="fraud_x", tool_call_id="a"),
        TranscriptEntry(role="tool_result", content="42", tool_name="fraud_x", tool_call_id="a"),
        TranscriptEntry(role="tool_call", content="{}", tool_name="clock", tool_call_id="b"),
        TranscriptEntry(role="tool_result", content="noon", tool_name="clock", tool_call_id="b"),
        TranscriptEntry(role="assistant", content="the answer is 42", agent_id="fraud"),
    ):
        await store.append_entry(SESSION, run_id, entry)
    await store.finish_run(SESSION, run_id, "ok")
    recorder = _Recorder()

    await run_turn(SESSION, "thanks", ctx=_ctx(store, model=recorder.model()))

    history = recorder.histories[0]
    tool_names = [
        part.tool_name
        for message in history
        for part in message.parts
        if isinstance(part, ToolCallPart | ToolReturnPart)
    ]
    assert tool_names == ["clock", "clock"]
    assert "the answer is 42" in _texts(history)


def test_drop_foreign_tool_parts_keeps_text_and_known_tools() -> None:
    messages: list[ModelMessage] = [
        ModelRequest(parts=[UserPromptPart(content="hi")]),
        ModelResponse(
            parts=[
                TextPart(content="let me check"),
                ToolCallPart(tool_name="other", args="{}", tool_call_id="1"),
            ]
        ),
        ModelRequest(parts=[ToolReturnPart(tool_name="other", content="x", tool_call_id="1")]),
        ModelResponse(parts=[ToolCallPart(tool_name="clock", args="{}", tool_call_id="2")]),
    ]

    kept = drop_foreign_tool_parts(messages, {"clock"})

    assert len(kept) == 3
    assert kept[1].parts == [TextPart(content="let me check")]
    assert isinstance(kept[2].parts[0], ToolCallPart)
    assert kept[2].parts[0].tool_name == "clock"


def test_only_word_start_handles_count_as_agent_mentions() -> None:
    assert first_agent_mention("@fraud chargebacks") == "fraud"
    assert first_agent_mention("ask @fraud, then @main") == "fraud"
    assert first_agent_mention("mail ada@example.com") is None
    assert first_agent_mention("look at @samples.nyctaxi.trips") is None
    assert first_agent_mention("read @AGENTS.md and @file:SOUL.md") is None


async def test_a_resumed_approval_continues_with_the_agent_that_paused() -> None:
    store = MemorySessionStore()
    await _fraud(store)
    instructions: list[str] = []

    async def call_clock(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        instructions.append(info.instructions or "")
        if any(isinstance(p, ToolReturnPart) for m in messages for p in m.parts):
            yield "done"
            return
        yield {0: DeltaToolCall(name="clock", json_args="{}", tool_call_id="call-1")}

    ctx = replace(
        _ctx(store, model=FunctionModel(stream_function=call_clock)), sensitive_tools=("clock",)
    )
    paused = await run_turn(SESSION, "@fraud what time is it?", ctx=ctx)
    assert paused.status == "pending_approval"
    assert paused.approval_id is not None

    resumed = await resume_turn(SESSION, paused.approval_id, "approved", ctx=ctx)

    assert resumed.status == "ok"
    assert "agent @fraud" in instructions[-1]
    assert resumed.transcript[-1].agent_id == "fraud"
