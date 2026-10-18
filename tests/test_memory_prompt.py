"""Turn injection of owner memory."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models.function import AgentInfo, FunctionModel

from clawhouse.agent.turn import TurnContext, run_turn
from clawhouse.store.store import MemorySessionStore

SESSION = "00000000-0000-4000-8000-0000000000c1"
OWNER = "ada@example.com"


def _capture(seen: list[str]) -> FunctionModel:
    async def stream(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str]:
        del info
        texts: list[str] = []
        for message in messages:
            for part in message.parts:
                content = getattr(part, "content", None)
                if isinstance(content, str):
                    texts.append(content)
        seen.append("\n".join(texts))
        yield "ok"

    return FunctionModel(stream_function=stream)


@pytest.mark.asyncio
async def test_turn_injects_at_most_5_entries_and_2000_chars() -> None:
    ticks = {"n": 0}

    def now() -> datetime:
        ticks["n"] += 1
        return datetime(2026, 10, 12, 12, 0, ticks["n"], tzinfo=UTC)

    store = MemorySessionStore(now=now)
    await store.open_session(SESSION, OWNER)
    tie_old = await store.save_memory(OWNER, "refunds once", None, None)
    await store.save_memory(OWNER, "refunds filler " + ("y" * 1800), None, None)
    older = await store.save_memory(OWNER, "refunds refunds", None, None)
    newer = await store.save_memory(OWNER, "refunds", None, None)
    tie_new = await store.save_memory(OWNER, "refunds once", None, None)
    seen: list[str] = []
    await run_turn(
        SESSION,
        "refunds",
        ctx=TurnContext(
            owner_id=OWNER,
            store=store,
            model=_capture(seen),
            now=lambda: datetime(2026, 10, 12, 12, 0, tzinfo=UTC),
        ),
    )
    memory = seen[0].split("[Memory]\n", 1)[1]
    lines = [line for line in memory.splitlines() if line.startswith("[")]
    assert 1 <= len(lines) <= 5
    assert sum(len(line) for line in lines) + max(len(lines) - 1, 0) <= 2000
    assert lines[0].startswith(f"[{older.id} {older.created_at.isoformat()}]")
    assert newer.id not in lines[0]
    assert newer.created_at > older.created_at
    assert tie_new.created_at > tie_old.created_at
    block = "\n".join(lines)
    assert tie_new.id in block
    assert tie_old.id not in block
    assert all(line.startswith("[") and "2026-10-12" in line for line in lines)


@pytest.mark.asyncio
async def test_turn_injection_excludes_other_owners() -> None:
    store = MemorySessionStore(now=lambda: datetime(2026, 10, 12, 12, 0, tzinfo=UTC))
    await store.open_session(SESSION, OWNER)
    await store.save_memory("grace@example.com", "refunds secret", None, None)
    await store.save_memory(OWNER, "refunds mine", None, None)
    seen: list[str] = []
    await run_turn(
        SESSION,
        "refunds",
        ctx=TurnContext(
            owner_id=OWNER,
            store=store,
            model=_capture(seen),
            now=lambda: datetime(2026, 10, 12, 12, 0, tzinfo=UTC),
        ),
    )
    assert "refunds mine" in seen[0]
    assert "refunds secret" not in seen[0]
