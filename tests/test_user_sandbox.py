"""Tests for user-sandbox: native Databricks python_exec and persistent Workspace files."""

import io
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic_ai.models.function import FunctionModel

from clawhouse.agent.pauses import DEFAULT_APPROVAL_REQUIRED_TOOLS
from clawhouse.api.app import create_app
from clawhouse.capabilities.databricks.sandbox import (
    python_exec,
    sandbox_list_files,
    sandbox_read_file,
    sandbox_write_file,
    user_sandbox_root,
    user_sandbox_slug,
)
from clawhouse.capabilities.databricks.tools import DatabricksTools
from clawhouse.settings import Settings
from clawhouse.store.store import MemorySessionStore

OWNER = "analyst@example.com"
OTHER = "other@example.com"
HEADERS = {"x-forwarded-email": OWNER, "x-forwarded-access-token": "tok_" + "user"}
OTHER_HEADERS = {"x-forwarded-email": OTHER, "x-forwarded-access-token": "tok_" + "other"}
SESSION = "00000000-0000-4000-8000-0000000000b1"


def _make_tools(client: MagicMock, token: str = "tok_user", owner: str = OWNER) -> DatabricksTools:
    return DatabricksTools(client, warehouse_id=None, user_token=token, owner_id=owner)


def _app(
    store: MemorySessionStore | None = None,
    client: MagicMock | None = None,
) -> object:
    mock_client = client if client is not None else MagicMock()
    mock_client.workspace.list.return_value = []
    settings = Settings(
        dev_user=None,
        dev_token=None,
        serving_endpoint=None,
        workspace_host="https://adb-123.databricks.com",
    )
    s = store or MemorySessionStore()

    def _model_factory(caller: object, model_id: str | None) -> FunctionModel:
        return FunctionModel(stream_function=lambda messages, info: ["ok"])  # type: ignore[return-value]

    return create_app(
        settings=settings,
        model_for=_model_factory,
        store=s,
        workspace_client_factory=lambda token: mock_client,
    )


def _client(app: object) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")  # type: ignore[arg-type]


# --- C1: Approval required tools ---
def test_python_exec_in_default_approval_tools() -> None:
    assert "python_exec" in DEFAULT_APPROVAL_REQUIRED_TOOLS
    assert "sandbox_write_file" in DEFAULT_APPROVAL_REQUIRED_TOOLS


# --- C2: Fails closed without token ---
@pytest.mark.asyncio
async def test_python_exec_fails_closed_without_token() -> None:
    client = MagicMock()
    tools = _make_tools(client, token="")
    res = await python_exec(tools, "print(1)")
    assert res == {"error": "user token required"}
    client.api_client.do.assert_not_called()


# --- C3: Calls MCP function and returns output ---
@pytest.mark.asyncio
async def test_python_exec_calls_mcp_function_and_returns_output() -> None:
    client = MagicMock()
    client.api_client.do.return_value = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "structuredContent": {
                "columns": ["output"],
                "rows": [["42\n"]],
                "is_truncated": False,
            }
        },
    }
    tools = _make_tools(client)
    res = await python_exec(tools, "print(40 + 2)")
    assert res == {"output": "42\n", "is_truncated": False}
    client.api_client.do.assert_called_once()
    call = client.api_client.do.call_args
    assert call.args[0] == "POST"
    assert call.args[1] == "/api/2.0/mcp/functions/system/ai/python_exec"
    assert call.kwargs["body"]["params"]["name"] == "system__ai__python_exec"


# --- C4: python_exec with script_path ---
@pytest.mark.asyncio
async def test_python_exec_with_script_path() -> None:
    client = MagicMock()
    client.workspace.download.return_value = io.BytesIO(b"print('hello from script')")
    client.api_client.do.return_value = {
        "structuredContent": {"rows": [["hello from script\n"]], "is_truncated": False}
    }
    tools = _make_tools(client)
    res = await python_exec(tools, script_path="scripts/test.py")
    assert res == {"output": "hello from script\n", "is_truncated": False}
    body = client.api_client.do.call_args.kwargs["body"]
    assert body["params"]["arguments"]["code"] == "print('hello from script')"


# --- C5: Token scrubbing ---
@pytest.mark.asyncio
async def test_python_exec_scrubs_token() -> None:
    token = "secret_tok_12345"
    client = MagicMock()
    client.api_client.do.return_value = {
        "structuredContent": {"rows": [[f"output with {token} leaked\n"]], "is_truncated": False}
    }
    tools = _make_tools(client, token=token)
    res = await python_exec(tools, "print(token)")
    assert "[REDACTED]" in str(res["output"])
    assert token not in str(res["output"])


# --- C6: MCP error handling ---
@pytest.mark.asyncio
async def test_python_exec_handles_mcp_error() -> None:
    client = MagicMock()
    client.api_client.do.side_effect = RuntimeError("500 internal error")
    tools = _make_tools(client)
    res = await python_exec(tools, "print(1)")
    assert "error" in res
    assert "python_exec failed: 500 internal error" in str(res["error"])


# --- C7: Output truncation ---
@pytest.mark.asyncio
async def test_python_exec_truncates_large_output() -> None:
    client = MagicMock()
    huge = "A" * 25_000
    client.api_client.do.return_value = {
        "structuredContent": {"rows": [[huge]], "is_truncated": False}
    }
    tools = _make_tools(client)
    res = await python_exec(tools, "print('lots')")
    assert res["is_truncated"] is True
    assert len(str(res["output"])) == 20_000


# --- C8 & C9: sandbox_write_file approval & upload ---
@pytest.mark.asyncio
async def test_sandbox_write_file_pauses_for_approval() -> None:
    assert "sandbox_write_file" in DEFAULT_APPROVAL_REQUIRED_TOOLS


@pytest.mark.asyncio
async def test_sandbox_write_file_uploads_to_slug_path() -> None:
    client = MagicMock()
    tools = _make_tools(client)
    res = await sandbox_write_file(tools, "notes.txt", "sample content")
    assert res == {"path": "notes.txt", "bytes_written": len(b"sample content")}
    slug = user_sandbox_slug(OWNER)
    expected_path = f"/Workspace/Shared/clawhouse/sandboxes/{slug}/notes.txt"
    client.workspace.upload.assert_called_once()
    assert client.workspace.upload.call_args[0][0] == expected_path


# --- C10: Read and list do not pause ---
def test_sandbox_read_and_list_do_not_pause() -> None:
    assert "sandbox_read_file" not in DEFAULT_APPROVAL_REQUIRED_TOOLS
    assert "sandbox_list_files" not in DEFAULT_APPROVAL_REQUIRED_TOOLS


# --- C11: sandbox_read_file ---
@pytest.mark.asyncio
async def test_sandbox_read_file_returns_content() -> None:
    client = MagicMock()
    client.workspace.download.return_value = io.BytesIO(b"stored data")
    tools = _make_tools(client)
    res = await sandbox_read_file(tools, "notes.txt")
    assert res == {"path": "notes.txt", "content": "stored data"}


# --- C12: Read missing file returns error ---
@pytest.mark.asyncio
async def test_sandbox_read_file_missing_returns_error() -> None:
    client = MagicMock()
    client.workspace.download.side_effect = Exception("Not found")
    tools = _make_tools(client)
    res = await sandbox_read_file(tools, "missing.txt")
    assert res == {"error": "file not found", "path": "missing.txt"}


# --- C13: sandbox_list_files ---
@pytest.mark.asyncio
async def test_sandbox_list_files_returns_sorted_paths() -> None:
    client = MagicMock()
    slug = user_sandbox_slug(OWNER)
    root = f"/Workspace/Shared/clawhouse/sandboxes/{slug}"
    item1 = MagicMock()
    item1.path = f"{root}/b.txt"
    item1.is_dir = False
    item2 = MagicMock()
    item2.path = f"{root}/a.txt"
    item2.is_dir = False
    client.workspace.list.return_value = [item1, item2]

    tools = _make_tools(client)
    res = await sandbox_list_files(tools)
    assert res == {"files": ["a.txt", "b.txt"]}


@pytest.mark.asyncio
async def test_sandbox_list_files_returns_nested_relative_paths() -> None:
    client = MagicMock()
    slug = user_sandbox_slug(OWNER)
    root = f"/Workspace/Shared/clawhouse/sandboxes/{slug}"
    item1 = MagicMock()
    item1.path = f"{root}/sub/nested.txt"
    item1.is_dir = False
    dir_item = MagicMock()
    dir_item.path = f"{root}/sub"
    dir_item.is_dir = True
    root_item = MagicMock()
    root_item.path = f"{root}/top.txt"
    root_item.is_dir = False

    def mock_list(path: str) -> list[MagicMock]:
        if path == root:
            return [dir_item, root_item]
        if path == f"{root}/sub":
            return [item1]
        return []

    client.workspace.list.side_effect = mock_list
    tools = _make_tools(client)
    res = await sandbox_list_files(tools)
    assert res == {"files": ["sub/nested.txt", "top.txt"]}


# --- C14: Path traversal denial ---
@pytest.mark.asyncio
async def test_sandbox_file_tools_deny_path_traversal() -> None:
    client = MagicMock()
    tools = _make_tools(client)
    for bad in ["/etc/passwd", "../secret", "a/../../etc"]:
        w_res = await sandbox_write_file(tools, bad, "foo")
        assert w_res == {"error": "path traversal denied"}
        r_res = await sandbox_read_file(tools, bad)
        assert r_res == {"error": "path traversal denied"}


# --- C15: User isolation ---
def test_sandbox_files_user_isolation() -> None:
    root_a = user_sandbox_root(OWNER)
    root_b = user_sandbox_root(OTHER)
    assert root_a != root_b
    assert user_sandbox_slug(OWNER) != user_sandbox_slug(OTHER)


# --- C16 & C17: API status and auth ---
@pytest.mark.asyncio
async def test_api_get_sandbox_status() -> None:
    app = _app()
    async with _client(app) as client:
        resp = await client.get("/api/sandbox", headers=HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data["owner_id"] == OWNER
    assert data["backend"] == "databricks_python_exec"
    assert data["status"] == "ready"
    assert isinstance(data["file_count"], int)


@pytest.mark.asyncio
async def test_api_sandbox_requires_auth() -> None:
    app = _app()
    async with _client(app) as client:
        get_res = await client.get("/api/sandbox")
        post_res = await client.post("/api/sandbox/reset")
    assert get_res.status_code == 401
    assert post_res.status_code == 401


# --- C18: Reset endpoint ---
@pytest.mark.asyncio
async def test_api_post_sandbox_reset() -> None:
    app = _app()
    async with _client(app) as client:
        resp = await client.post("/api/sandbox/reset", headers=HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data["owner_id"] == OWNER
    assert data["file_count"] == 0


# --- C19: Reset failure 502 ---
@pytest.mark.asyncio
async def test_api_post_sandbox_reset_failure_502(monkeypatch: pytest.MonkeyPatch) -> None:
    async def mock_reset(tools: DatabricksTools) -> dict[str, object]:
        return {"error": "Databricks cluster failure"}

    monkeypatch.setattr("clawhouse.api.routes.status.sandbox_reset", mock_reset)
    app = _app()
    async with _client(app) as client:
        resp = await client.post("/api/sandbox/reset", headers=HEADERS)
    assert resp.status_code == 502


# --- C20: Mount check ---
def test_create_app_mounts_sandbox_routes() -> None:
    app = _app()
    routes = [route.path for route in app.routes]  # type: ignore[attr-defined]
    assert "/api/sandbox" in routes
    assert "/api/sandbox/reset" in routes


# --- C21: Status.js contains User Sandbox and button ---
def test_status_js_contains_user_sandbox_and_reset_button() -> None:
    status_js = Path("src/clawhouse/static/status.js").read_text(encoding="utf-8")
    assert "User Sandbox" in status_js
    assert "btn-reset-sandbox" in status_js
    assert "stat-sandbox-files" in status_js


# --- C22: Status.js wires reset click ---
def test_status_js_wires_reset_sandbox_click() -> None:
    status_js = Path("src/clawhouse/static/status.js").read_text(encoding="utf-8")
    assert "/api/sandbox/reset" in status_js


# --- C23: DatabricksTools includes sandbox tools ---
def test_databricks_tools_includes_sandbox_tools() -> None:
    client = MagicMock()
    tools = _make_tools(client)
    names = [fn.__name__ for fn in tools.all_tools()]
    assert "python_exec" in names
    assert "sandbox_write_file" in names
    assert "sandbox_read_file" in names
    assert "sandbox_list_files" in names


# --- C24: Headless turn without token denies ---
@pytest.mark.asyncio
async def test_headless_turn_python_exec_empty_token() -> None:
    client = MagicMock()
    tools = _make_tools(client, token="")
    res = await tools.python_exec("print(1)")
    assert res == {"error": "user token required"}


@pytest.mark.asyncio
async def test_api_sandbox_unavailable_when_client_fails() -> None:
    settings = Settings(
        dev_user=None,
        dev_token=None,
        serving_endpoint=None,
        workspace_host="https://adb-123.databricks.com",
    )

    def _failing_factory(_token: str) -> MagicMock:
        raise ValueError("auth failure")

    app = create_app(
        settings=settings,
        model_for=lambda caller, model_id: FunctionModel(stream_function=lambda m, i: ["ok"]),  # type: ignore[return-value]
        store=MemorySessionStore(),
        workspace_client_factory=_failing_factory,  # type: ignore[arg-type]
    )
    async with _client(app) as client:
        status_resp = await client.get("/api/status", headers=HEADERS)
        sandbox_resp = await client.get("/api/sandbox", headers=HEADERS)
        reset_resp = await client.post("/api/sandbox/reset", headers=HEADERS)

    assert status_resp.status_code == 200
    assert status_resp.json()["sandbox"]["status"] == "unavailable"
    assert sandbox_resp.status_code == 200
    assert sandbox_resp.json()["status"] == "unavailable"
    assert reset_resp.status_code == 502
