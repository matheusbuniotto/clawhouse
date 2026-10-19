"""Fired jobs: chat scheduling, the Databricks hook, and Slack delivery."""

import asyncio
import base64
import json
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

from databricks.sdk.errors import PermissionDenied
from databricks.sdk.service.jobs import PauseStatus
from httpx import ASGITransport, AsyncClient
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel

from clawhouse.agent.pauses import DEFAULT_APPROVAL_REQUIRED_TOOLS
from clawhouse.agent.turn import TurnContext, TurnResult, resume_turn, run_turn
from clawhouse.api.app import create_app
from clawhouse.capabilities import fired as fired_mod
from clawhouse.capabilities.databricks import DatabricksCapability, DatabricksTools, JobsIdentity
from clawhouse.capabilities.schedules import create_schedule_entry, run_scheduled_turn
from clawhouse.capabilities.workspace import resolve_agent_workspace
from clawhouse.settings import Settings
from clawhouse.store.schema import SCHEMA
from clawhouse.store.shapes import FiredDelivery, FiredJob
from clawhouse.store.store import MemorySessionStore

SESSION = "00000000-0000-4000-8000-0000000000b2"
OWNER = "user-1"
SLACK = "https://hooks.slack.com/services/T/B/secret"
PASSWORD = "hook-secret"
NOW = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)


async def _says_done(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str]:
    del messages, info
    yield "done"


def _calls_tool(name: str, args: Mapping[str, object]) -> FunctionModel:
    async def stream(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        del info
        returned = any(
            getattr(part, "part_kind", "") == "tool-return" for m in messages for part in m.parts
        )
        if returned:
            yield "done"
            return
        yield {0: DeltaToolCall(name=name, json_args=json.dumps(args), tool_call_id="call-1")}

    return FunctionModel(stream_function=stream)


def _settings(**overrides: object) -> Settings:
    base = Settings(
        dev_user=None,
        dev_token=None,
        serving_endpoint=None,
        workspace_host=None,
        job_hook_password=PASSWORD,
        app_base_url="https://app.example",
    )
    if not overrides:
        return base
    return Settings(
        dev_user=overrides.get("dev_user", base.dev_user),  # type: ignore[arg-type]
        dev_token=overrides.get("dev_token", base.dev_token),  # type: ignore[arg-type]
        serving_endpoint=None,
        workspace_host=overrides.get("workspace_host", base.workspace_host),  # type: ignore[arg-type]
        jobs_sp_client_id=overrides.get("jobs_sp_client_id"),  # type: ignore[arg-type]
        jobs_sp_client_secret=overrides.get("jobs_sp_client_secret"),  # type: ignore[arg-type]
        job_hook_password=str(overrides.get("job_hook_password", PASSWORD)),
        app_base_url=str(overrides.get("app_base_url", "https://app.example")),
    )


def _db_client(job_id: int = 42) -> MagicMock:
    client = MagicMock()
    client.jobs.create.return_value = MagicMock(job_id=job_id)
    client.notification_destinations.list.return_value = []
    client.notification_destinations.create.return_value = MagicMock(id="dest-1")
    return client


def _ctx(
    client: MagicMock,
    store: MemorySessionStore,
    *,
    model: FunctionModel | None = None,
    settings: Settings | None = None,
    fired_job: bool = False,
) -> TurnContext:
    return TurnContext(
        owner_id=OWNER,
        store=store,
        model=model or FunctionModel(stream_function=_says_done),
        now=lambda: NOW,
        user_token="client-credential",
        fired_job=fired_job,
        headless=fired_job,
        databricks_capability=DatabricksCapability(
            client_factory=lambda _token: client,
            warehouse_id="wh-1",
            settings=settings,
            user_token="client-credential",
        ),
    )


def _tool_result(result: TurnResult) -> dict[str, object]:
    entry = next(e for e in result.transcript if e.role == "tool_result")
    return json.loads(entry.content)


def _auth(user: str = "clawhouse", password: str = PASSWORD) -> str:
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return f"Basic {token}"


def _sql_client(count: int) -> MagicMock:
    sql = MagicMock()
    sql.as_dict.return_value = {"rows": [f"r{i}" for i in range(1, count + 1)]}
    client = MagicMock()
    client.jobs.get_run_output.return_value = MagicMock(sql_output=sql)
    return client


def _grid_client(rows: int, columns: int) -> MagicMock:
    sql = MagicMock()
    sql.as_dict.return_value = {
        "rows": [[f"c{col}" for col in range(columns)] for _ in range(rows)]
    }
    client = MagicMock()
    client.jobs.get_run_output.return_value = MagicMock(sql_output=sql)
    return client


async def _fired(  # noqa: PLR0913
    store: MemorySessionStore,
    *,
    kind: str = "sql",
    job_id: int | None = 7,
    schedule_id: str | None = None,
    instructions: str = "",
    agent_name: str | None = None,
) -> FiredJob:
    job = FiredJob(
        id=str(uuid4()),
        session_id=SESSION,
        owner_id=OWNER,
        kind=kind,  # type: ignore[arg-type]
        name="nightly",
        slack_webhook_url=SLACK,
        instructions=instructions,
        agent_name=agent_name,
        databricks_job_id=job_id,
        schedule_id=schedule_id,
    )
    await store.insert_fired_job(job)
    return job


def _app(store: MemorySessionStore, settings: Settings, client: MagicMock):
    async def _dummy(_messages: object, _info: object) -> AsyncIterator[str]:
        if False:
            yield ""

    app = create_app(
        store=store,
        settings=settings,
        model_for=lambda _caller, _model: FunctionModel(stream_function=_dummy),  # type: ignore[arg-type]
    )
    app.state.job_hook_client = client
    return app


async def _post(app, payload: dict[str, object], auth: str | None = None):
    headers = {"authorization": auth} if auth is not None else {}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.post("/api/job-hooks", json=payload, headers=headers)


def _payload(event: str, job_id: int = 7, run_id: int = 11) -> dict[str, object]:
    return {"event_type": event, "job": {"job_id": job_id}, "run": {"run_id": run_id}}


async def test_jobs_schedule_pauses_before_any_write() -> None:
    client = _db_client()
    store = MemorySessionStore()
    args = {
        "name": "nightly",
        "kind": "sql",
        "cron_expression": "0 12 * * *",
        "query": "SELECT 1",
        "slack_webhook_url": SLACK,
    }
    paused = await run_turn(
        SESSION, "go", ctx=_ctx(client, store, model=_calls_tool("jobs_schedule", args))
    )
    assert paused.status == "pending_approval"
    client.workspace.upload.assert_not_called()
    client.jobs.create.assert_not_called()
    assert await store.list_schedules(OWNER) == ()


async def test_jobs_schedule_sql_uploads_raw_sql_and_webhooks() -> None:
    client = _db_client()
    store = MemorySessionStore()
    args = {
        "name": "nightly",
        "kind": "sql",
        "cron_expression": "0 12 * * *",
        "query": "SELECT 1",
        "slack_webhook_url": SLACK,
    }
    paused = await run_turn(
        SESSION,
        "go",
        ctx=_ctx(client, store, model=_calls_tool("jobs_schedule", args), settings=_settings()),
    )
    resumed = await resume_turn(
        SESSION, paused.approval_id or "", "approved", ctx=_ctx(client, store, settings=_settings())
    )
    assert resumed.status == "ok"
    uploaded = client.workspace.upload.call_args.kwargs["content"].read().decode()
    assert "ai_query" not in uploaded
    assert "SELECT 1" in uploaded
    hooks = client.jobs.create.call_args.kwargs["webhook_notifications"]
    assert hooks.on_success[0].id == "dest-1"
    assert hooks.on_failure[0].id == "dest-1"


async def test_jobs_schedule_cron_noon_is_quartz_utc_unpaused() -> None:
    client = _db_client()
    store = MemorySessionStore()
    args = {
        "name": "noon",
        "kind": "sql",
        "cron_expression": "0 12 * * *",
        "query": "SELECT 1",
        "slack_webhook_url": SLACK,
    }
    paused = await run_turn(
        SESSION,
        "go",
        ctx=_ctx(client, store, model=_calls_tool("jobs_schedule", args), settings=_settings()),
    )
    await resume_turn(
        SESSION, paused.approval_id or "", "approved", ctx=_ctx(client, store, settings=_settings())
    )
    schedule = client.jobs.create.call_args.kwargs["schedule"]
    assert schedule.quartz_cron_expression == "0 0 12 * * ?"
    assert schedule.timezone_id == "UTC"
    assert schedule.pause_status == PauseStatus.UNPAUSED


async def test_jobs_schedule_sql_agent_stores_agent_and_skips_ai_query() -> None:
    client = _db_client(99)
    store = MemorySessionStore()
    args = {
        "name": "analyze",
        "kind": "sql_agent",
        "cron_expression": "0 12 * * *",
        "query": "SELECT fare FROM trips",
        "agent_name": "main",
        "slack_webhook_url": SLACK,
    }
    paused = await run_turn(
        SESSION,
        "go",
        ctx=_ctx(client, store, model=_calls_tool("jobs_schedule", args), settings=_settings()),
    )
    with patch(
        "clawhouse.capabilities.databricks.jobs_tasks.build_agentic_query",
        side_effect=AssertionError("ai_query"),
    ):
        resumed = await resume_turn(
            SESSION,
            paused.approval_id or "",
            "approved",
            ctx=_ctx(client, store, settings=_settings()),
        )
    assert resumed.status == "ok"
    uploaded = client.workspace.upload.call_args.kwargs["content"].read().decode()
    assert "ai_query" not in uploaded
    stored = await store.fired_job_by_databricks_id(99)
    assert stored is not None
    assert stored.agent_name == "main"


async def test_jobs_schedule_agent_creates_schedule_without_databricks_job() -> None:
    client = _db_client()
    store = MemorySessionStore()
    args = {
        "name": "digest",
        "kind": "agent",
        "cron_expression": "0 12 * * *",
        "agent_name": "main",
        "instructions": "Summarize yesterday",
        "slack_webhook_url": SLACK,
    }
    paused = await run_turn(
        SESSION,
        "go",
        ctx=_ctx(client, store, model=_calls_tool("jobs_schedule", args), settings=_settings()),
    )
    resumed = await resume_turn(
        SESSION, paused.approval_id or "", "approved", ctx=_ctx(client, store, settings=_settings())
    )
    assert resumed.status == "ok"
    client.jobs.create.assert_not_called()
    schedules = await store.list_schedules(OWNER)
    assert len(schedules) == 1
    assert schedules[0].prompt == "Summarize yesterday"


def test_fired_job_kind_check() -> None:
    assert "CHECK (kind IN ('sql', 'sql_agent', 'agent'))" in SCHEMA


async def test_jobs_schedule_sql_uses_service_principal() -> None:
    instance = _db_client()
    store = MemorySessionStore()
    settings = _settings(
        jobs_sp_client_id="sp-client",
        jobs_sp_client_secret="sp-secret",
        workspace_host="https://adb.example",
    )
    args = {
        "name": "nightly",
        "kind": "sql",
        "cron_expression": "0 12 * * *",
        "query": "SELECT 1",
        "slack_webhook_url": SLACK,
    }
    mock_cls = MagicMock(return_value=instance)
    with patch("clawhouse.capabilities.databricks.WorkspaceClient", mock_cls):
        paused = await run_turn(
            SESSION,
            "go",
            ctx=_ctx(instance, store, model=_calls_tool("jobs_schedule", args), settings=settings),
        )
        await resume_turn(
            SESSION,
            paused.approval_id or "",
            "approved",
            ctx=_ctx(instance, store, settings=settings),
        )
    mock_cls.assert_called_with(
        client_id="sp-client",
        client_secret="sp-secret",
        auth_type="oauth-m2m",
        host="https://adb.example",
    )
    instance.jobs.create.assert_called()


async def test_jobs_schedule_rejects_invalid() -> None:
    cases = [
        {
            "kind": "nope",
            "query": "SELECT 1",
            "agent_name": "main",
            "instructions": "x",
            "slack_webhook_url": SLACK,
        },
        {
            "kind": "sql",
            "query": "",
            "agent_name": "",
            "instructions": "",
            "slack_webhook_url": SLACK,
        },
        {
            "kind": "sql_agent",
            "query": "",
            "agent_name": "main",
            "instructions": "",
            "slack_webhook_url": SLACK,
        },
        {
            "kind": "sql_agent",
            "query": "SELECT 1",
            "agent_name": "",
            "instructions": "",
            "slack_webhook_url": SLACK,
        },
        {
            "kind": "agent",
            "query": "",
            "agent_name": "",
            "instructions": "go",
            "slack_webhook_url": SLACK,
        },
        {
            "kind": "agent",
            "query": "",
            "agent_name": "main",
            "instructions": "",
            "slack_webhook_url": SLACK,
        },
        {
            "kind": "sql",
            "query": "SELECT 1",
            "agent_name": "",
            "instructions": "",
            "slack_webhook_url": "http://hooks.example/a",
        },
        {
            "kind": "sql_agent",
            "query": "SELECT 1",
            "agent_name": "Nope",
            "instructions": "",
            "slack_webhook_url": SLACK,
        },
    ]
    for case in cases:
        client = _db_client()
        store = MemorySessionStore()
        tools = DatabricksTools(
            client,
            "wh-1",
            jobs_identity=JobsIdentity(kind="user_obo", client=client, label="user"),
            store=store,
            session_id=SESSION,
            owner_id=OWNER,
            settings=_settings(),
        )
        result = await tools.jobs_schedule(
            "nightly",
            case["kind"],  # type: ignore[arg-type]
            "0 12 * * *",
            case["slack_webhook_url"],
            query=case["query"],
            agent_name=case["agent_name"],
            instructions=case["instructions"],
        )
        assert "error" in result
        client.jobs.create.assert_not_called()
        assert await store.list_schedules(OWNER) == ()


async def test_jobs_schedule_deny_writes_nothing() -> None:
    client = _db_client()
    store = MemorySessionStore()
    args = {
        "name": "nightly",
        "kind": "sql",
        "cron_expression": "0 12 * * *",
        "query": "SELECT 1",
        "slack_webhook_url": SLACK,
    }
    paused = await run_turn(
        SESSION,
        "go",
        ctx=_ctx(client, store, model=_calls_tool("jobs_schedule", args), settings=_settings()),
    )
    denied = await resume_turn(
        SESSION, paused.approval_id or "", "denied", ctx=_ctx(client, store, settings=_settings())
    )
    assert denied.status == "ok"
    client.jobs.create.assert_not_called()
    assert await store.list_schedules(OWNER) == ()


async def test_jobs_schedule_keeps_sql_file_when_create_fails() -> None:
    client = _db_client()
    client.jobs.create.side_effect = RuntimeError("boom")
    store = MemorySessionStore()
    args = {
        "name": "nightly",
        "kind": "sql",
        "cron_expression": "0 12 * * *",
        "query": "SELECT 1",
        "slack_webhook_url": SLACK,
    }
    paused = await run_turn(
        SESSION,
        "go",
        ctx=_ctx(client, store, model=_calls_tool("jobs_schedule", args), settings=_settings()),
    )
    resumed = await resume_turn(
        SESSION, paused.approval_id or "", "approved", ctx=_ctx(client, store, settings=_settings())
    )
    body = _tool_result(resumed)
    assert "error" in body
    client.workspace.upload.assert_called()
    client.workspace.delete.assert_not_called()
    assert await store.fired_job_by_databricks_id(42) is None


async def test_jobs_schedule_destination_forbidden() -> None:
    client = _db_client()
    client.notification_destinations.list.side_effect = PermissionDenied("no")
    store = MemorySessionStore()
    args = {
        "name": "nightly",
        "kind": "sql",
        "cron_expression": "0 12 * * *",
        "query": "SELECT 1",
        "slack_webhook_url": SLACK,
    }
    paused = await run_turn(
        SESSION,
        "go",
        ctx=_ctx(client, store, model=_calls_tool("jobs_schedule", args), settings=_settings()),
    )
    resumed = await resume_turn(
        SESSION, paused.approval_id or "", "approved", ctx=_ctx(client, store, settings=_settings())
    )
    assert _tool_result(resumed)["error"] == "notification destination forbidden"
    client.jobs.create.assert_not_called()


def test_lakeflow_skill_names_fired_kinds_without_ai_query() -> None:
    text = (
        resolve_agent_workspace(__import__("pathlib").Path(__file__).resolve().parents[1], "main")
        .skills.joinpath("lakeflow-jobs/SKILL.md")
        .read_text()
    )
    assert "sql_agent" in text
    assert "`sql`" in text or "\n- `sql`" in text
    assert "`agent`" in text
    assert "do not use ai_query" in text


def test_jobs_schedule_is_approval_required() -> None:
    assert "jobs_schedule" in DEFAULT_APPROVAL_REQUIRED_TOOLS


async def test_job_hook_sql_success_posts_twenty_rows(monkeypatch) -> None:
    posted: list[str] = []

    def _capture(url: str, text: str) -> int:
        del url
        posted.append(text)
        return 200

    monkeypatch.setattr(fired_mod, "post_slack", _capture)
    store = MemorySessionStore()
    await _fired(store)
    app = _app(store, _settings(), _sql_client(21))
    response = await _post(app, _payload("jobs.on_success"), _auth())
    assert response.status_code == 200
    assert response.json() == {"delivered": True}
    assert len(posted) == 1
    assert "7" in posted[0]
    assert "11" in posted[0]
    assert "r20" in posted[0]
    assert "r21" not in posted[0]


async def test_job_hook_duplicate_does_not_post(monkeypatch) -> None:
    posted: list[str] = []
    monkeypatch.setattr(fired_mod, "post_slack", lambda _url, text: posted.append(text) or 200)
    store = MemorySessionStore()
    await _fired(store)
    app = _app(store, _settings(), _sql_client(1))
    first = await _post(app, _payload("jobs.on_success"), _auth())
    second = await _post(app, _payload("jobs.on_success"), _auth())
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json() == {"duplicate": True}
    assert len(posted) == 1


def test_delivery_unique_sql() -> None:
    assert "fired_delivery_run_idx" in SCHEMA
    assert "ON clawhouse.deliveries (databricks_job_id, run_id, event_type)" in SCHEMA
    assert "fired_delivery_slot_idx" in SCHEMA
    assert "ON clawhouse.deliveries (schedule_id, next_run_at)" in SCHEMA


async def test_job_hook_rejects_bad_basic_auth(monkeypatch) -> None:
    posted: list[str] = []
    monkeypatch.setattr(fired_mod, "post_slack", lambda _url, text: posted.append(text) or 200)
    store = MemorySessionStore()
    await _fired(store)
    app = _app(store, _settings(), _sql_client(1))
    wrong_user = await _post(app, _payload("jobs.on_success"), _auth(user="other"))
    wrong_password = await _post(app, _payload("jobs.on_success"), _auth(password="nope"))
    empty = _app(store, _settings(job_hook_password=""), _sql_client(1))
    empty_password = await _post(empty, _payload("jobs.on_success"), _auth(password=""))
    for response in (wrong_user, wrong_password, empty_password):
        assert response.status_code == 401
        assert response.json() == {"error": "unauthorized"}
    assert posted == []


async def test_job_hook_unknown_job_is_404(monkeypatch) -> None:
    monkeypatch.setattr(fired_mod, "post_slack", lambda _url, _text: 200)
    store = MemorySessionStore()
    app = _app(store, _settings(), _sql_client(1))
    response = await _post(app, _payload("jobs.on_success", job_id=99), _auth())
    assert response.status_code == 404
    assert response.json() == {"error": "unknown job"}


async def test_job_hook_failure_posts_without_agent(monkeypatch) -> None:
    posted: list[str] = []
    calls: list[object] = []
    monkeypatch.setattr(fired_mod, "post_slack", lambda _url, text: posted.append(text) or 200)

    async def _run(*args: object, **kwargs: object) -> str:
        calls.append(args)
        return "nope"

    monkeypatch.setattr("clawhouse.api.routes.job_hooks.run_turn", _run)
    store = MemorySessionStore()
    await _fired(store)
    app = _app(store, _settings(), _sql_client(1))
    response = await _post(app, _payload("jobs.on_failure"), _auth())
    assert response.status_code == 200
    assert "jobs.on_failure" in posted[0]
    assert "7" in posted[0]
    assert "11" in posted[0]
    assert calls == []


async def test_job_hook_start_is_ignored(monkeypatch) -> None:
    posted: list[str] = []
    calls: list[object] = []
    monkeypatch.setattr(fired_mod, "post_slack", lambda _url, text: posted.append(text) or 200)

    async def _run(*_args: object, **_kwargs: object) -> str:
        calls.append(True)
        return "nope"

    monkeypatch.setattr("clawhouse.api.routes.job_hooks.run_turn", _run)
    store = MemorySessionStore()
    await _fired(store)
    app = _app(store, _settings(), _sql_client(1))
    response = await _post(app, _payload("jobs.on_start"), _auth())
    assert response.status_code == 200
    assert posted == []
    assert calls == []


async def test_job_hook_slack_failure_returns_502_and_clears_delivery(monkeypatch) -> None:
    monkeypatch.setattr(fired_mod, "post_slack", lambda _url, _text: 500)
    store = MemorySessionStore()
    await _fired(store)
    app = _app(store, _settings(), _sql_client(1))
    response = await _post(app, _payload("jobs.on_success"), _auth())
    assert response.status_code == 502
    assert response.json() == {"delivered": False}
    assert await store.delivery_for_run(7, 11, "jobs.on_success") is None


async def test_job_hook_existing_delivery_skips_slack(monkeypatch) -> None:
    posted: list[str] = []
    monkeypatch.setattr(fired_mod, "post_slack", lambda _url, text: posted.append(text) or 200)
    store = MemorySessionStore()
    job = await _fired(store)
    await store.try_insert_delivery(
        FiredDelivery(
            id=str(uuid4()),
            fired_job_id=job.id,
            databricks_job_id=7,
            run_id=11,
            event_type="jobs.on_success",
        )
    )
    app = _app(store, _settings(), _sql_client(1))
    response = await _post(app, _payload("jobs.on_success"), _auth())
    assert response.status_code == 200
    assert response.json() == {"duplicate": True}
    assert posted == []


async def test_job_hook_log_omits_secrets(monkeypatch, caplog) -> None:
    monkeypatch.setattr(fired_mod, "post_slack", lambda _url, _text: 200)
    store = MemorySessionStore()
    await _fired(store)
    app = _app(store, _settings(), _sql_client(1))
    with caplog.at_level("INFO", logger="clawhouse.fired"):
        await _post(app, _payload("jobs.on_success"), _auth())
    text = caplog.text
    assert "7" in text
    assert "11" in text
    assert PASSWORD not in text
    assert SLACK not in text


async def test_job_hook_destination_shape() -> None:
    client = _db_client()
    store = MemorySessionStore()
    settings = _settings()
    args = {
        "name": "nightly",
        "kind": "sql",
        "cron_expression": "0 12 * * *",
        "query": "SELECT 1",
        "slack_webhook_url": SLACK,
    }
    paused = await run_turn(
        SESSION,
        "go",
        ctx=_ctx(client, store, model=_calls_tool("jobs_schedule", args), settings=settings),
    )
    await resume_turn(
        SESSION, paused.approval_id or "", "approved", ctx=_ctx(client, store, settings=settings)
    )
    created = client.notification_destinations.create.call_args.kwargs
    webhook = created["config"].generic_webhook
    assert created["display_name"] == "clawhouse-job-hook"
    assert webhook.username == "clawhouse"
    assert webhook.password == PASSWORD
    assert webhook.url == "https://app.example/api/job-hooks"
    hooks = client.jobs.create.call_args.kwargs["webhook_notifications"]
    assert hooks.on_success[0].id == "dest-1"
    assert hooks.on_failure[0].id == "dest-1"


def test_create_app_mounts_job_hook() -> None:
    app = _app(MemorySessionStore(), _settings(), MagicMock())
    mounted = [
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/job-hooks"
        and "POST" in getattr(route, "methods", set())
    ]
    assert len(mounted) == 1


async def test_job_hook_concurrent_posts_once(monkeypatch) -> None:
    posted: list[str] = []
    monkeypatch.setattr(fired_mod, "post_slack", lambda _url, text: posted.append(text) or 200)
    store = MemorySessionStore()
    await _fired(store)
    app = _app(store, _settings(), _sql_client(1))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first, second = await asyncio.gather(
            client.post(
                "/api/job-hooks",
                json=_payload("jobs.on_success"),
                headers={"authorization": _auth()},
            ),
            client.post(
                "/api/job-hooks",
                json=_payload("jobs.on_success"),
                headers={"authorization": _auth()},
            ),
        )
    assert first.status_code == 200
    assert second.status_code == 200
    bodies = {
        first.json().get("delivered"),
        first.json().get("duplicate"),
        second.json().get("delivered"),
        second.json().get("duplicate"),
    }
    assert True in bodies
    assert len(posted) == 1


async def test_job_hook_sql_agent_runs_one_headless_turn(monkeypatch) -> None:
    seen: list[tuple[str, TurnContext]] = []

    async def _run(session_id: str, message: str, *, ctx: TurnContext) -> TurnResult:
        seen.append((message, ctx))
        return TurnResult(
            session_id=session_id, status="ok", reply="insight", error=None, transcript=()
        )

    monkeypatch.setattr("clawhouse.api.routes.job_hooks.run_turn", _run)
    monkeypatch.setattr(fired_mod, "post_slack", lambda _url, _text: 200)
    store = MemorySessionStore()
    await _fired(store, kind="sql_agent", instructions="Look hard", agent_name="main")
    app = _app(store, _settings(), _sql_client(101))
    response = await _post(app, _payload("jobs.on_success"), _auth())
    assert response.status_code == 200
    assert len(seen) == 1
    message, ctx = seen[0]
    assert ctx.headless is True
    assert "r100" in message
    assert "r101" not in message
    assert "@main" in message


async def test_job_hook_empty_instructions_use_analyze_sentence(monkeypatch) -> None:
    seen: list[str] = []

    async def _run(session_id: str, message: str, *, ctx: TurnContext) -> TurnResult:
        del ctx
        seen.append(message)
        return TurnResult(session_id=session_id, status="ok", reply="ok", error=None, transcript=())

    monkeypatch.setattr("clawhouse.api.routes.job_hooks.run_turn", _run)
    monkeypatch.setattr(fired_mod, "post_slack", lambda _url, _text: 200)
    store = MemorySessionStore()
    await _fired(store, kind="sql_agent", instructions="", agent_name="main")
    app = _app(store, _settings(), _sql_client(1))
    await _post(app, _payload("jobs.on_success"), _auth())
    assert "Analyze these query results." in seen[0]


async def test_job_hook_slack_reply_cuts_at_3000(monkeypatch) -> None:
    posted: list[str] = []

    async def _run(session_id: str, message: str, *, ctx: TurnContext) -> TurnResult:
        del message, ctx
        return TurnResult(
            session_id=session_id, status="ok", reply="a" * 3001, error=None, transcript=()
        )

    monkeypatch.setattr("clawhouse.api.routes.job_hooks.run_turn", _run)
    monkeypatch.setattr(fired_mod, "post_slack", lambda _url, text: posted.append(text) or 200)
    store = MemorySessionStore()
    await _fired(store, kind="sql_agent", instructions="go", agent_name="main")
    app = _app(store, _settings(), _sql_client(1))
    await _post(app, _payload("jobs.on_success"), _auth())
    assert len(posted[0]) == 3000


async def test_fired_turn_denies_sensitive_tools() -> None:
    sheet_id = "a" * 20
    args_for = {
        "jobs_run_now": {"job_id": 1},
        "jobs_cancel_run": {"run_id": 1},
        "jobs_create": {"name": "n"},
        "jobs_edit": {"job_id": 1},
        "jobs_delete": {"job_id": 1},
        "delivery_send_webhook": {"url": "https://example.com/hook", "payload": {"text": "hi"}},
        "create_google_sheet": {"sheet": {"title": "T", "rows": [["a"]]}},
        "update_google_sheet": {
            "update": {"spreadsheet_id": sheet_id, "tab": "Sheet1", "rows": [["a"]]}
        },
        "run_python_analysis": {"code": "print(1)"},
        "jobs_schedule": {
            "name": "n",
            "kind": "sql",
            "cron_expression": "0 12 * * *",
            "slack_webhook_url": SLACK,
            "query": "SELECT 1",
        },
    }
    for name, args in args_for.items():
        store = MemorySessionStore()
        client = _db_client()
        result = await run_turn(
            SESSION,
            "go",
            ctx=_ctx(client, store, model=_calls_tool(name, args), fired_job=True),
        )
        blob = " ".join(entry.content for entry in result.transcript)
        assert "headless fired job: tool not approved" in blob
        assert await store.list_approvals(OWNER, status="pending") == ()


async def test_fired_turn_skips_sheet_without_token(monkeypatch) -> None:
    sheets: list[object] = []
    posted: list[str] = []

    async def _sheet(*args: object, **kwargs: object) -> dict[str, str]:
        sheets.append(args)
        return {"url": "https://docs.google.com/spreadsheets/d/abc"}

    async def _run(session_id: str, message: str, *, ctx: TurnContext) -> TurnResult:
        del message, ctx
        return TurnResult(
            session_id=session_id, status="ok", reply="insight", error=None, transcript=()
        )

    monkeypatch.setattr(fired_mod, "write_new_sheet", _sheet)
    monkeypatch.setattr(fired_mod, "post_slack", lambda _url, text: posted.append(text) or 200)
    monkeypatch.setattr("clawhouse.api.routes.job_hooks.run_turn", _run)
    store = MemorySessionStore()
    await _fired(store, kind="sql_agent", instructions="go", agent_name="main")
    app = _app(store, _settings(), _sql_client(1))
    response = await _post(app, _payload("jobs.on_success"), _auth())
    assert response.status_code == 200
    assert posted
    assert sheets == []
    saved = await store.delivery_for_run(7, 11, "jobs.on_success")
    assert saved is not None
    assert saved.sheet_status == "skipped"


async def test_fired_turn_caps_sheet_and_links_it(monkeypatch) -> None:
    seen: list[object] = []
    posted: list[str] = []

    async def _sheet(_token: str, sheet: object, host: str | None = None) -> dict[str, str]:
        del host
        seen.append(sheet)
        return {"url": "https://docs.google.com/spreadsheets/d/abc"}

    async def _run(session_id: str, message: str, *, ctx: TurnContext) -> TurnResult:
        del message, ctx
        return TurnResult(
            session_id=session_id, status="ok", reply="insight", error=None, transcript=()
        )

    monkeypatch.setattr(fired_mod, "write_new_sheet", _sheet)
    monkeypatch.setattr(fired_mod, "post_slack", lambda _url, text: posted.append(text) or 200)
    monkeypatch.setattr("clawhouse.api.routes.job_hooks.run_turn", _run)
    store = MemorySessionStore()
    await _fired(store, kind="sql_agent", instructions="go", agent_name="main")
    settings = _settings(dev_user=OWNER, dev_token="user-token")
    app = _app(store, settings, _grid_client(501, 27))
    await _post(app, _payload("jobs.on_success"), _auth())
    sheet = seen[0]
    assert len(sheet.rows) == 500  # type: ignore[attr-defined]
    assert len(sheet.rows[0]) == 26  # type: ignore[attr-defined]
    assert "https://docs.google.com/spreadsheets/d/" in posted[0]


async def test_agent_schedule_posts_reply(monkeypatch) -> None:
    posted: list[str] = []
    seen: list[tuple[str, TurnContext]] = []
    monkeypatch.setattr(fired_mod, "post_slack", lambda _url, text: posted.append(text) or 200)
    store = MemorySessionStore()
    schedule = await create_schedule_entry(
        store,
        session_id=SESSION,
        owner_id=OWNER,
        cron_expression="0 12 * * *",
        prompt="Summarize yesterday",
        now=NOW,
    )
    await _fired(
        store,
        kind="agent",
        job_id=None,
        schedule_id=schedule.id,
        instructions="Summarize yesterday",
        agent_name="main",
    )

    async def _run(session_id: str, message: str, ctx: TurnContext) -> TurnResult:
        seen.append((message, ctx))
        return TurnResult(
            session_id=session_id, status="ok", reply="b" * 3001, error=None, transcript=()
        )

    await run_scheduled_turn(
        schedule,
        store,
        _run,
        lambda _sch: TurnContext(owner_id=OWNER, store=store, model=MagicMock(), now=lambda: NOW),
        now_fn=lambda: schedule.next_run_at,
    )
    assert len(seen) == 1
    assert seen[0][0] == "Summarize yesterday"
    assert seen[0][1].headless is True
    assert len(posted) == 1
    assert len(posted[0]) == 3000


async def test_agent_schedule_delivery_blocks_second_post(monkeypatch) -> None:
    posted: list[str] = []
    monkeypatch.setattr(fired_mod, "post_slack", lambda _url, text: posted.append(text) or 200)
    store = MemorySessionStore()
    schedule = await create_schedule_entry(
        store,
        session_id=SESSION,
        owner_id=OWNER,
        cron_expression="0 12 * * *",
        prompt="Summarize yesterday",
        now=NOW,
    )
    job = await _fired(
        store,
        kind="agent",
        job_id=None,
        schedule_id=schedule.id,
        instructions="Summarize yesterday",
        agent_name="main",
    )
    await store.try_insert_delivery(
        FiredDelivery(
            id=str(uuid4()),
            fired_job_id=job.id,
            schedule_id=schedule.id,
            next_run_at=schedule.next_run_at,
        )
    )

    async def _run(session_id: str, message: str, ctx: TurnContext) -> TurnResult:
        del message, ctx
        return TurnResult(
            session_id=session_id, status="ok", reply="done", error=None, transcript=()
        )

    await run_scheduled_turn(
        schedule,
        store,
        _run,
        lambda _sch: TurnContext(owner_id=OWNER, store=store, model=MagicMock(), now=lambda: NOW),
        now_fn=lambda: schedule.next_run_at,
    )
    assert posted == []
