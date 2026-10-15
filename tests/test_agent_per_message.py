"""Agent per message (#97): who answers a turn, and what the transcript records about it."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime

from pydantic_ai.messages import ModelMessage
from pydantic_ai.models.function import AgentInfo, FunctionModel

from clawhouse.turn import AgentNotice, TurnContext, TurnNotice, run_turn  # isort: skip
from clawhouse.shapes import CustomAgent
from clawhouse.store import MemorySessionStore

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
