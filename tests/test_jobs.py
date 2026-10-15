"""Jobs screen (#97): schedules and Databricks jobs the user may see, in one list."""

from datetime import UTC, datetime
from types import SimpleNamespace as NS
from typing import Any

import pytest
from databricks.sdk.service.jobs import (
    CronSchedule,
    JobAccessControlResponse,
    JobPermission,
    JobPermissionLevel,
    JobPermissions,
    PauseStatus,
)
from httpx import ASGITransport, AsyncClient

from clawhouse.turn import TurnContext  # noqa: F401  # isort: skip
from clawhouse.app import create_app
from clawhouse.capabilities.jobs import (
    DatabricksJobs,
    Principal,
    humanize_cron,
    levels_for,
    quartz_to_cron,
)
from clawhouse.identity import Caller
from clawhouse.settings import Settings
from clawhouse.shapes import ScheduleEntry
from clawhouse.store import MemorySessionStore

OWNER = "ada@example.com"
HEADERS = {"x-forwarded-email": OWNER, "x-forwarded-access-token": "dapi-secret"}
NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
SID = "66666666-6666-4666-8666-666666666666"


@pytest.mark.parametrize(
    ("cron", "human"),
    [
        ("0 5 * * *", "todo dia às 5h"),
        ("30 8 * * *", "todo dia às 8h30"),
        ("0 9 * * 1-5", "de segunda a sexta às 9h"),
        ("0 9 * * 1", "toda segunda às 9h"),
        ("0 9 * * 0", "todo domingo às 9h"),
        ("0 6 1 * *", "todo dia 1 do mês às 6h"),
        ("*/15 * * * *", "a cada 15 min"),
        ("0 */2 * * *", "a cada 2h"),
        ("10 * * * *", "toda hora, no minuto 10"),
        ("0 5 * 3 *", "0 5 * 3 *"),
    ],
)
def test_cron_reads_in_portuguese(cron: str, human: str) -> None:
    assert humanize_cron(cron) == human


@pytest.mark.parametrize(
    ("quartz", "cron"),
    [
        ("0 0 5 * * ?", "0 5 * * *"),
        ("0 30 9 ? * MON-FRI", "30 9 * * 1-5"),
        ("0 0 9 ? * 2", "0 9 * * 1"),
        ("0 0 6 1 * ? 2027", "0 6 1 * *"),
        ("bad", None),
    ],
)
def test_quartz_becomes_standard_cron(quartz: str, cron: str | None) -> None:
    assert quartz_to_cron(quartz) == cron


def _acl(**grants: str) -> list[JobAccessControlResponse]:
    rows = []
    for who, level in grants.items():
        perm = [JobPermission(permission_level=JobPermissionLevel(level))]
        user = who.replace("_at_", "@").replace("_com", ".com")
        if "@" in user:
            rows.append(JobAccessControlResponse(user_name=user, all_permissions=perm))
        else:
            rows.append(JobAccessControlResponse(group_name=who, all_permissions=perm))
    return rows


def test_acl_levels_match_user_and_groups() -> None:
    who = Principal(user_name="Ada@Example.com", groups=frozenset({"data", "users"}))
    assert levels_for(_acl(ada_at_example_com="CAN_VIEW"), who) == {"CAN_VIEW"}
    assert levels_for(_acl(data="CAN_MANAGE_RUN"), who) == {"CAN_MANAGE_RUN"}
    assert levels_for(_acl(bob_at_example_com="IS_OWNER", ops="CAN_MANAGE"), who) == set()


def _job(job_id: int, name: str, quartz: str | None = None, *, paused: bool = False) -> Any:
    schedule = (
        CronSchedule(
            quartz_cron_expression=quartz,
            timezone_id="America/Sao_Paulo",
            pause_status=PauseStatus.PAUSED if paused else PauseStatus.UNPAUSED,
        )
        if quartz
        else None
    )
    return NS(job_id=job_id, settings=NS(name=name, schedule=schedule))


class _Jobs:
    def __init__(self, jobs: list[Any], acls: dict[int, list[JobAccessControlResponse]]) -> None:
        self.jobs = jobs
        self.acls = acls
        self.started: list[int] = []

    def list(self, limit: int) -> Any:
        del limit
        return iter(self.jobs)

    def list_runs(self, job_id: int, limit: int) -> Any:
        del limit
        state = NS(result_state=NS(value="SUCCESS"), life_cycle_state=NS(value="TERMINATED"))
        return iter(
            [NS(start_time=1_760_000_000_000, state=state, run_page_url=f"https://x/{job_id}")]
        )

    def get_permissions(self, job_id: str) -> JobPermissions:
        return JobPermissions(access_control_list=self.acls.get(int(job_id), []))

    def run_now(self, job_id: int) -> Any:
        self.started.append(job_id)
        return NS(run_id=900 + job_id)


class _Denied:
    def list(self, limit: int) -> Any:
        raise PermissionError("no jobs scope")

    def run_now(self, job_id: int) -> Any:
        raise PermissionError("no jobs scope")


def _any(value: object) -> Any:
    return value


def _user(groups: tuple[str, ...] = ("data",)) -> Any:
    me = NS(user_name=OWNER, groups=[NS(display=g) for g in groups])
    return NS(jobs=_Denied(), current_user=NS(me=lambda: me))


def _fallback(app_jobs: _Jobs, groups: tuple[str, ...] = ("data",)) -> DatabricksJobs:
    return DatabricksJobs(
        user_client=lambda: _user(groups), app_client=lambda: _any(NS(jobs=app_jobs))
    )


APP_JOBS = [
    _job(1, "Mine", "0 0 5 * * ?"),
    _job(2, "Team", "0 30 9 ? * MON-FRI", paused=True),
    _job(3, "Someone else's"),
]
ACLS = {
    1: _acl(ada_at_example_com="IS_OWNER"),
    2: _acl(data="CAN_VIEW"),
    3: _acl(bob_at_example_com="IS_OWNER"),
}


def test_without_a_jobs_scope_only_jobs_the_acl_grants_are_listed() -> None:
    listing = _fallback(_Jobs(APP_JOBS, ACLS)).list_sync(NOW)

    assert listing.visibility == "acl"
    by_id = {j.id: j for j in listing.jobs}
    assert set(by_id) == {"databricks:1", "databricks:2"}
    assert by_id["databricks:1"].can_run is True
    assert by_id["databricks:2"].can_run is False  # CAN_VIEW only
    assert by_id["databricks:1"].cron_human == "todo dia às 5h"
    assert by_id["databricks:1"].next_run_at == datetime(2026, 10, 15, 8, 0, tzinfo=UTC)
    assert by_id["databricks:2"].next_run_at is None  # paused
    last = by_id["databricks:1"].last_run
    assert last is not None and last.status == "SUCCESS" and last.session_id is None
    assert last.run_url == "https://x/1"


def test_workspace_admins_see_every_job() -> None:
    listing = _fallback(_Jobs(APP_JOBS, ACLS), groups=("admins",)).list_sync(NOW)
    assert len(listing.jobs) == 3


def test_with_a_user_jobs_scope_the_user_listing_is_used() -> None:
    user_jobs = _Jobs([APP_JOBS[0]], {})
    jobs = DatabricksJobs(
        user_client=lambda: _any(NS(jobs=user_jobs)), app_client=lambda: _any(1 / 0)
    )
    listing = jobs.list_sync(NOW)
    assert listing.visibility == "user"
    assert [j.id for j in listing.jobs] == ["databricks:1"]


def test_run_now_refuses_without_run_permission() -> None:
    app_jobs = _Jobs(APP_JOBS, ACLS)
    jobs = _fallback(app_jobs)
    with pytest.raises(PermissionError):
        jobs.run_now_sync(2)
    assert jobs.run_now_sync(1) == 901
    assert app_jobs.started == [1]


# --- API -----------------------------------------------------------------------------------


def _client(store: MemorySessionStore, jobs: DatabricksJobs) -> AsyncClient:
    settings = Settings(dev_user=None, dev_token=None, serving_endpoint=None, workspace_host=None)

    def model_for(caller: Caller, model_id: str | None) -> Any:
        del caller, model_id

    app = create_app(settings=settings, model_for=model_for, store=store)
    app.state.databricks_jobs_factory = lambda token: jobs
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t", headers=HEADERS)


async def _schedule(store: MemorySessionStore, prompt: str) -> ScheduleEntry:
    return await store.create_schedule(
        ScheduleEntry(
            id="77777777-7777-4777-8777-777777777777",
            session_id=SID,
            owner_id=OWNER,
            cron_expression="0 5 * * *",
            prompt=prompt,
            status="active",
            next_run_at=datetime(2099, 1, 1, 8, 0, tzinfo=UTC),
            created_at=NOW,
            last_run_at=NOW,
        )
    )


async def test_api_lists_schedules_and_databricks_jobs_together() -> None:
    store = MemorySessionStore()
    saved = await _schedule(store, "resumo de vendas")
    async with _client(store, _fallback(_Jobs(APP_JOBS, ACLS))) as client:
        body = (await client.get("/api/jobs")).json()

    assert body["databricks_visibility"] == "acl"
    first = body["jobs"][0]
    assert first["id"] == f"schedule:{saved.id}"
    assert first["source"] == "schedule"
    assert first["agent_id"] == "main"
    assert first["cron_human"] == "todo dia às 5h"
    assert first["next_run_at"].startswith("2099-01-01T08:00")
    assert first["last_run"]["session_id"] == SID
    assert first["can_run"] is False and first["can_delete"] is True
    assert [j["id"] for j in body["jobs"][1:]] == ["databricks:1", "databricks:2"]


async def test_api_run_only_for_databricks_and_delete_only_for_schedules() -> None:
    store = MemorySessionStore()
    saved = await _schedule(store, "resumo")
    async with _client(store, _fallback(_Jobs(APP_JOBS, ACLS))) as client:
        assert (await client.post(f"/api/jobs/schedule:{saved.id}/run")).status_code == 405
        assert (await client.post("/api/jobs/databricks:2/run")).status_code == 403
        ran = await client.post("/api/jobs/databricks:1/run")
        assert ran.status_code == 200 and ran.json()["run_id"] == 901
        assert (await client.delete("/api/jobs/databricks:1")).status_code == 405
        assert (await client.delete("/api/jobs/schedule:nope")).status_code == 404
        assert (await client.delete(f"/api/jobs/schedule:{saved.id}")).status_code == 204
        body = (await client.get("/api/jobs")).json()
    assert all(j["source"] == "databricks" for j in body["jobs"])


async def test_jobs_page_is_served() -> None:
    async with _client(MemorySessionStore(), _fallback(_Jobs([], {}))) as client:
        assert (await client.get("/jobs")).status_code == 200


async def test_source_schedule_skips_databricks() -> None:
    store = MemorySessionStore()
    await _schedule(store, "resumo")
    exploding = DatabricksJobs(user_client=lambda: _any(1 / 0), app_client=lambda: _any(1 / 0))
    async with _client(store, exploding) as client:
        body = (await client.get("/api/jobs?source=schedule")).json()
    assert [j["source"] for j in body["jobs"]] == ["schedule"]
    assert body["databricks_error"] is None
