"""Slash-command interception: recognized control commands never reach the model.

`parse_command` is pure. `dispatch_command` runs the command's workflow and returns the
reply and any transcript replacement, keeping command branches out of model execution.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from crabriks.capabilities.mentions import execute_compaction
from crabriks.capabilities.schedules import (
    InvalidScheduleCommand,
    ParsedSchedule,
    create_schedule_entry,
    parse_schedule_command,
)

if TYPE_CHECKING:
    from datetime import datetime

    from pydantic_ai.models import Model

    from crabriks.store.shapes import TranscriptEntry
    from crabriks.store.store import SessionStore


@dataclass(frozen=True, slots=True)
class Compact:
    """Summarize the conversation through the tiered compaction policy."""


@dataclass(frozen=True, slots=True)
class Clear:
    """Reset the session transcript while keeping its identity and ownership."""


@dataclass(frozen=True, slots=True)
class InvalidCommand:
    """A recognized command whose arguments are malformed; carries the usage text."""

    message: str


Command = Compact | Clear | ParsedSchedule | InvalidCommand


@dataclass(frozen=True, slots=True)
class CommandContext:
    """Primitives a command workflow needs from the claiming turn."""

    store: SessionStore
    session_id: str
    owner_id: str
    model: Model
    now: datetime


@dataclass(frozen=True, slots=True)
class CommandOutcome:
    """The assistant reply, plus the transcript it replaces (None to keep the old one)."""

    reply: str
    replacement: tuple[TranscriptEntry, ...] | None = None


def parse_command(text: str) -> Command | None:
    """Resolve a control command, or `None` when the message is an ordinary turn."""
    stripped = text.strip()
    if stripped == "/compact":
        return Compact()
    if stripped == "/clear":
        return Clear()
    try:
        return parse_schedule_command(stripped)
    except InvalidScheduleCommand as exc:
        return InvalidCommand(message=str(exc))


async def dispatch_command(command: Command, *, ctx: CommandContext) -> CommandOutcome:
    """Execute the command's workflow and return its reply and transcript replacement."""
    if isinstance(command, Compact):
        result = await execute_compaction(ctx.store, ctx.session_id, ctx.owner_id, ctx.model)
        return CommandOutcome(
            reply="Conversation history compacted successfully.",
            replacement=result.entries,
        )
    if isinstance(command, Clear):
        return CommandOutcome(
            reply="🧹 Session cleared. The next turn starts with a fresh history.",
            replacement=(),
        )
    if isinstance(command, InvalidCommand):
        return CommandOutcome(reply=command.message)
    return CommandOutcome(reply=await _schedule_confirmation(command, ctx=ctx))


async def _schedule_confirmation(command: ParsedSchedule, *, ctx: CommandContext) -> str:
    schedule = await create_schedule_entry(
        ctx.store,
        session_id=ctx.session_id,
        owner_id=ctx.owner_id,
        cron_expression=command.cron_expression,
        prompt=command.prompt,
        now=ctx.now,
    )
    return (
        f"⏰ Scheduled automation created successfully!\n\n"
        f"- **Schedule ID**: `{schedule.id}`\n"
        f"- **Cron Expression**: `{schedule.cron_expression}`\n"
        f"- **First Run At**: `{schedule.next_run_at.isoformat()}`\n"
        f"- **Instruction**: {schedule.prompt}"
    )
