"""Databricks native user sandbox: system.ai.python_exec and Workspace files."""

from __future__ import annotations

import hashlib
import io
import json
import logging
import re
from typing import TYPE_CHECKING, Any

from databricks.sdk.service.workspace import ImportFormat

from clawhouse.capabilities.mcp import scrub_token

if TYPE_CHECKING:
    from clawhouse.capabilities.databricks.tools import DatabricksTools

logger = logging.getLogger("clawhouse.sandbox")

_MCP_PYTHON_EXEC_PATH = "/api/2.0/mcp/functions/system/ai/python_exec"
_MAX_OUTPUT_CHARS = 20_000
_MAX_READ_CHARS = 50_000


def user_sandbox_slug(owner_id: str) -> str:
    """Generate a safe, isolated directory name for a user's sandbox workspace."""
    clean_prefix = re.sub(r"[^a-zA-Z0-9_]", "_", owner_id).strip("_") or "user"
    digest = hashlib.sha256(owner_id.encode("utf-8")).hexdigest()[:8]
    return f"{clean_prefix}_{digest}"


def user_sandbox_root(owner_id: str) -> str:
    return f"/Workspace/Shared/clawhouse/sandboxes/{user_sandbox_slug(owner_id)}"


def _check_safe_relative_path(path: str) -> None:
    if not path or path.startswith("/") or ".." in path.split("/"):
        raise ValueError("path traversal denied")


def _resolve_sandbox_path(owner_id: str, relative_path: str) -> str:
    _check_safe_relative_path(relative_path)
    clean_rel = relative_path.strip("/")
    return f"{user_sandbox_root(owner_id)}/{clean_rel}"


def _parse_content_json(text: str) -> tuple[str, bool] | None:
    try:
        parsed = json.loads(text)
        rows = parsed.get("rows")
        if isinstance(rows, list) and rows and isinstance(rows[0], list) and rows[0]:
            return str(rows[0][0]), bool(parsed.get("is_truncated"))
    except json.JSONDecodeError:
        return None
    return None


def _extract_structured_rows(res: Any) -> tuple[str, bool] | None:
    structured = getattr(res, "structuredContent", None) or (
        res.get("structuredContent") if isinstance(res, dict) else None
    )
    if not isinstance(structured, dict):
        return None
    rows = structured.get("rows")
    if isinstance(rows, list) and rows and isinstance(rows[0], list) and rows[0]:
        return str(rows[0][0]), bool(structured.get("is_truncated"))
    return None


def _extract_content_text(res: Any) -> tuple[str, bool] | None:
    content = getattr(res, "content", None) or (
        res.get("content") if isinstance(res, dict) else None
    )
    if not isinstance(content, list) or not content:
        return None
    first = content[0]
    text = getattr(first, "text", None) or (first.get("text") if isinstance(first, dict) else None)
    if not isinstance(text, str):
        return None
    parsed = _parse_content_json(text)
    return parsed if parsed is not None else (text, False)


def _extract_exec_output(res: Any) -> tuple[str, bool]:
    if isinstance(res, dict) and isinstance(res.get("result"), dict):
        res = res["result"]
    structured = _extract_structured_rows(res)
    if structured is not None:
        return structured
    content = _extract_content_text(res)
    if content is not None:
        return content
    return str(res), False


async def python_exec(
    tools: DatabricksTools,
    code: str = "",
    *,
    script_path: str | None = None,
) -> dict[str, object]:
    """Execute Python code in Databricks system.ai.python_exec native sandbox."""
    if not tools.user_token.strip():
        return {"error": "user token required"}

    exec_code = code
    if script_path:
        read_res = await sandbox_read_file(tools, script_path)
        if "error" in read_res:
            return read_res
        exec_code = str(read_res.get("content", ""))

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "system__ai__python_exec",
            "arguments": {"code": exec_code},
        },
    }

    try:
        raw_res = tools.client.api_client.do("POST", _MCP_PYTHON_EXEC_PATH, body=payload)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"python_exec failed: {exc}"}

    raw_output, is_truncated = _extract_exec_output(raw_res)
    scrubbed = scrub_token(raw_output, tools.user_token)

    if len(scrubbed) > _MAX_OUTPUT_CHARS:
        scrubbed = scrubbed[-_MAX_OUTPUT_CHARS:]
        is_truncated = True

    return {
        "output": scrubbed,
        "is_truncated": is_truncated,
    }


async def sandbox_write_file(
    tools: DatabricksTools,
    path: str,
    content: str,
) -> dict[str, object]:
    """Write or overwrite a file in the caller's workspace sandbox."""
    try:
        abs_path = _resolve_sandbox_path(tools.owner_id, path)
    except ValueError as err:
        return {"error": str(err)}

    parent = "/".join(abs_path.split("/")[:-1])
    try:
        tools._call(lambda cl: cl.workspace.mkdirs(parent))
        tools._call(
            lambda cl: cl.workspace.upload(
                abs_path,
                io.BytesIO(content.encode("utf-8")),
                overwrite=True,
                format=ImportFormat.AUTO,
            )
        )
    except Exception as exc:  # noqa: BLE001
        return {"error": f"write failed: {exc}"}

    return {"path": path, "bytes_written": len(content.encode("utf-8"))}


async def sandbox_read_file(
    tools: DatabricksTools,
    path: str,
) -> dict[str, object]:
    """Read a file from the caller's workspace sandbox."""
    try:
        abs_path = _resolve_sandbox_path(tools.owner_id, path)
    except ValueError as err:
        return {"error": str(err)}

    try:
        stream = tools._call(lambda cl: cl.workspace.download(abs_path))
        data = stream.read().decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        return {"error": "file not found", "path": path}

    if len(data) > _MAX_READ_CHARS:
        data = data[:_MAX_READ_CHARS]

    return {"path": path, "content": data}


def _collect_files(client: Any, root_dir: str) -> list[str]:
    files: list[str] = []
    try:
        items = list(client.workspace.list(root_dir))
    except Exception:  # noqa: BLE001
        return files

    prefix = root_dir.rstrip("/") + "/"
    for item in items:
        path = str(item.path)
        is_directory = (
            getattr(item, "is_dir", False)
            or str(getattr(item, "object_type", "")).upper() == "DIRECTORY"
        )
        if is_directory:
            files.extend(_collect_files(client, path))
        else:
            rel = path[len(prefix) :] if path.startswith(prefix) else path
            files.append(rel)
    return files


async def sandbox_list_files(
    tools: DatabricksTools,
    path: str = "",
) -> dict[str, object]:
    """List files in the caller's workspace sandbox recursively."""
    try:
        if path:
            abs_dir = _resolve_sandbox_path(tools.owner_id, path)
        else:
            abs_dir = user_sandbox_root(tools.owner_id)
    except ValueError as err:
        return {"error": str(err)}

    try:
        items = tools._call(lambda cl: _collect_files(cl, abs_dir))
    except Exception as exc:  # noqa: BLE001
        return {"error": f"list failed: {exc}"}

    items.sort()
    return {"files": items}


async def sandbox_reset(tools: DatabricksTools) -> dict[str, object]:
    """Wipe all files from the caller's workspace sandbox and recreate the empty directory."""
    root_dir = user_sandbox_root(tools.owner_id)
    try:
        tools._call(lambda cl: cl.workspace.delete(root_dir, recursive=True))
    except Exception as exc:  # noqa: BLE001
        logger.info("Sandbox reset delete (may not exist yet): %s", exc)

    try:
        tools._call(lambda cl: cl.workspace.mkdirs(root_dir))
    except Exception as exc:  # noqa: BLE001
        return {"error": f"sandbox reset failed: {exc}"}

    return {"reset": True, "file_count": 0}
