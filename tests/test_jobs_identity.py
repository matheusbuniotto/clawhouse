"""Unit tests for Lakeflow Jobs execution identity resolution and mutating tools metadata."""

from unittest.mock import MagicMock, patch

import pytest

from clawhouse.capabilities.databricks import (
    DatabricksTools,
    JobsIdentity,
    MissingJobsIdentityError,
    jobs_identity,
)
from clawhouse.settings import Settings, settings_from_env


def test_settings_jobs_sp_credentials() -> None:
    env = {
        "CLAWHOUSE_JOBS_SP_CLIENT_ID": "test-sp-client-id",
        "CLAWHOUSE_JOBS_SP_CLIENT_SECRET": "test-sp-client-secret",
    }
    settings = settings_from_env(env)
    assert settings.jobs_sp_client_id == "test-sp-client-id"
    assert settings.jobs_sp_client_secret == "test-sp-client-secret"

    empty_settings = settings_from_env({})
    assert empty_settings.jobs_sp_client_id is None
    assert empty_settings.jobs_sp_client_secret is None


def test_jobs_identity_service_principal() -> None:
    settings = Settings(
        dev_user=None,
        dev_token=None,
        serving_endpoint=None,
        workspace_host="https://adb-1234.net",
        jobs_sp_client_id="sp-client-123",
        jobs_sp_client_secret="sp-secret-456",
    )
    with patch("clawhouse.capabilities.databricks.WorkspaceClient") as mock_wc:
        ident = jobs_identity(settings=settings)
        assert ident.kind == "service_principal"
        assert ident.label == "sp-client-123"
        mock_wc.assert_called_once_with(
            client_id="sp-client-123",
            client_secret="sp-secret-456",
            auth_type="oauth-m2m",
            host="https://adb-1234.net",
        )


def test_jobs_identity_user_obo() -> None:
    with patch("clawhouse.capabilities.databricks.WorkspaceClient") as mock_wc:
        ident = jobs_identity(user_token="pat-token-xyz")
        assert ident.kind == "user_obo"
        assert ident.label == "user"
        mock_wc.assert_called_once_with(token="pat-token-xyz", auth_type="pat")


def test_jobs_identity_missing_raises() -> None:
    with patch("clawhouse.capabilities.databricks.WorkspaceClient") as mock_wc:
        with pytest.raises(MissingJobsIdentityError):
            jobs_identity()
        with pytest.raises(MissingJobsIdentityError):
            jobs_identity(user_token="")
        mock_wc.assert_not_called()


@pytest.mark.asyncio
async def test_mutating_jobs_tools_return_identity() -> None:
    client = MagicMock()
    client.jobs.create.return_value = MagicMock(job_id=101)
    client.jobs.update.return_value = MagicMock()
    client.jobs.run_now.return_value = MagicMock(run_id=202)
    client.jobs.cancel_run.return_value = MagicMock()

    identity = JobsIdentity(kind="service_principal", client=client, label="sp-client-123")
    tools = DatabricksTools(client, warehouse_id="wh-1", jobs_identity=identity)

    # 1. jobs_create
    res_create = await tools.jobs_create("job_1", task_type="python", path="/W/j1.py")
    assert res_create["job_id"] == 101
    assert res_create["identity"] == {"kind": "service_principal", "label": "sp-client-123"}
    client.jobs.create.assert_called_once()

    # 2. jobs_edit
    res_edit = await tools.jobs_edit(101, name="renamed_job")
    assert res_edit["updated"] is True
    assert res_edit["identity"] == {"kind": "service_principal", "label": "sp-client-123"}
    client.jobs.update.assert_called_once()

    # 3. jobs_run_now
    res_run = await tools.jobs_run_now(101)
    assert res_run["run_id"] == 202
    assert res_run["identity"] == {"kind": "service_principal", "label": "sp-client-123"}
    client.jobs.run_now.assert_called_once()

    # 4. jobs_cancel_run
    res_cancel = await tools.jobs_cancel_run(202)
    assert res_cancel["cancel_requested"] is True
    assert res_cancel["identity"] == {"kind": "service_principal", "label": "sp-client-123"}
    client.jobs.cancel_run.assert_called_once()


@pytest.mark.asyncio
async def test_jobs_create_fails_without_identity() -> None:
    client = MagicMock()
    tools = DatabricksTools(client, warehouse_id="wh-1")

    res = await tools.jobs_create("job_fail", task_type="python", path="/W/f.py")
    assert "error" in res
    assert "no jobs execution identity configured" in str(res["error"]).lower()
    client.jobs.create.assert_not_called()
