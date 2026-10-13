from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic_ai.models.function import FunctionModel

from crabriks.agent.turn import TurnContext
from crabriks.app import create_app
from crabriks.capabilities.schedules import (
    InvalidScheduleCommand,
    calculate_next_run,
    parse_schedule_command,
    run_scheduled_turn,
)
from crabriks.settings import Settings
from crabriks.store.shapes import ScheduleEntry, TurnResult
from crabriks.store.store import MemorySessionStore


def test_parse_cron_syntax() -> None:
    text = '/schedule cron "0 9 * * *" Check failing Lakeflow jobs and notify me'
    parsed = parse_schedule_command(text)

    assert parsed is not None
    assert parsed.cron_expression == "0 9 * * *"
    assert parsed.prompt == "Check failing Lakeflow jobs and notify me"


def test_parse_every_syntax() -> None:
    text = "/schedule every 30m Inspect Lakebase table sync status"
    parsed = parse_schedule_command(text)

    assert parsed is not None
    assert parsed.cron_expression == "*/30 * * * *"
    assert parsed.prompt == "Inspect Lakebase table sync status"


def test_parse_every_hours_syntax() -> None:
    text = "/schedule every 2h Run daily audit report"
    parsed = parse_schedule_command(text)

    assert parsed is not None
    assert parsed.cron_expression == "0 */2 * * *"
    assert parsed.prompt == "Run daily audit report"


def test_parse_non_schedule_message_returns_none() -> None:
    text = "Hello agent, what is the status of jobs?"
    assert parse_schedule_command(text) is None


def test_parse_invalid_schedule_syntax_raises_invalid_command() -> None:
    with pytest.raises(InvalidScheduleCommand):
        parse_schedule_command("/schedule foo bar")


def test_calculate_next_run_advances_time() -> None:
    base_time = datetime(2026, 10, 12, 10, 0, 0, tzinfo=UTC)
    next_run = calculate_next_run("*/15 * * * *", from_time=base_time)

    assert next_run == datetime(2026, 10, 12, 10, 15, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_memory_store_schedule_crud_and_claim() -> None:
    store = MemorySessionStore()
    session = await store.create_session("ada@example.com")
    now = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)

    schedule = ScheduleEntry(
        id="sch-1",
        session_id=session.id,
        owner_id="ada@example.com",
        cron_expression="*/5 * * * *",
        prompt="Check run health",
        status="active",
        next_run_at=now,
        created_at=now,
    )

    created = await store.create_schedule(schedule)
    assert created.id == "sch-1"
    assert created.status == "active"

    schedules = await store.list_schedules("ada@example.com")
    assert len(schedules) == 1
    assert schedules[0].id == "sch-1"

    # Claim due schedules when before/at next_run_at
    claimed = await store.claim_due_schedules(now)
    assert len(claimed) == 1
    assert claimed[0].id == "sch-1"

    # Update run
    next_time = datetime(2026, 10, 12, 12, 5, tzinfo=UTC)
    updated = await store.update_schedule_run("sch-1", last_run_at=now, next_run_at=next_time)
    assert updated is not None
    assert updated.last_run_at == now
    assert updated.next_run_at == next_time

    # No due schedules right now
    due_again = await store.claim_due_schedules(now)
    assert len(due_again) == 0

    # Cancel schedule
    cancelled = await store.cancel_schedule("sch-1", "ada@example.com")
    assert cancelled is True
    active_schedules = await store.list_schedules("ada@example.com")
    assert active_schedules[0].status == "cancelled"


@pytest.mark.asyncio
async def test_run_scheduled_turn_executes_and_advances_schedule() -> None:
    store = MemorySessionStore()
    session = await store.create_session("ada@example.com")
    now = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)

    schedule = ScheduleEntry(
        id="sch-2",
        session_id=session.id,
        owner_id="ada@example.com",
        cron_expression="*/10 * * * *",
        prompt="Inspect errors",
        status="active",
        next_run_at=now,
        created_at=now,
    )
    await store.create_schedule(schedule)

    executed_calls = []

    async def fake_run_turn(sess_id: str, prompt: str, ctx: TurnContext) -> TurnResult:
        executed_calls.append((sess_id, prompt))
        return TurnResult(
            session_id=sess_id,
            status="ok",
            reply="All clear",
            error=None,
            transcript=(),
        )

    def fake_make_ctx(sch: ScheduleEntry) -> TurnContext:
        return TurnContext(
            owner_id=sch.owner_id,
            store=store,
            model=None,  # type: ignore[arg-type]
            now=lambda: now,
        )

    result = await run_scheduled_turn(
        schedule,
        store=store,
        run_turn_fn=fake_run_turn,
        make_turn_ctx=fake_make_ctx,
        now_fn=lambda: now,
    )

    assert result is not None
    assert result.reply == "All clear"
    assert len(executed_calls) == 1
    assert executed_calls[0] == (session.id, "Inspect errors")

    schedules = await store.list_schedules("ada@example.com")
    updated = schedules[0]
    assert updated.last_run_at == now
    assert updated.next_run_at == datetime(2026, 10, 12, 12, 10, tzinfo=UTC)


@pytest.mark.asyncio
async def test_schedule_api_endpoints_and_chat_turn(tmp_path) -> None:
    store = MemorySessionStore()
    settings = Settings(
        dev_user=None,
        dev_token=None,
        serving_endpoint=None,
        workspace_host=None,
        agent_root=tmp_path,
    )

    async def _dummy_stream(_msgs: object, _info: object) -> AsyncIterator[str]:
        if False:
            yield ""

    app = create_app(
        store=store,
        settings=settings,
        model_for=lambda _c, _m: FunctionModel(stream_function=_dummy_stream),  # type: ignore[arg-type]
    )

    headers = {
        "x-forwarded-email": "ada@example.com",
        "x-forwarded-access-token": "test-token-ada",
    }

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", headers=headers
    ) as client:
        # Create session
        sess_resp = await client.post("/api/sessions")
        assert sess_resp.status_code == 201
        session_id = sess_resp.json()["id"]

        # 1. Test POST /api/sessions/{session_id}/schedules
        sch_resp = await client.post(
            f"/api/sessions/{session_id}/schedules",
            json={
                "cron_expression": "*/15 * * * *",
                "prompt": "Check Lakeflow jobs status",
            },
        )
        assert sch_resp.status_code == 201
        sch_data = sch_resp.json()
        assert sch_data["cron_expression"] == "*/15 * * * *"
        assert sch_data["status"] == "active"
        schedule_id = sch_data["id"]

        # 2. Test GET /api/schedules
        list_resp = await client.get("/api/schedules")
        assert list_resp.status_code == 200
        items = list_resp.json()
        assert len(items) == 1
        assert items[0]["id"] == schedule_id

        # 3. Test /schedule command in chat turn
        turn_resp = await client.post(
            f"/api/sessions/{session_id}/turns",
            json={"message": '/schedule cron "0 8 * * *" Daily morning health check'},
        )
        assert turn_resp.status_code == 200
        content = turn_resp.text
        assert "Scheduled automation created successfully!" in content

        # Verify second schedule exists
        list_resp_2 = await client.get("/api/schedules")
        items_2 = list_resp_2.json()
        assert len(items_2) == 2

        # 4. Test DELETE /api/schedules/{id}
        del_resp = await client.delete(f"/api/schedules/{schedule_id}")
        assert del_resp.status_code == 204

        # Verify cancelled status
        list_resp_3 = await client.get("/api/schedules")
        items_3 = list_resp_3.json()
        target = next(s for s in items_3 if s["id"] == schedule_id)
        assert target["status"] == "cancelled"
