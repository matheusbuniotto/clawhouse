"""Characterization of the natural-language scheduling flow (issue #78, step 1).

Asking in chat to schedule something makes the agent call `jobs_create` with a
`cron_expression`, which creates a scheduled Databricks Lakeflow Job. These tests pin
the CURRENT behavior, including credential selection (user token first, then the
app's ambient service principal), so later refactors can be checked against it.
They document behavior; they do not endorse it.
"""

import json
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from databricks.sdk.service.jobs import CronSchedule, PauseStatus
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel

from crabriks.agent.turn import TurnContext, TurnResult, resume_turn, run_turn
from crabriks.capabilities import databricks as databricks_module
from crabriks.capabilities.databricks import (
    DatabricksCapability,
    DatabricksTools,
    build_cron_schedule,
    default_workspace_client,
    to_quartz_cron,
)
from crabriks.store.store import MemorySessionStore

SESSION = "00000000-0000-4000-8000-0000000000b7"
NATURAL_REQUEST = "eu quero agendar o relatório de vendas todo dia útil às 9h"


def _calls_tool_once(name: str, args: Mapping[str, object]) -> FunctionModel:
    async def stream(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        del info
        returned = any(
            getattr(part, "part_kind", "") == "tool-return" for m in messages for part in m.parts
        )
        if returned:
            yield "Agendado."
            return
        yield {0: DeltaToolCall(name=name, json_args=json.dumps(args), tool_call_id="call-nl")}

    return FunctionModel(stream_function=stream)


def _ctx(client: MagicMock, store: MemorySessionStore, model: FunctionModel) -> TurnContext:
    return TurnContext(
        owner_id="user-1",
        store=store,
        model=model,
        now=lambda: datetime(2026, 10, 14, 12, 0, 0, tzinfo=UTC),
        user_token="fake-user-credential",
        databricks_capability=DatabricksCapability(
            client_factory=lambda _token: client, warehouse_id="wh-1"
        ),
    )


async def _schedule_via_chat(
    client: MagicMock, args: dict[str, object]
) -> tuple[TurnResult, TurnResult]:
    store = MemorySessionStore()
    model = _calls_tool_once("jobs_create", args)
    paused = await run_turn(SESSION, NATURAL_REQUEST, ctx=_ctx(client, store, model))
    assert paused.approval_id is not None
    resumed = await resume_turn(
        SESSION, paused.approval_id, "approved", ctx=_ctx(client, store, model)
    )
    return paused, resumed


def _tool_result(result: TurnResult) -> dict[str, Any]:
    entry = next(e for e in result.transcript if e.role == "tool_result")
    return json.loads(entry.content)


# --- cron -> Quartz conversion -------------------------------------------------------


@pytest.mark.parametrize(
    ("cron", "quartz"),
    [
        ("0 9 * * *", "0 0 9 * * ?"),  # every day: day-of-week becomes "?"
        ("0 9 * * 1-5", "0 0 9 ? * 1-5"),  # weekdays: day-of-month becomes "?"
        ("30 6 1 * *", "0 30 6 1 * ?"),  # monthly
        ("*/15 * * * *", "0 */15 * * * ?"),
        ("0 0 12 * * ?", "0 0 12 * * ?"),  # 6-field Quartz is kept as is
        ("0 0 12 ? * MON 2027", "0 0 12 ? * MON 2027"),  # 7-field Quartz is kept as is
        ("  0 9 * * *  ", "0 0 9 * * ?"),  # surrounding whitespace is stripped
    ],
)
def test_to_quartz_cron_current_conversion(cron: str, quartz: str) -> None:
    assert to_quartz_cron(cron) == quartz


def test_to_quartz_cron_keeps_both_fields_when_neither_is_a_wildcard() -> None:
    # Current behavior: no "?" is inserted, which Databricks rejects. Documented, not fixed.
    assert to_quartz_cron("0 9 1 * 1") == "0 0 9 1 * 1"


def test_to_quartz_cron_passes_unexpected_field_counts_through() -> None:
    assert to_quartz_cron("bad cron") == "bad cron"


def test_build_cron_schedule_defaults_to_utc_unpaused() -> None:
    assert build_cron_schedule("0 9 * * *") == CronSchedule(
        quartz_cron_expression="0 0 9 * * ?",
        timezone_id="UTC",
        pause_status=PauseStatus.UNPAUSED,
    )


@pytest.mark.parametrize("cron", [None, ""])
def test_build_cron_schedule_without_cron_is_none(cron: str | None) -> None:
    assert build_cron_schedule(cron) is None


def test_build_cron_schedule_paused_is_case_insensitive() -> None:
    schedule = build_cron_schedule("0 9 * * *", "America/Sao_Paulo", "paused")
    assert schedule is not None
    assert schedule.pause_status == PauseStatus.PAUSED
    assert schedule.timezone_id == "America/Sao_Paulo"


# --- natural-language request -> approval -> client.jobs.create ------------------------


async def test_natural_language_schedule_pauses_for_approval_before_creating() -> None:
    client = MagicMock()
    store = MemorySessionStore()
    model = _calls_tool_once(
        "jobs_create",
        {
            "name": "vendas",
            "task_type": "python",
            "path": "/W/x.py",
            "cron_expression": "0 9 * * 1-5",
        },
    )

    paused = await run_turn(SESSION, NATURAL_REQUEST, ctx=_ctx(client, store, model))

    assert paused.status == "pending_approval"
    assert paused.approval_id is not None
    client.jobs.create.assert_not_called()


async def test_natural_language_schedule_passes_quartz_cron_schedule_to_jobs_create() -> None:
    client = MagicMock()
    client.jobs.create.return_value = MagicMock(job_id=7801)

    _, resumed = await _schedule_via_chat(
        client,
        {
            "name": "relatorio_vendas",
            "task_type": "python",
            "path": "/Workspace/Shared/vendas.py",
            "cron_expression": "0 9 * * 1-5",
            "timezone_id": "America/Sao_Paulo",
        },
    )

    assert resumed.status == "ok"
    assert _tool_result(resumed) == {"job_id": 7801, "name": "relatorio_vendas", "scheduled": True}
    client.jobs.create.assert_called_once()
    kwargs = client.jobs.create.call_args.kwargs
    assert kwargs["name"] == "relatorio_vendas"
    assert kwargs["schedule"] == CronSchedule(
        quartz_cron_expression="0 0 9 ? * 1-5",
        timezone_id="America/Sao_Paulo",
        pause_status=PauseStatus.UNPAUSED,
    )


async def test_natural_language_schedule_can_be_created_paused() -> None:
    client = MagicMock()
    client.jobs.create.return_value = MagicMock(job_id=7802)

    await _schedule_via_chat(
        client,
        {
            "name": "pausado",
            "task_type": "python",
            "path": "/W/p.py",
            "cron_expression": "0 9 * * *",
            "pause_status": "PAUSED",
        },
    )

    assert client.jobs.create.call_args.kwargs["schedule"].pause_status == PauseStatus.PAUSED


async def test_jobs_create_without_cron_sends_no_schedule() -> None:
    client = MagicMock()
    client.jobs.create.return_value = MagicMock(job_id=7803)

    _, resumed = await _schedule_via_chat(
        client, {"name": "avulso", "task_type": "python", "path": "/W/a.py"}
    )

    assert "schedule" not in client.jobs.create.call_args.kwargs
    assert "scheduled" not in _tool_result(resumed)


async def test_denied_schedule_never_creates_the_job() -> None:
    client = MagicMock()
    store = MemorySessionStore()
    model = _calls_tool_once(
        "jobs_create",
        {
            "name": "negado",
            "task_type": "python",
            "path": "/W/n.py",
            "cron_expression": "0 9 * * *",
        },
    )
    paused = await run_turn(SESSION, NATURAL_REQUEST, ctx=_ctx(client, store, model))
    assert paused.approval_id is not None

    resumed = await resume_turn(
        SESSION, paused.approval_id, "denied", ctx=_ctx(client, store, model)
    )

    assert resumed.status == "ok"
    client.jobs.create.assert_not_called()


# --- approval gate ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "tool", ["jobs_create", "jobs_edit", "jobs_delete", "jobs_run_now", "jobs_cancel_run"]
)
def test_mutating_jobs_tools_are_in_the_approval_set(tool: str) -> None:
    assert tool in databricks_module._APPROVAL_REQUIRED_TOOLS  # pyright: ignore[reportPrivateUsage]


@pytest.mark.parametrize("tool", ["jobs_list", "jobs_get_run", "jobs_get_run_output"])
def test_read_only_jobs_tools_are_not_in_the_approval_set(tool: str) -> None:
    assert tool not in databricks_module._APPROVAL_REQUIRED_TOOLS  # pyright: ignore[reportPrivateUsage]


# --- current credential behavior: user token first, then ambient (app SP) ---------------


def test_default_client_uses_user_token_as_pat_when_given() -> None:
    with patch.object(databricks_module, "WorkspaceClient") as workspace_client:
        default_workspace_client("fake-user-credential")

    workspace_client.assert_called_once_with(token="fake-user-credential", auth_type="pat")


def test_default_client_without_token_uses_ambient_auth() -> None:
    with patch.object(databricks_module, "WorkspaceClient") as workspace_client:
        default_workspace_client("")

    workspace_client.assert_called_once_with()


def test_default_client_falls_back_to_ambient_when_user_token_client_fails() -> None:
    ambient = MagicMock(name="ambient")
    with patch.object(
        databricks_module, "WorkspaceClient", side_effect=[ValueError("bad credential"), ambient]
    ) as workspace_client:
        client = default_workspace_client("fake-user-credential")

    assert client is ambient
    assert workspace_client.call_args_list[1].args == ()
    assert workspace_client.call_args_list[1].kwargs == {}


async def test_jobs_create_silently_retries_on_ambient_client_when_user_call_fails() -> None:
    user_client = MagicMock(name="user")
    user_client.jobs.create.side_effect = PermissionError("missing jobs scope")
    ambient_client = MagicMock(name="ambient")
    ambient_client.jobs.create.return_value = MagicMock(job_id=7804)
    tools = DatabricksTools(user_client, warehouse_id="wh-1")
    tools._fallback_client = lambda: ambient_client  # type: ignore[method-assign]

    result = await tools.jobs_create(
        "fallback", task_type="python", path="/W/f.py", cron_expression="0 9 * * *"
    )

    # Current behavior: the job is created by the ambient identity and nothing in the
    # result says which identity was used (issue #78 will make this explicit).
    assert result == {"job_id": 7804, "name": "fallback", "scheduled": True}
    user_client.jobs.create.assert_called_once()
    ambient_client.jobs.create.assert_called_once()


async def test_jobs_create_reports_error_when_both_identities_fail() -> None:
    user_client = MagicMock(name="user")
    user_client.jobs.create.side_effect = PermissionError("user denied")
    ambient_client = MagicMock(name="ambient")
    ambient_client.jobs.create.side_effect = PermissionError("sp denied")
    tools = DatabricksTools(user_client, warehouse_id="wh-1")
    tools._fallback_client = lambda: ambient_client  # type: ignore[method-assign]

    result = await tools.jobs_create("x", task_type="python", path="/W/x.py")

    assert result == {"error": "Failed to create job x: sp denied"}


def test_capability_toolset_falls_back_to_ambient_when_user_client_factory_fails() -> None:
    def failing_factory(_token: str) -> MagicMock:
        raise RuntimeError("user client unavailable")

    cap = DatabricksCapability(
        client_factory=failing_factory, warehouse_id="wh-1", user_token="fake-user-credential"
    )
    with patch.object(databricks_module, "WorkspaceClient") as workspace_client:
        toolset = cap.get_toolset()

    assert toolset is not None
    workspace_client.assert_called_once_with()
