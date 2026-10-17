"""Estate reads use the forwarded client and fail closed."""

from unittest.mock import MagicMock

import pytest
from databricks.sdk.errors import PermissionDenied
from databricks.sdk.service.catalog import (
    EffectivePermissionsList,
    EffectivePrivilege,
    EffectivePrivilegeAssignment,
    Privilege,
)
from databricks.sdk.service.jobs import Run, RunLifeCycleState, RunResultState, RunState, RunTask

from clawhouse.capabilities.databricks import DatabricksTools

FQN = "main.sales.orders"


def _tools(client: MagicMock, token: str = "user-token") -> DatabricksTools:
    return DatabricksTools(client, "wh-1", user_token=token)


def _statement(rows: list[list[str]], columns: list[str]) -> MagicMock:
    resp = MagicMock()
    resp.manifest.schema.columns = [MagicMock(name=name) for name in columns]
    for col, name in zip(resp.manifest.schema.columns, columns, strict=True):
        col.name = name
    resp.result.data_array = rows
    return resp


@pytest.mark.asyncio
async def test_uc_list_grants_returns_effective_assignments() -> None:
    client = MagicMock()
    client.grants.get_effective.return_value = EffectivePermissionsList(
        privilege_assignments=[
            EffectivePrivilegeAssignment(
                principal="ada@example.com",
                privileges=[
                    EffectivePrivilege(privilege=Privilege.SELECT, inherited_from_name=None)
                ],
            ),
            EffectivePrivilegeAssignment(
                principal="analysts",
                privileges=[
                    EffectivePrivilege(privilege=Privilege.SELECT, inherited_from_name="analysts")
                ],
            ),
        ]
    )

    result = await _tools(client).uc_list_grants(FQN)

    client.grants.get_effective.assert_called_once_with(securable_type="table", full_name=FQN)
    assert result["full_name"] == FQN
    assert result["grants"] == [
        {"principal": "ada@example.com", "privilege": "SELECT", "inherited": False},
        {"principal": "analysts", "privilege": "SELECT", "inherited": True},
    ]


@pytest.mark.asyncio
async def test_uc_list_grants_permission_error_is_not_an_empty_list() -> None:
    client = MagicMock()
    client.grants.get_effective.side_effect = PermissionDenied("permission denied")

    result = await _tools(client).uc_list_grants(FQN)

    assert result == {"error": "not visible to you"}
    assert "grants" not in result


@pytest.mark.asyncio
async def test_uc_list_grants_empty_token_does_not_call_ambient_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    constructed: list[object] = []
    monkeypatch.setattr(
        "clawhouse.capabilities.databricks.WorkspaceClient",
        lambda *args, **kwargs: constructed.append((args, kwargs)) or MagicMock(),
    )
    client = MagicMock()

    result = await _tools(client, token="").uc_list_grants(FQN)

    assert result == {"error": "not visible to you"}
    assert constructed == []
    client.grants.get_effective.assert_not_called()


@pytest.mark.asyncio
async def test_uc_list_grants_rejects_non_three_part_names() -> None:
    client = MagicMock()
    tools = _tools(client)

    two = await tools.uc_list_grants("sales.orders")
    four = await tools.uc_list_grants("main.sales.orders.extra")

    assert two == {"error": "full_name must be catalog.schema.table"}
    assert four == {"error": "full_name must be catalog.schema.table"}
    client.grants.get_effective.assert_not_called()


@pytest.mark.asyncio
async def test_uc_table_lineage_splits_upstream_and_downstream() -> None:
    client = MagicMock()
    client.statement_execution.execute_statement.return_value = _statement(
        [
            ["bronze.raw.orders", FQN, "2026-01-02T00:00:00Z"],
            [FQN, "gold.sales.region", "2026-01-03T00:00:00Z"],
        ],
        ["source_table_full_name", "target_table_full_name", "event_time"],
    )

    result = await _tools(client).uc_table_lineage(FQN)

    assert result["upstream"] == [
        {"table": "bronze.raw.orders", "last_seen": "2026-01-02T00:00:00Z"}
    ]
    assert result["downstream"] == [
        {"table": "gold.sales.region", "last_seen": "2026-01-03T00:00:00Z"}
    ]


@pytest.mark.asyncio
async def test_uc_column_lineage_returns_column_pairs() -> None:
    client = MagicMock()
    client.statement_execution.execute_statement.return_value = _statement(
        [
            ["bronze.raw.orders", "amt", FQN, "amount", "2026-02-01T00:00:00Z"],
            [FQN, "amount", "gold.sales.region", "revenue", "2026-02-02T00:00:00Z"],
        ],
        [
            "source_table_full_name",
            "source_column_name",
            "target_table_full_name",
            "target_column_name",
            "event_time",
        ],
    )

    result = await _tools(client).uc_column_lineage(FQN, "amount")

    assert result["upstream"] == [
        {"table": "bronze.raw.orders", "column": "amt", "last_seen": "2026-02-01T00:00:00Z"}
    ]
    assert result["downstream"] == [
        {"table": "gold.sales.region", "column": "revenue", "last_seen": "2026-02-02T00:00:00Z"}
    ]


@pytest.mark.asyncio
async def test_empty_lineage_returns_note() -> None:
    client = MagicMock()
    client.statement_execution.execute_statement.return_value = _statement(
        [],
        ["source_table_full_name", "target_table_full_name", "event_time"],
    )

    result = await _tools(client).uc_table_lineage(FQN)

    assert result == {"table": FQN, "upstream": [], "downstream": [], "note": "no lineage found"}


@pytest.mark.asyncio
async def test_lineage_caps_each_direction_at_50() -> None:
    rows = [[f"up.s.t{i:02d}", FQN, f"2026-03-{(i % 28) + 1:02d}T00:00:00Z"] for i in range(60)] + [
        [FQN, f"down.s.t{i:02d}", f"2026-04-{(i % 28) + 1:02d}T00:00:00Z"] for i in range(60)
    ]
    client = MagicMock()
    client.statement_execution.execute_statement.return_value = _statement(
        rows,
        ["source_table_full_name", "target_table_full_name", "event_time"],
    )

    result = await _tools(client).uc_table_lineage(FQN)

    upstream = result["upstream"]
    downstream = result["downstream"]
    assert isinstance(upstream, list)
    assert isinstance(downstream, list)
    assert len(upstream) == 50
    assert len(downstream) == 50
    assert upstream == sorted(upstream, key=lambda row: row["last_seen"], reverse=True)
    assert downstream == sorted(downstream, key=lambda row: row["last_seen"], reverse=True)


@pytest.mark.asyncio
async def test_lineage_empty_token_does_not_query() -> None:
    client = MagicMock()
    tools = _tools(client, token="")

    table = await tools.uc_table_lineage(FQN)
    column = await tools.uc_column_lineage(FQN, "amount")

    assert table == {"error": "not visible to you"}
    assert column == {"error": "not visible to you"}
    client.statement_execution.execute_statement.assert_not_called()


@pytest.mark.asyncio
async def test_job_run_failure_returns_run_fields() -> None:
    client = MagicMock()
    client.jobs.get_run.return_value = Run(
        run_id=77,
        run_page_url="https://example.cloud.databricks.com/#job/5/run/77",
        start_time=1_000,
        end_time=4_500,
        state=RunState(
            life_cycle_state=RunLifeCycleState.TERMINATED,
            result_state=RunResultState.FAILED,
            state_message="cluster failed",
        ),
        tasks=[],
    )

    result = await _tools(client).job_run_failure(77)

    assert result["run_id"] == 77
    assert result["life_cycle_state"] == "TERMINATED"
    assert result["result_state"] == "FAILED"
    assert result["state_message"] == "cluster failed"
    assert result["duration_ms"] == 3_500
    assert result["run_page_url"] == "https://example.cloud.databricks.com/#job/5/run/77"


@pytest.mark.asyncio
async def test_job_run_failure_lists_failed_tasks() -> None:
    client = MagicMock()
    client.jobs.get_run.return_value = Run(
        run_id=80,
        run_page_url="https://example/run/80",
        start_time=1,
        end_time=2,
        state=RunState(
            life_cycle_state=RunLifeCycleState.TERMINATED,
            result_state=RunResultState.FAILED,
            state_message="failed",
        ),
        tasks=[
            RunTask(
                task_key="load",
                run_id=81,
                state=RunState(
                    life_cycle_state=RunLifeCycleState.TERMINATED,
                    result_state=RunResultState.FAILED,
                    state_message="null key",
                ),
            ),
            RunTask(
                task_key="ok",
                run_id=82,
                state=RunState(
                    life_cycle_state=RunLifeCycleState.TERMINATED,
                    result_state=RunResultState.SUCCESS,
                    state_message="",
                ),
            ),
        ],
    )

    result = await _tools(client).job_run_failure(80)

    assert result["failed_tasks"] == [
        {"task_key": "load", "result_state": "FAILED", "state_message": "null key"}
    ]


@pytest.mark.asyncio
async def test_running_run_is_not_labeled_failed() -> None:
    client = MagicMock()
    client.jobs.get_run.return_value = Run(
        run_id=90,
        run_page_url="https://example/run/90",
        state=RunState(life_cycle_state=RunLifeCycleState.RUNNING, result_state=None),
        tasks=[],
    )

    result = await _tools(client).job_run_failure(90)

    assert result["life_cycle_state"] == "RUNNING"
    assert result["result_state"] != "FAILED"


@pytest.mark.asyncio
async def test_job_run_failure_empty_token_does_not_get_run() -> None:
    client = MagicMock()

    result = await _tools(client, token="").job_run_failure(77)

    assert result == {"error": "not visible to you"}
    client.jobs.get_run.assert_not_called()


@pytest.mark.asyncio
async def test_table_lineage_sql_filters_source_or_target() -> None:
    client = MagicMock()
    client.statement_execution.execute_statement.return_value = _statement(
        [],
        ["source_table_full_name", "target_table_full_name", "event_time"],
    )

    await _tools(client).uc_table_lineage(FQN)

    statement = client.statement_execution.execute_statement.call_args.kwargs["statement"]
    params = client.statement_execution.execute_statement.call_args.kwargs["parameters"]
    assert "system.access.table_lineage" in statement
    assert "source_table_full_name = :fqn" in statement
    assert "target_table_full_name = :fqn" in statement
    assert params[0].value == FQN
