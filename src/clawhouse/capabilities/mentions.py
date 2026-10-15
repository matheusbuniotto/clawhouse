"""Mention extraction, context bundling, and session history compaction."""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai_harness.compaction import (
    ClearToolResults,
    SummarizingCompaction,
    TieredCompaction,
    compact_now,
)

from clawhouse.store.shapes import CustomAgent, TranscriptEntry

if TYPE_CHECKING:
    from pydantic_ai.models import Model

    from clawhouse.capabilities.databricks import DatabricksCapability
    from clawhouse.capabilities.workspace import WorkspacePaths
    from clawhouse.store.store import SessionStore

logger = logging.getLogger("clawhouse.mentions")

_TABLE_REGEX = re.compile(r"@([a-zA-Z0-9_]+\.[a-zA-Z0-9_]+\.[a-zA-Z0-9_]+)")
_SUMMARY_PREFIX = "Summary of previous conversation:\n\n"
_FILE_PREFIX_REGEX = re.compile(r"@file:([^\s]+)")
_FILE_EXT_REGEX = re.compile(r"@([a-zA-Z0-9_\-\./]+\.(?:md|py|json|txt|ya?ml|sql))")
_AGENT_REGEX = re.compile(r"@([a-zA-Z0-9_]+)(?![\.\:\/])")
_SKILL_REGEX = re.compile(r"/skill:([a-zA-Z0-9_\-]+)")


@dataclass(frozen=True, slots=True)
class MentionBundle:
    injected_context: str
    target_agent: CustomAgent | None = None


def extract_table_mentions(text: str) -> list[str]:
    return list(dict.fromkeys(_TABLE_REGEX.findall(text)))


def extract_file_mentions(text: str) -> list[str]:
    files: list[str] = []
    files.extend(_FILE_PREFIX_REGEX.findall(text))
    for m in _FILE_EXT_REGEX.findall(text):
        if "." in m and m not in files and not _TABLE_REGEX.fullmatch(f"@{m}"):
            files.append(m)
    return list(dict.fromkeys(files))


def extract_agent_mentions(text: str) -> list[str]:
    raw_tokens = re.findall(r"@([a-zA-Z0-9_\-\.\:\/]+)", text)
    agents = [t for t in raw_tokens if not any(c in t for c in (".", ":", "/"))]
    return list(dict.fromkeys(agents))


def extract_skill_mentions(text: str) -> list[str]:
    return list(dict.fromkeys(_SKILL_REGEX.findall(text)))


async def _resolve_agent_context(
    text: str, store: SessionStore, owner_id: str, default_agent: str | None = None
) -> tuple[CustomAgent | None, str | None]:
    agent_names = extract_agent_mentions(text)
    if not agent_names and default_agent:
        agent_names = [default_agent]
    if not agent_names:
        return None, None
    custom_agents = await store.list_custom_agents(owner_id)
    lower_mentions = {a.lower() for a in agent_names}
    for ca in custom_agents:
        if ca.name.lower() in lower_mentions:
            part = (
                f"### Delegated Agent Persona: @{ca.name} (ALREADY REGISTERED)\n"
                f"- Name: {ca.name} {ca.signature_emoji}\n"
                f"- Description: {ca.description}\n"
                f"- Operating Instructions:\n{ca.system_prompt}\n\n"
                f"IMPORTANT INSTRUCTION: The user assigned this task to @{ca.name}.\n"
                f"- You are executing this turn directly AS @{ca.name}.\n"
                f"- Adopt @{ca.name}'s persona, instructions, and emoji {ca.signature_emoji}.\n"
                f"- No separate delegation tool is needed; carry out analysis as @{ca.name}.\n"
                f"- DO NOT call `create_agent` for '@{ca.name}' because it already exists."
            )
            return ca, part
    return None, None


def _resolve_skill_context(text: str, workspace: WorkspacePaths | None) -> list[str]:
    skills = extract_skill_mentions(text)
    parts: list[str] = []
    for skill_name in skills:
        instructions = _read_skill_instructions(skill_name, workspace)
        if instructions is not None:
            parts.append(f"### Skill Instructions: {skill_name}\n{instructions}")
        else:
            parts.append(f"### Skill: {skill_name} (not found)")
    return parts


async def resolve_mention_bundles(  # noqa: PLR0913
    text: str,
    *,
    store: SessionStore,
    owner_id: str,
    workspace: WorkspacePaths | None = None,
    databricks_cap: DatabricksCapability | None = None,
    default_agent: str | None = None,
) -> MentionBundle:
    context_parts: list[str] = []

    # 1. Resolve table mentions
    for table_name in extract_table_mentions(text):
        desc = await _describe_table(table_name, databricks_cap)
        if desc:
            context_parts.append(f"### Table Context: {table_name}\n{desc}")

    # 2. Resolve file mentions
    for file_path in extract_file_mentions(text):
        content = _read_file_content(file_path, workspace)
        if content:
            context_parts.append(f"### File Context: {file_path}\n{content}")

    # 3. Resolve target agent mention
    target_agent, agent_part = await _resolve_agent_context(
        text, store, owner_id, default_agent=default_agent
    )
    if agent_part:
        context_parts.append(agent_part)

    # 4. Resolve skill mentions (/skill:{name})
    context_parts.extend(_resolve_skill_context(text, workspace))

    injected = "\n\n".join(context_parts)
    return MentionBundle(injected_context=injected, target_agent=target_agent)


async def _describe_table(
    table_name: str, databricks_cap: DatabricksCapability | None
) -> str | None:
    if not databricks_cap:
        return f"Columns: known table {table_name}"
    try:
        client = databricks_cap.client_factory(databricks_cap.user_token)
        info = client.tables.get(full_name=table_name)
        cols_text = []
        for col in getattr(info, "columns", None) or []:
            t_name = getattr(col, "type_text", getattr(col, "type_name", "UNKNOWN"))
            cols_text.append(f"- {col.name}: {t_name}")
        comment = getattr(info, "comment", None)
        comment_str = f"Comment: {comment}\n" if comment else ""
        return f"{comment_str}Columns:\n" + "\n".join(cols_text)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to describe mentioned table %s: %s", table_name, exc)
        return f"Table {table_name} metadata unavailable."


def _read_file_content(file_path: str, workspace: WorkspacePaths | None) -> str | None:
    if not workspace:
        return None
    candidate = workspace.directory / file_path
    if not candidate.exists() and not file_path.startswith("claw/"):
        candidate = workspace.directory.parent.parent.parent / file_path
    if candidate.exists() and candidate.is_file():
        try:
            return candidate.read_text(encoding="utf-8")[:4000]
        except Exception:  # noqa: BLE001
            return None
    return None


def _read_skill_instructions(skill_name: str, workspace: WorkspacePaths | None) -> str | None:
    if not workspace:
        return None
    candidate = workspace.skills / skill_name / "SKILL.md"
    if not candidate.exists():
        repo_root = workspace.directory.parent.parent.parent
        for alt in (
            repo_root / ".agents" / "skills" / skill_name / "SKILL.md",
            repo_root / "skills" / skill_name / "SKILL.md",
        ):
            if alt.exists():
                candidate = alt
                break

    if candidate.exists() and candidate.is_file():
        try:
            return candidate.read_text(encoding="utf-8")[:8000]
        except Exception:  # noqa: BLE001
            return None
    return None


def _transcript_to_messages(transcript: Sequence[TranscriptEntry]) -> list[ModelMessage]:
    messages: list[ModelMessage] = []
    for entry in transcript:
        if entry.role == "user":
            messages.append(ModelRequest(parts=[UserPromptPart(content=entry.content)]))
        elif entry.role == "assistant":
            messages.append(ModelResponse(parts=[TextPart(content=entry.content)]))
    return messages


@dataclass(frozen=True, slots=True)
class CompactionResult:
    """A compacted transcript: the summary checkpoint plus the retained tail."""

    summary: str
    entries: tuple[TranscriptEntry, ...]


def _find_summary_text(compacted: Sequence[ModelMessage]) -> str:
    """The summarizer's prose: the first system part, minus the harness prefix."""
    for message in compacted:
        if isinstance(message, ModelRequest):
            for part in message.parts:
                if isinstance(part, SystemPromptPart) and part.content:
                    return part.content.removeprefix(_SUMMARY_PREFIX)
    return "Session context successfully compacted."


def _compacted_entries(compacted: Sequence[ModelMessage]) -> tuple[TranscriptEntry, ...]:
    """Replay a compacted message list back into the transcript it replaces."""
    entries: list[TranscriptEntry] = []
    for message in compacted:
        for part in message.parts:
            entry = _entry_from_part(part)
            if entry is not None:
                entries.append(entry)
    return tuple(entries)


def _entry_from_part(part: object) -> TranscriptEntry | None:
    if isinstance(part, SystemPromptPart):
        return _summary_entry(part)
    if isinstance(part, UserPromptPart | TextPart):
        return _text_entry(part)
    if isinstance(part, ToolCallPart | ToolReturnPart):
        return _tool_entry(part)
    return None


def _summary_entry(part: SystemPromptPart) -> TranscriptEntry | None:
    summary = part.content.removeprefix(_SUMMARY_PREFIX)
    return TranscriptEntry(role="assistant", content=summary) if summary else None


def _text_entry(part: UserPromptPart | TextPart) -> TranscriptEntry | None:
    content = part.content
    if not isinstance(content, str) or not content:
        return None
    if isinstance(part, UserPromptPart):
        return TranscriptEntry(role="user", content=content)
    return TranscriptEntry(role="assistant", content=content)


def _tool_entry(part: ToolCallPart | ToolReturnPart) -> TranscriptEntry:
    if isinstance(part, ToolCallPart):
        return TranscriptEntry(
            role="tool_call",
            content=part.args_as_json_str(),
            tool_name=part.tool_name,
            tool_call_id=part.tool_call_id,
        )
    return TranscriptEntry(
        role="tool_result",
        content=str(part.content),
        tool_name=part.tool_name,
        tool_call_id=part.tool_call_id,
    )


def tiered_compaction(
    *,
    target_tokens: int | None = None,
    target_fraction: float | None = None,
    keep_messages: int = 20,
    preserve_first_user_message: bool = True,
) -> TieredCompaction[Any]:
    """Cheap-first compaction: clear stale tool results, summarize only if still over budget."""
    return TieredCompaction(
        tiers=[
            ClearToolResults(max_tokens=1),
            SummarizingCompaction(
                max_messages=1,
                keep_messages=keep_messages,
                preserve_first_user_message=preserve_first_user_message,
            ),
        ],
        target_tokens=target_tokens,
        target_fraction=target_fraction,
    )


async def execute_compaction(
    store: SessionStore,
    session_id: str,
    owner_id: str,
    model: Model,
) -> CompactionResult:
    transcript = await store.transcript(session_id, owner_id)
    if not transcript:
        return CompactionResult(summary="No session history to compact.", entries=())

    messages = _transcript_to_messages(transcript)
    # keep_messages=1 + target_tokens=1 force the tiered policy to the summarization tier.
    strategy = tiered_compaction(
        target_tokens=1, keep_messages=1, preserve_first_user_message=False
    )
    compacted = await compact_now(strategy, messages, model=model)
    return CompactionResult(
        summary=_find_summary_text(compacted),
        entries=_compacted_entries(compacted),
    )
