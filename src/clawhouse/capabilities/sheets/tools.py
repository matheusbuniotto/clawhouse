"""Toolset and capability adapter for Google Sheets."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.toolsets import FunctionToolset

from clawhouse.capabilities.sheets.gateway import (
    _guarded,
    _write_new,
    _write_update,
    databricks_host,
)
from clawhouse.capabilities.sheets.geometry import NewSheet, SheetUpdate

WRITE_TOOLS = frozenset({"create_google_sheet", "update_google_sheet"})


async def write_new_sheet(token: str, sheet: NewSheet, host: str | None = None) -> dict[str, Any]:
    resolved_host = host or (databricks_host() if token else "")
    return await _guarded(token, lambda: _write_new(token, resolved_host, sheet))


async def write_sheet_update(
    token: str, update: SheetUpdate, host: str | None = None
) -> dict[str, Any]:
    resolved_host = host or (databricks_host() if token else "")
    return await _guarded(token, lambda: _write_update(token, resolved_host, update))


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


__all__ = [
    "WRITE_TOOLS",
    "GoogleSheetsCapability",
    "NewSheet",
    "SheetUpdate",
    "sheets_toolset",
    "write_new_sheet",
    "write_sheet_update",
]
