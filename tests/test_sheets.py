"""Tests for Google Sheets capability via Databricks AI Gateway system.ai.google_drive."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
import requests
from pydantic import ValidationError
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel

from crabriks.agent.turn import TurnContext, resume_turn, run_turn
from crabriks.capabilities import sheets
from crabriks.capabilities.sheets import (
    AUTHORIZE,
    NO_TOKEN,
    REJECTED,
    TIMED_OUT,
    UNCONFIRMED,
    NewSheet,
    SheetUpdate,
    write_new_sheet,
    write_sheet_update,
)
from crabriks.store import MemorySessionStore

SHEET_ID = "1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"
TOKEN = "forwarded-user-token"
SESSION_ID = "11111111-2222-3333-4444-555555555555"
OWNER = "analyst@example.com"
NOW = datetime(2026, 10, 13, 15, 0, tzinfo=UTC)


class _MockResponse:
    def __init__(
        self,
        status_code: int,
        data: dict[str, Any] | None = None,
        content: bytes = b"",
    ) -> None:
        self.status_code = status_code
        self.headers = {"content-type": "application/json"}
        if data is not None:
            self.content = json.dumps(data).encode("utf-8")
        else:
            self.content = content

    def json(self) -> dict[str, Any]:
        return json.loads(self.content.decode("utf-8"))

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")


def _init_resp() -> _MockResponse:
    return _MockResponse(
        200, {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2025-06-18"}}
    )


def _call_resp(body: dict[str, Any]) -> _MockResponse:
    return _MockResponse(
        200,
        {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {
                "content": [{"type": "text", "text": json.dumps(body)}],
                "isError": False,
            },
        },
    )


def test_update_range_is_derived_from_the_data_shape() -> None:
    update = SheetUpdate(
        spreadsheet_id=SHEET_ID,
        tab="Vendas",
        first_column="Z",
        first_row=3,
        rows=[[1, 2, 3], [4, 5, 6]],
    )
    assert update.a1_range == "'Vendas'!Z3:AB4"


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [[]],
        [[1, 2], [3]],
        [["x" * 1_001]],
        [[1] * 27],
        [[1]] * 501,
    ],
)
def test_oversized_or_ragged_tables_are_rejected_before_approval(rows: list[list[Any]]) -> None:
    with pytest.raises(ValidationError):
        NewSheet(title="Test", rows=rows)


@pytest.mark.parametrize("tab", ["a'b", "a/b", "[x]", "*star", "?quest", ""])
def test_tab_names_cannot_break_out_of_the_quoted_range(tab: str) -> None:
    with pytest.raises(ValidationError):
        SheetUpdate(spreadsheet_id=SHEET_ID, tab=tab, rows=[[1]])


def test_extra_fields_such_as_a_model_chosen_range_are_rejected() -> None:
    with pytest.raises(ValidationError):
        SheetUpdate.model_validate(
            {"spreadsheet_id": SHEET_ID, "rows": [[1]], "tab": "Dados", "range": "A1:ZZ9999"}
        )


def test_normalize_host_ensures_https() -> None:
    assert (
        sheets.normalize_host("dbc-562d9321-2592.cloud.databricks.com")
        == "https://dbc-562d9321-2592.cloud.databricks.com"
    )
    assert (
        sheets.normalize_host("https://dbc-562d9321-2592.cloud.databricks.com/")
        == "https://dbc-562d9321-2592.cloud.databricks.com"
    )


def test_databricks_host_reads_env_with_or_without_scheme(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABRICKS_HOST", "dbc-bare.cloud.databricks.com")
    assert sheets.databricks_host() == "https://dbc-bare.cloud.databricks.com"
    monkeypatch.setenv("DATABRICKS_HOST", "https://dbc-with-scheme.cloud.databricks.com/")
    assert sheets.databricks_host() == "https://dbc-with-scheme.cloud.databricks.com"


@pytest.mark.asyncio
async def test_missing_token_never_constructs_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sheets, "databricks_host", lambda: pytest.fail("unexpected host lookup"))
    output = await write_new_sheet("", NewSheet(title="test", rows=[[1]]))
    assert output == {"error": NO_TOKEN}


@pytest.mark.asyncio
async def test_create_neutralizes_formulas_and_returns_only_a_sheets_link(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    tool_payloads = {
        sheets.REMOTE_CREATE: {
            "id": SHEET_ID,
            "mimeType": sheets.SPREADSHEET_MIME,
            "webViewLink": (
                f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit see https://evil.test/x"
            ),
        },
        sheets.REMOTE_READ: {"metadata": {"sheet_tabs": [{"title": "Página1"}]}},
        sheets.REMOTE_UPDATE: {"updatedCells": 6, "updatedRange": "'Página1'!A1:B3"},
    }

    def mock_post(_url: str, **kwargs: Any) -> _MockResponse:
        payload = kwargs.get("json", {})
        method = payload.get("method")
        if method == "notifications/initialized":
            return _MockResponse(204)
        if method == "initialize":
            return _init_resp()
        if method == "tools/call":
            params = payload.get("params", {})
            calls.append(params)
            tool_name = params.get("name")
            return _call_resp(tool_payloads.get(tool_name, {}))
        return _MockResponse(200, {"jsonrpc": "2.0", "id": 1, "result": {}})

    monkeypatch.setattr("requests.post", mock_post)
    sheet = NewSheet(
        title="Vendas",
        rows=[["nome", "total"], ['=IMPORTDATA("https://evil.test")', -5], ["@handle", 2]],
    )
    output = await write_new_sheet(TOKEN, sheet, host="https://adb-123.databricks.com")

    assert output == {
        "written": True,
        "url": f"https://docs.google.com/spreadsheets/d/{SHEET_ID}",
        "spreadsheet_id": SHEET_ID,
        "tab": "Página1",
    }
    assert "evil.test" not in str(output)
    update_call = next(c for c in calls if c.get("name") == sheets.REMOTE_UPDATE)
    assert update_call["arguments"]["values"] == [
        ["nome", "total"],
        ['\'=IMPORTDATA("https://evil.test")', -5],
        ["'@handle", 2],
    ]


@pytest.mark.asyncio
async def test_update_sends_only_the_derived_range(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    def mock_post(_url: str, **kwargs: Any) -> _MockResponse:
        payload = kwargs.get("json", {})
        method = payload.get("method")
        if method == "notifications/initialized":
            return _MockResponse(204)
        if method == "initialize":
            return _init_resp()
        if method == "tools/call":
            params = payload.get("params", {})
            calls.append(params)
            return _call_resp({"updatedCells": 2, "updatedRange": "'Dados'!A2:B2"})
        return _MockResponse(200, {"jsonrpc": "2.0", "id": 1, "result": {}})

    monkeypatch.setattr("requests.post", mock_post)
    update = SheetUpdate(spreadsheet_id=SHEET_ID, tab="Dados", rows=[[1, 2]], first_row=2)
    output = await write_sheet_update(TOKEN, update, host="https://adb-123.databricks.com")

    assert output == {
        "written": True,
        "url": f"https://docs.google.com/spreadsheets/d/{SHEET_ID}",
        "spreadsheet_id": SHEET_ID,
        "tab": "Dados",
    }
    assert calls[0]["arguments"] == {
        "file_id": SHEET_ID,
        "range_a1": "'Dados'!A2:B2",
        "values": [[1, 2]],
    }


@pytest.mark.asyncio
async def test_unrecognized_reply_reported_as_unconfirmed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def mock_post(_url: str, **kwargs: Any) -> _MockResponse:
        payload = kwargs.get("json", {})
        if payload.get("method") == "notifications/initialized":
            return _MockResponse(204)
        if payload.get("method") == "initialize":
            return _init_resp()
        return _MockResponse(
            200,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "result": {
                    "content": [{"type": "text", "text": '{"wrong": "payload"}'}],
                    "isError": False,
                },
            },
        )

    monkeypatch.setattr("requests.post", mock_post)
    sheet = NewSheet(title="test", rows=[[1]])
    output = await write_new_sheet(TOKEN, sheet, host="https://adb-123.databricks.com")
    assert output == {"error": UNCONFIRMED}


@pytest.mark.asyncio
async def test_auth_error_code_asks_to_authorize(monkeypatch: pytest.MonkeyPatch) -> None:
    def mock_post(_url: str, **kwargs: Any) -> _MockResponse:
        payload = kwargs.get("json", {})
        if payload.get("method") == "notifications/initialized":
            return _MockResponse(204)
        if payload.get("method") == "initialize":
            return _init_resp()
        return _MockResponse(
            200,
            {"jsonrpc": "2.0", "id": 2, "error": {"code": -32042, "message": "Auth required"}},
        )

    monkeypatch.setattr("requests.post", mock_post)
    sheet = NewSheet(title="test", rows=[[1]])
    output = await write_new_sheet(TOKEN, sheet, host="https://adb-123.databricks.com")
    assert output == {"error": AUTHORIZE}


@pytest.mark.asyncio
async def test_gateway_403_is_reported_without_the_body(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    opaque_body = f"upstream body with token {TOKEN} and internal details"

    def mock_post(_url: str, **kwargs: Any) -> _MockResponse:
        payload = kwargs.get("json", {})
        if payload.get("method") == "notifications/initialized":
            return _MockResponse(204)
        if payload.get("method") == "initialize":
            return _init_resp()
        return _MockResponse(403, content=opaque_body.encode("utf-8"))

    monkeypatch.setattr("requests.post", mock_post)
    sheet = NewSheet(title="test", rows=[[1]])
    with caplog.at_level(logging.WARNING, logger="crabriks.sheets"):
        output = await write_new_sheet(TOKEN, sheet, host="https://adb-123.databricks.com")
    assert output["error"] == "Google Drive gateway returned HTTP 403. Check consent and access."
    assert TOKEN not in output["error"]
    assert "internal details" not in output["error"]
    assert "Gateway returned HTTP 403" in caplog.text
    assert TOKEN not in caplog.text
    assert "internal details" not in caplog.text


@pytest.mark.asyncio
async def test_timeout_tells_the_user_to_check_drive(monkeypatch: pytest.MonkeyPatch) -> None:
    def mock_post(_url: str, **_kwargs: Any) -> _MockResponse:
        raise requests.Timeout("timed out")

    monkeypatch.setattr("requests.post", mock_post)
    sheet = NewSheet(title="test", rows=[[1]])
    output = await write_new_sheet(TOKEN, sheet, host="https://adb-123.databricks.com")
    assert output == {"error": TIMED_OUT}


@pytest.mark.asyncio
async def test_rpc_rejected_code_reports_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    def mock_post(_url: str, **kwargs: Any) -> _MockResponse:
        payload = kwargs.get("json", {})
        if payload.get("method") == "notifications/initialized":
            return _MockResponse(204)
        if payload.get("method") == "initialize":
            return _init_resp()
        return _MockResponse(
            200,
            {"jsonrpc": "2.0", "id": 2, "error": {"code": -32600, "message": "Invalid request"}},
        )

    monkeypatch.setattr("requests.post", mock_post)
    sheet = NewSheet(title="test", rows=[[1]])
    output = await write_new_sheet(TOKEN, sheet, host="https://adb-123.databricks.com")
    assert output == {"error": REJECTED}


@pytest.mark.asyncio
async def test_create_google_sheet_requires_approval_and_resumes_when_approved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = MemorySessionStore()
    calls: list[str] = []

    tool_payloads = {
        sheets.REMOTE_CREATE: {"id": SHEET_ID, "mimeType": sheets.SPREADSHEET_MIME},
        sheets.REMOTE_READ: {"metadata": {"sheet_tabs": [{"title": "Dados"}]}},
        sheets.REMOTE_UPDATE: {"updatedCells": 1, "updatedRange": "'Dados'!A1:A1"},
    }

    def mock_post(_url: str, **kwargs: Any) -> _MockResponse:
        payload = kwargs.get("json", {})
        method = payload.get("method")
        if method == "notifications/initialized":
            return _MockResponse(204)
        if method == "initialize":
            return _init_resp()
        if method == "tools/call":
            tool_name = payload["params"]["name"]
            calls.append(tool_name)
            return _call_resp(tool_payloads.get(tool_name, {}))
        return _MockResponse(200, {"jsonrpc": "2.0", "id": 1, "result": {}})

    monkeypatch.setattr("requests.post", mock_post)
    monkeypatch.setattr(sheets, "databricks_host", lambda: "https://adb-123.databricks.com")

    # Step 1: Model calls create_google_sheet
    async def call_create(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        del messages, info
        yield {
            0: DeltaToolCall(
                name="create_google_sheet",
                json_args=json.dumps({"sheet": {"title": "Top Products", "rows": [["Product A"]]}}),
                tool_call_id="call-sheet-1",
            )
        }

    ctx = TurnContext(
        owner_id=OWNER,
        store=store,
        model=FunctionModel(stream_function=call_create),
        now=lambda: NOW,
        user_token=TOKEN,
    )

    paused = await run_turn(SESSION_ID, "Put the products in a sheet", ctx=ctx)
    assert paused.status == "pending_approval"
    assert paused.approval_id is not None
    # No remote call made yet before approval!
    assert calls == []

    # Step 2: Resume with approved
    async def reply_after_create(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str]:
        del info
        tool_returns = [
            getattr(p, "content", "")
            for m in messages
            for p in getattr(m, "parts", [])
            if getattr(p, "part_kind", "") == "tool-return"
        ]
        assert len(tool_returns) == 1
        yield "Sheet created successfully: " + str(tool_returns[0])

    resume_ctx = TurnContext(
        owner_id=OWNER,
        store=store,
        model=FunctionModel(stream_function=reply_after_create),
        now=lambda: NOW,
        user_token=TOKEN,
    )

    resumed = await resume_turn(SESSION_ID, paused.approval_id, "approved", ctx=resume_ctx)
    assert resumed.status == "ok"
    assert "Sheet created successfully" in resumed.reply
    assert sheets.REMOTE_CREATE in calls
    assert sheets.REMOTE_UPDATE in calls


@pytest.mark.asyncio
async def test_denied_sheet_approval_makes_no_remote_call(monkeypatch: pytest.MonkeyPatch) -> None:
    store = MemorySessionStore()
    calls: list[str] = []

    def mock_post(_url: str, **kwargs: Any) -> _MockResponse:
        calls.append("unexpected_network_call")
        return _MockResponse(200)

    monkeypatch.setattr("requests.post", mock_post)
    monkeypatch.setattr(sheets, "databricks_host", lambda: "https://adb-123.databricks.com")

    async def call_update(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        del messages, info
        yield {
            0: DeltaToolCall(
                name="update_google_sheet",
                json_args=json.dumps(
                    {
                        "update": {
                            "spreadsheet_id": SHEET_ID,
                            "tab": "Dados",
                            "first_column": "A",
                            "first_row": 1,
                            "rows": [["New Val"]],
                        }
                    }
                ),
                tool_call_id="call-sheet-2",
            )
        }

    ctx = TurnContext(
        owner_id=OWNER,
        store=store,
        model=FunctionModel(stream_function=call_update),
        now=lambda: NOW,
        user_token=TOKEN,
    )

    paused = await run_turn(SESSION_ID, "Update the sheet", ctx=ctx)
    assert paused.status == "pending_approval"
    assert paused.approval_id is not None

    async def reply_after_deny(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str]:
        del info
        tool_returns = [
            getattr(p, "content", "")
            for m in messages
            for p in getattr(m, "parts", [])
            if getattr(p, "part_kind", "") == "tool-return"
        ]
        assert len(tool_returns) == 1
        assert "denied" in str(tool_returns[0]).lower()
        yield "Write was cancelled as requested."

    resume_ctx = TurnContext(
        owner_id=OWNER,
        store=store,
        model=FunctionModel(stream_function=reply_after_deny),
        now=lambda: NOW,
        user_token=TOKEN,
    )

    resumed = await resume_turn(SESSION_ID, paused.approval_id, "denied", ctx=resume_ctx)
    assert resumed.status == "ok"
    assert "cancelled" in resumed.reply
    assert calls == []
