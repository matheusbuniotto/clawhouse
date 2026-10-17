"""Google Sheets write capability through Databricks AI Gateway system.ai.google_drive.

Mutating tools (create_google_sheet, update_google_sheet) require in-chat approval.
Acts strictly with the user's forwarded token; fails closed when no token is present.
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated, Any

import anyio
import requests
from databricks.sdk import WorkspaceClient
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field
from pydantic_ai import RunContext
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.toolsets import AbstractToolset, FunctionToolset
from pydantic_ai.toolsets.approval_required import ApprovalRequiredToolset

logger = logging.getLogger("clawhouse.sheets")

SERVICE = "system.ai.google_drive"
REMOTE_CREATE = "google_file_create"
REMOTE_READ = "google_file_read"
REMOTE_UPDATE = "google_sheet_update_values"
SPREADSHEET_MIME = "application/vnd.google-apps.spreadsheet"

MAX_ROWS = 500
MAX_COLUMNS = 26
MAX_CELL_CHARS = 1_000
TIMEOUT_SECONDS = 30
MAX_RESPONSE_BYTES = 512_000

FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
ID_RE = re.compile(r"^[A-Za-z0-9_-]{20,100}$")
TAB_RE = re.compile(r"^[^\[\]:*?/\\']+$")
AUTH_CODES = frozenset({-32042, -32006})

NO_TOKEN = "A forwarded Databricks user token is required. Nothing was written."
UNCONFIRMED = "Google Sheets write unconfirmed. Check your Drive before retrying."
TIMED_OUT = "Google Sheets timed out. Check your Drive before retrying."
AUTHORIZE = "Authorize Google Drive in Databricks Catalog Explorer. Nothing was written."
REJECTED = "Google rejected the request. Check your Drive before retrying."
UNAVAILABLE = "Google Sheets unavailable. Check your Drive before retrying."

Cell = str | bool | int | float | None


def _require_rectangle(rows: list[list[Cell]]) -> None:
    width = len(rows[0])
    if not 1 <= width <= MAX_COLUMNS or any(len(row) != width for row in rows):
        message = f"rows must be rectangular and 1 to {MAX_COLUMNS} columns wide"
        raise ValueError(message)
    if any(len(cell) > MAX_CELL_CHARS for row in rows for cell in row if isinstance(cell, str)):
        message = f"a cell is longer than {MAX_CELL_CHARS} characters"
        raise ValueError(message)


def _bounded_rows(rows: list[list[Cell]]) -> list[list[Cell]]:
    if rows:
        _require_rectangle(rows)
    return rows


Rows = Annotated[
    list[list[Cell]],
    Field(min_length=1, max_length=MAX_ROWS),
    BeforeValidator(_bounded_rows),
]


class Table(BaseModel):
    """A bounded rectangle. The model does not choose where the write ends."""

    model_config = ConfigDict(extra="forbid")

    tab: str = Field(min_length=1, max_length=100, pattern=TAB_RE.pattern)
    rows: Rows


class NewSheet(BaseModel):
    """A new spreadsheet in the user's own Drive. Values land on its first tab."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=100)
    rows: Rows


class SheetUpdate(Table):
    """Overwrite one block in a spreadsheet this app is allowed to edit."""

    spreadsheet_id: str = Field(pattern=ID_RE.pattern)
    first_column: str = Field(default="A", pattern=r"^[A-Z]{1,2}$")
    first_row: int = Field(default=1, ge=1, le=100_000)

    @property
    def a1_range(self) -> str:
        """The exact block that will be overwritten, derived from the data's shape."""
        return a1_range(self.tab, self.first_column, self.first_row, self.rows)


def _column_index(name: str) -> int:
    index = 0
    for letter in name:
        index = index * 26 + ord(letter) - ord("A") + 1
    return index


def _column_name(index: int) -> str:
    name = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(ord("A") + remainder) + name
    return name


def a1_range(tab: str, first_column: str, first_row: int, rows: list[list[Cell]]) -> str:
    last = _column_name(_column_index(first_column) + len(rows[0]) - 1)
    end_row = first_row + len(rows) - 1
    return f"'{tab}'!{first_column}{first_row}:{last}{end_row}"


def _as_text(cell: Cell) -> Cell:
    if isinstance(cell, str) and cell.startswith(FORMULA_PREFIXES):
        return f"'{cell}"
    return cell


def neutralized(rows: list[list[Cell]]) -> list[list[Cell]]:
    return [[_as_text(cell) for cell in row] for row in rows]


class GatewayStatusError(Exception):
    def __init__(self, status: int) -> None:
        self.status = status
        super().__init__(f"HTTP {status}")


class GatewayRpcError(Exception):
    def __init__(self, code: int) -> None:
        self.code = code
        super().__init__(f"RPC error {code}")


def normalize_host(host: str) -> str:
    cleaned = host.strip().rstrip("/")
    if cleaned and not cleaned.startswith(("http://", "https://")):
        return f"https://{cleaned}"
    return cleaned


def databricks_host() -> str:
    host = os.environ.get("DATABRICKS_HOST", "").strip()
    if host:
        return normalize_host(host)
    try:
        resolved = WorkspaceClient().config.host
        if isinstance(resolved, str) and resolved:
            return normalize_host(resolved)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Failed to resolve workspace host from client: %s", exc)
    raise RuntimeError("Databricks workspace host is unavailable.")


def _log_gateway_failure(resp: requests.Response) -> None:
    """Log a redacted diagnostic: status, size, and request id, never the body."""
    request_id = resp.headers.get("x-request-id", "")
    logger.warning(
        "Gateway returned HTTP %s (%s bytes%s)",
        resp.status_code,
        len(resp.content or b""),
        f", request-id={request_id}" if request_id else "",
    )


def _validate_rpc_response(resp: requests.Response) -> None:
    if resp.status_code in (401, 403) or resp.status_code >= 300:
        _log_gateway_failure(resp)
        raise GatewayStatusError(resp.status_code)
    if resp.status_code != 204 and resp.content:
        if len(resp.content) > MAX_RESPONSE_BYTES:
            raise ValueError("MCP response exceeds the byte limit")
        if "application/json" not in resp.headers.get("content-type", ""):
            raise ValueError("MCP response was not JSON")


def _extract_rpc_result(body: dict[str, Any]) -> dict[str, Any]:
    error = body.get("error")
    if isinstance(error, dict):
        code = error.get("code")
        code_int = code if isinstance(code, int) else -1
        raise GatewayRpcError(code_int)
    result = body.get("result")
    if not isinstance(result, dict):
        raise TypeError("MCP result was not an object")
    return result


def _post_rpc(
    token: str,
    url: str,
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "Accept-Encoding": "identity",
    }
    try:
        resp = requests.post(
            url,
            json=payload,
            headers=headers,
            timeout=TIMEOUT_SECONDS,
            allow_redirects=False,
        )
    except requests.Timeout as exc:
        raise TimeoutError from exc
    except requests.RequestException as exc:
        raise RuntimeError(f"Network error calling gateway: {exc}") from exc

    _validate_rpc_response(resp)
    if resp.status_code == 204 or not resp.content:
        return None
    body = resp.json()
    if not isinstance(body, dict):
        raise TypeError("MCP response was not an object")
    return _extract_rpc_result(body)


def _exchange(
    token: str,
    host: str,
    tool_name: str,
    arguments: dict[str, Any],
) -> dict[str, Any] | None:
    base_host = normalize_host(host)
    url = f"{base_host}/ai-gateway/mcp-services/{SERVICE}"
    _post_rpc(
        token,
        url,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "clawhouse", "version": "0"},
            },
        },
    )
    _post_rpc(token, url, {"jsonrpc": "2.0", "method": "notifications/initialized"})
    return _post_rpc(
        token,
        url,
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        },
    )


def _parse_payload(result: dict[str, Any] | None) -> dict[str, Any] | None:
    if not result or result.get("isError"):
        return None
    content = result.get("content")
    if not isinstance(content, list) or len(content) != 1:
        return None
    first = content[0]
    text = getattr(first, "text", None) if not isinstance(first, dict) else first.get("text")
    if not isinstance(text, str) or not text:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


async def _json_tool_call(
    token: str,
    host: str,
    tool_name: str,
    arguments: dict[str, Any],
) -> dict[str, Any] | None:
    result = await anyio.to_thread.run_sync(lambda: _exchange(token, host, tool_name, arguments))
    return _parse_payload(result)


def _tab_title(payload: dict[str, Any] | None) -> str | None:
    if payload is None:
        return None
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        return None
    tabs = metadata.get("sheet_tabs")
    if not isinstance(tabs, list) or not tabs or not isinstance(tabs[0], dict):
        return None
    title = tabs[0].get("title")
    if not isinstance(title, str) or TAB_RE.fullmatch(title) is None:
        return None
    return title


def _update_ok(payload: dict[str, Any] | None, expected_cells: int) -> bool:
    if payload is None:
        return False
    cells = payload.get("updatedCells")
    updated_range = payload.get("updatedRange")
    return isinstance(cells, int) and cells == expected_cells and isinstance(updated_range, str)


def _extract_valid_file_id(created: dict[str, Any] | None) -> str | None:
    if created is None or created.get("mimeType") != SPREADSHEET_MIME:
        return None
    file_id = created.get("id")
    if not isinstance(file_id, str) or ID_RE.fullmatch(file_id) is None:
        return None
    return file_id


async def _write_new(token: str, host: str, sheet: NewSheet) -> dict[str, Any]:
    created = await _json_tool_call(
        token, host, REMOTE_CREATE, {"name": sheet.title, "file_type": "spreadsheet"}
    )
    file_id = _extract_valid_file_id(created)
    if file_id is None:
        return {"error": UNCONFIRMED}

    read_meta = await _json_tool_call(
        token, host, REMOTE_READ, {"file_id": file_id, "file_type": "spreadsheet", "limit": 500}
    )
    tab = _tab_title(read_meta)
    url = f"https://docs.google.com/spreadsheets/d/{file_id}"
    if tab is None:
        return {"error": UNCONFIRMED, "url": url}

    values = neutralized(sheet.rows)
    updated = await _json_tool_call(
        token,
        host,
        REMOTE_UPDATE,
        {
            "file_id": file_id,
            "range_a1": a1_range(tab, "A", 1, values),
            "values": values,
        },
    )
    expected = len(values) * len(values[0])
    if not _update_ok(updated, expected):
        return {"error": UNCONFIRMED}
    return {"written": True, "url": url, "spreadsheet_id": file_id, "tab": tab}


async def _write_update(token: str, host: str, update: SheetUpdate) -> dict[str, Any]:
    values = neutralized(update.rows)
    updated = await _json_tool_call(
        token,
        host,
        REMOTE_UPDATE,
        {
            "file_id": update.spreadsheet_id,
            "range_a1": update.a1_range,
            "values": values,
        },
    )
    expected = len(values) * len(values[0])
    if not _update_ok(updated, expected):
        return {"error": UNCONFIRMED}
    url = f"https://docs.google.com/spreadsheets/d/{update.spreadsheet_id}"
    return {
        "written": True,
        "url": url,
        "spreadsheet_id": update.spreadsheet_id,
        "tab": update.tab,
    }


def _failure(exc: Exception) -> str:
    if isinstance(exc, GatewayRpcError):
        if exc.code in AUTH_CODES:
            return AUTHORIZE
        return REJECTED
    if isinstance(exc, GatewayStatusError):
        if exc.status in (401, 403):
            return f"Google Drive gateway returned HTTP {exc.status}. Check consent and access."
        return UNAVAILABLE
    return UNAVAILABLE


async def _guarded(
    token: str,
    action: Callable[[], Awaitable[dict[str, Any]]],
) -> dict[str, Any]:
    if not token:
        return {"error": NO_TOKEN}
    try:
        with anyio.fail_after(TIMEOUT_SECONDS):
            return await action()
    except TimeoutError:
        return {"error": TIMED_OUT}
    except Exception as exc:
        logger.exception("Google Sheets write failed")
        return {"error": _failure(exc)}


async def write_new_sheet(token: str, sheet: NewSheet, host: str | None = None) -> dict[str, Any]:
    resolved_host = host or (databricks_host() if token else "")
    return await _guarded(token, lambda: _write_new(token, resolved_host, sheet))


async def write_sheet_update(
    token: str, update: SheetUpdate, host: str | None = None
) -> dict[str, Any]:
    resolved_host = host or (databricks_host() if token else "")
    return await _guarded(token, lambda: _write_update(token, resolved_host, update))


WRITE_TOOLS = frozenset({"create_google_sheet", "update_google_sheet"})


def sheets_toolset(token: str, host: str | None = None) -> FunctionToolset[Any]:
    async def create_google_sheet(sheet: NewSheet) -> dict[str, Any]:
        """Create a new Google Sheet in your own Drive, only after you approve it in chat.

        The first row is usually the header. Cells that start with = + - or @ are written
        as text. Values land on the spreadsheet's first tab; the result names that tab.
        """
        return await write_new_sheet(token, sheet, host=host)

    async def update_google_sheet(update: SheetUpdate) -> dict[str, Any]:
        """Overwrite one block of a Google Sheet created through this app, after you approve it.

        The block starts at first_column/first_row and is as large as rows. Nothing else changes.
        """
        return await write_sheet_update(token, update, host=host)

    return FunctionToolset([create_google_sheet, update_google_sheet])


@dataclass
class GoogleSheetsCapability(AbstractCapability[Any]):
    """Google Sheets writes for signed-in user via AI Gateway system.ai.google_drive."""

    user_token: str = ""
    host: str | None = None
    id: str | None = "google_sheets"

    def get_toolset(self) -> FunctionToolset[Any]:
        return sheets_toolset(self.user_token, host=self.host)

    def get_wrapper_toolset(self, toolset: AbstractToolset[Any]) -> AbstractToolset[Any]:
        def approval_required(
            _ctx: RunContext[Any],
            tool_def: ToolDefinition,
            _args: dict[str, Any],
        ) -> bool:
            return tool_def.name in WRITE_TOOLS

        return ApprovalRequiredToolset(toolset, approval_required_func=approval_required)
