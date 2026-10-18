"""Databricks capability provider for Pydantic AI agent integration."""

from __future__ import annotations

import json
import logging
import sys
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from databricks.sdk import WorkspaceClient
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.toolsets import AgentToolset, FunctionToolset

from clawhouse.capabilities.databricks.jobs_client import JobsIdentity, jobs_identity
from clawhouse.capabilities.databricks.tools import DatabricksTools
from clawhouse.capabilities.databricks.warehouse import resolve_warehouse_id

if TYPE_CHECKING:
    from clawhouse.settings import Settings

logger = logging.getLogger("clawhouse.databricks")


def _workspace_client_cls() -> type[WorkspaceClient]:
    mod = sys.modules.get("clawhouse.capabilities.databricks")
    if mod and hasattr(mod, "WorkspaceClient"):
        return mod.WorkspaceClient
    return WorkspaceClient


def default_workspace_client(token: str = "") -> WorkspaceClient:
    """Create a Databricks WorkspaceClient.

    If a user token is provided, explicitly uses `auth_type='pat'` so it does not conflict
    with ambient OAuth service-principal environment variables in Databricks Apps.
    Falls back to ambient authentication if token authentication is not configured
    or fails.
    """
    wc_cls = _workspace_client_cls()
    if token:
        try:
            return wc_cls(token=token, auth_type="pat")
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "WorkspaceClient with user token failed: %s; falling back to ambient auth", exc
            )
    return wc_cls()


async def system_ai_format_delivery(
    tools: DatabricksTools,
    content: str,
    destination: Literal["slack", "sheets"],
    title: str | None = None,
) -> dict[str, object]:
    """Format analytical outputs or reports for Slack or Google Sheets using Databricks AI."""
    if destination == "slack":
        prompt = (
            "You are a technical delivery formatter. Format this report into a clean, "
            "engaging Slack message using Slack mrkdwn syntax (bold, bullet points, emoji).\n"
            f"Include a headline{f' ({title})' if title else ''}, Key Findings, "
            f"and Action Items. Output ONLY the formatted text.\n\nReport:\n{content}"
        )
        formatted = await tools.system_ai_query(prompt)
        return {
            "destination": "slack",
            "formatted_text": formatted,
            "preview": formatted[:200],
        }
    prompt = (
        "You are a data transformation assistant. Convert these findings into a structured "
        "tabular JSON for a spreadsheet with: 'sheet_name' (str), 'headers' (list[str]), "
        f"and 'rows' (list of lists). Output ONLY valid JSON.\n\nReport:\n{content}"
    )
    formatted = await tools.system_ai_query(prompt)
    return {
        "destination": "sheets",
        "raw_json": formatted,
    }


async def delivery_send_webhook(
    url: str,
    payload: dict[str, Any] | str,
) -> dict[str, object]:
    """Send a formatted payload or notification to an external webhook (Slack, Sheets)."""
    data = payload if isinstance(payload, str) else json.dumps(payload)
    req = urllib.request.Request(
        url,
        data=data.encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            code = resp.status
            body = resp.read().decode("utf-8", errors="replace")
            return {"delivered": True, "status_code": code, "response": body[:200]}
    except Exception as exc:  # noqa: BLE001
        return {"delivered": False, "error": f"Webhook delivery failed: {exc}"}


@dataclass
class DatabricksCapability(AbstractCapability[Any]):
    """Provides Unity Catalog discovery, DBSQL query execution, and system.ai tools."""

    client_factory: Callable[[str], WorkspaceClient] = field(
        default_factory=lambda: default_workspace_client
    )
    warehouse_id: str | None = None
    user_token: str = ""
    settings: Settings | None = None
    id: str | None = "databricks"

    def _resolve_jobs_identity(self) -> JobsIdentity:
        def _factory(**kwargs: Any) -> WorkspaceClient:
            if "token" in kwargs:
                return self.client_factory(kwargs["token"])
            return _workspace_client_cls()(**kwargs)

        return jobs_identity(
            settings=self.settings,
            user_token=self.user_token,
            client_factory=_factory,
        )

    def get_toolset(self) -> AgentToolset[Any] | None:
        try:
            client = self.client_factory(self.user_token)
            warehouse_id = resolve_warehouse_id(client, self.warehouse_id)
            impl = DatabricksTools(
                client,
                warehouse_id,
                jobs_identity_resolver=self._resolve_jobs_identity,
                user_token=self.user_token,
                settings=self.settings,
            )
            return FunctionToolset(impl.all_tools())
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "DatabricksCapability failed with user client: %s; trying ambient client", exc
            )
            try:
                ambient = _workspace_client_cls()()
                warehouse_id = resolve_warehouse_id(ambient, self.warehouse_id)
                impl = DatabricksTools(
                    ambient,
                    warehouse_id,
                    jobs_identity_resolver=self._resolve_jobs_identity,
                    user_token=self.user_token,
                    settings=self.settings,
                )
                return FunctionToolset(impl.all_tools())
            except Exception as inner_exc:  # noqa: BLE001
                logger.warning("DatabricksCapability ambient fallback also failed: %s", inner_exc)
                return None
