"""HTTP RPC gateway client and validation for Google Sheets."""

from __future__ import annotations

import json
import logging
import os
import sys
from collections.abc import Awaitable, Callable
from typing import Any

import anyio
import requests
from databricks.sdk import WorkspaceClient

from clawhouse.capabilities.sheets.geometry import (
    ID_RE,
    TAB_RE,
    NewSheet,
    SheetUpdate,
    a1_range,
    neutralized,
)

logger = logging.getLogger("clawhouse.sheets")

SERVICE = "system.ai.google_drive"
REMOTE_CREATE = "google_file_create"
REMOTE_READ = "google_file_read"
REMOTE_UPDATE = "google_sheet_update_values"
SPREADSHEET_MIME = "application/vnd.google-apps.spreadsheet"

TIMEOUT_SECONDS = 30
MAX_RESPONSE_BYTES = 512_000
AUTH_CODES = frozenset({-32042, -32006})

NO_TOKEN = "A forwarded Databricks user token is required. Nothing was written."
UNCONFIRMED = "Google Sheets write unconfirmed. Check your Drive before retrying."
TIMED_OUT = "Google Sheets timed out. Check your Drive before retrying."
AUTHORIZE = "Authorize Google Drive in Databricks Catalog Explorer. Nothing was written."
REJECTED = "Google rejected the request. Check your Drive before retrying."
UNAVAILABLE = "Google Sheets unavailable. Check your Drive before retrying."


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
    mod = sys.modules.get("clawhouse.capabilities.sheets")
    if mod is not None:
        patched = getattr(mod, "databricks_host", None)
        if patched is not None and patched is not databricks_host:
            return str(patched())
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
