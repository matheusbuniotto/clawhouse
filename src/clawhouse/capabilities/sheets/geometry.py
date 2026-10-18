"""Geometry and table shapes for Google Sheets capability."""

from __future__ import annotations

import re
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

MAX_ROWS = 500
MAX_COLUMNS = 26
MAX_CELL_CHARS = 1_000

FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
ID_RE = re.compile(r"^[A-Za-z0-9_-]{20,100}$")
TAB_RE = re.compile(r"^[^\[\]:*?/\\']+$")

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
