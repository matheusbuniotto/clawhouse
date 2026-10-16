import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic_ai.models.function import FunctionModel

from clawhouse.agent.turn import TurnContext
from clawhouse.api.app import create_app
from clawhouse.capabilities.schedules import (
    InvalidScheduleCommand,
    calculate_next_run,
    parse_schedule_command,
    run_scheduled_turn,
    schedule_worker,
)
from clawhouse.settings import Settings
from clawhouse.store.shapes import ScheduleEntry, TurnResult
from clawhouse.store.store import LakebaseSessionStore, MemorySessionStore


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

        # Verify creating schedule for nonexistent session returns 404
        bad_resp = await client.post(
            "/api/sessions/99999999-9999-4999-8999-999999999999/schedules",
            json={"cron_expression": "*/5 * * * *", "prompt": "Check"},
        )
        assert bad_resp.status_code == 404


@pytest.mark.asyncio
async def test_claim_due_schedules_uses_skip_locked() -> None:
    now = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)
    mock_pool = AsyncMock()
    mock_pool.fetch = AsyncMock(
        return_value=[
            {
                "id": "11111111-1111-4111-8111-111111111111",
                "session_id": "22222222-2222-4222-8222-222222222222",
                "owner_id": "ada@example.com",
                "cron_expression": "*/5 * * * *",
                "prompt": "Check jobs",
                "status": "active",
                "next_run_at": now,
                "created_at": now,
                "last_run_at": None,
                "last_status": None,
                "last_error": None,
            }
        ]
    )

    store = LakebaseSessionStore(mock_pool)
    result = await store.claim_due_schedules(now)

    assert len(result) == 1
    assert result[0].id == "11111111-1111-4111-8111-111111111111"
    assert result[0].status == "active"

    assert mock_pool.fetch.await_count == 1
    sql = mock_pool.fetch.call_args[0][0]
    assert "FOR UPDATE SKIP LOCKED" in sql
    assert "ORDER BY next_run_at ASC" in sql
    assert "WHERE status = 'active' AND next_run_at <= $1" in sql
    assert mock_pool.fetch.call_args[0][1] == now


@pytest.mark.asyncio
async def test_run_scheduled_turn_success_advances_and_records_status() -> None:
    store = MemorySessionStore()
    session = await store.create_session("ada@example.com")
    now = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)

    schedule = ScheduleEntry(
        id="sch-success",
        session_id=session.id,
        owner_id="ada@example.com",
        cron_expression="*/15 * * * *",
        prompt="Run health check",
        status="active",
        next_run_at=now,
        created_at=now,
    )
    await store.create_schedule(schedule)

    async def fake_run_turn(sess_id: str, prompt: str, ctx: TurnContext) -> TurnResult:
        del sess_id, prompt, ctx
        return TurnResult(
            session_id=session.id,
            status="ok",
            reply="Healthy",
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
    assert result.status == "ok"
    assert result.reply == "Healthy"

    schedules = await store.list_schedules("ada@example.com")
    updated = schedules[0]
    assert updated.last_run_at == now
    assert updated.next_run_at == datetime(2026, 10, 12, 12, 15, tzinfo=UTC)
    assert updated.last_status == "ok"
    assert updated.last_error is None


@pytest.mark.asyncio
async def test_run_scheduled_turn_error_advances_and_records_error() -> None:
    store = MemorySessionStore()
    session = await store.create_session("ada@example.com")
    now = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)

    schedule = ScheduleEntry(
        id="sch-error",
        session_id=session.id,
        owner_id="ada@example.com",
        cron_expression="*/20 * * * *",
        prompt="Failing check",
        status="active",
        next_run_at=now,
        created_at=now,
    )
    await store.create_schedule(schedule)

    async def fake_run_turn(_sess_id: str, _prompt: str, _ctx: TurnContext) -> TurnResult:
        raise RuntimeError("SQL Warehouse unavailable")

    def fake_make_ctx(sch: ScheduleEntry) -> TurnContext:
        return TurnContext(
            owner_id=sch.owner_id,
            store=store,
            model=None,  # type: ignore[arg-type]
            now=lambda: now,
        )

    with pytest.raises(RuntimeError, match="SQL Warehouse unavailable"):
        await run_scheduled_turn(
            schedule,
            store=store,
            run_turn_fn=fake_run_turn,
            make_turn_ctx=fake_make_ctx,
            now_fn=lambda: now,
        )

    schedules = await store.list_schedules("ada@example.com")
    updated = schedules[0]
    assert updated.last_run_at == now
    assert updated.next_run_at == datetime(2026, 10, 12, 12, 20, tzinfo=UTC)
    assert updated.last_status == "error"
    assert updated.last_error == "SQL Warehouse unavailable"


@pytest.mark.asyncio
async def test_schedule_worker_continues_on_item_error() -> None:
    store = MemorySessionStore()
    session = await store.create_session("ada@example.com")
    now = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)

    sch1 = ScheduleEntry(
        id="sch-failing",
        session_id=session.id,
        owner_id="ada@example.com",
        cron_expression="*/10 * * * *",
        prompt="Fail please",
        status="active",
        next_run_at=now,
        created_at=now,
    )
    sch2 = ScheduleEntry(
        id="sch-healthy",
        session_id=session.id,
        owner_id="ada@example.com",
        cron_expression="*/30 * * * *",
        prompt="Succeed please",
        status="active",
        next_run_at=now,
        created_at=now,
    )
    await store.create_schedule(sch1)
    await store.create_schedule(sch2)

    executed: list[str] = []
    stop_event = asyncio.Event()

    async def fake_run_turn(sess_id: str, prompt: str, ctx: TurnContext) -> TurnResult:
        del sess_id, ctx
        executed.append(prompt)
        if prompt == "Succeed please":
            stop_event.set()
        if prompt == "Fail please":
            raise RuntimeError("something blew up")
        return TurnResult(
            session_id=session.id,
            status="ok",
            reply="Success",
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

    await asyncio.wait_for(
        schedule_worker(
            store,
            fake_run_turn,
            fake_make_ctx,
            poll_interval_seconds=0.01,
            stop_event=stop_event,
        ),
        timeout=2.0,
    )

    assert executed == ["Fail please", "Succeed please"]

    schedules = {s.id: s for s in await store.list_schedules("ada@example.com")}
    assert schedules["sch-failing"].last_status == "error"
    assert schedules["sch-failing"].last_error == "something blew up"
    assert schedules["sch-failing"].next_run_at > now

    assert schedules["sch-healthy"].last_status == "ok"
    assert schedules["sch-healthy"].last_error is None
    assert schedules["sch-healthy"].next_run_at > now
