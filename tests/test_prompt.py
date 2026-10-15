"""Cache-stable system prompt for the platform agent."""

from pathlib import Path

import pytest

from clawhouse.bootstrap import BootstrapContext, BootstrapFile
from clawhouse.prompt import CLOCK, RuntimeMeta, ToolCard, build_system_prompt
from clawhouse.workspace import resolve_agent_workspace

SESSION_A = "11111111-1111-4111-8111-111111111111"
SESSION_B = "22222222-2222-4222-8222-222222222222"

EXPECTED_PREFIX = """\
# Identity
You are Clawhouse, the platform agent main.

# Tools
- clock: Return the current UTC time as an ISO-8601 timestamp."""


def test_prefix_ignores_the_session_and_suffix_names_it() -> None:
    first = build_system_prompt(tools=(CLOCK,), runtime=RuntimeMeta(session_id=SESSION_A))
    second = build_system_prompt(tools=(CLOCK,), runtime=RuntimeMeta(session_id=SESSION_B))

    assert first.prefix == EXPECTED_PREFIX
    assert second.prefix == EXPECTED_PREFIX
    assert first.suffix == f"# Runtime\nsession_id: {SESSION_A}"
    assert second.suffix == f"# Runtime\nsession_id: {SESSION_B}"
    assert first.text == f"{EXPECTED_PREFIX}\n\n{first.suffix}"


def test_agent_without_a_tool_is_rejected() -> None:
    with pytest.raises(ValueError, match="at least one tool"):
        build_system_prompt(tools=(), runtime=RuntimeMeta(session_id=SESSION_A))


def test_sections_follow_fixed_order_and_the_prefix_ignores_the_session(
    tmp_path: Path,
) -> None:
    workspace = resolve_agent_workspace(tmp_path, "main")
    bootstrap = _bootstrap(
        {
            "AGENTS.md": "Follow the agreement.",
            "SOUL.md": "Be brief.",
            "IDENTITY.md": "Name: Clawhouse.",
            "USER.md": "Prefers tables.",
            "MEMORY.md": "Lakebase holds sessions.",
        }
    )
    directory = (tmp_path / "claw" / "agents" / "main").as_posix()
    expected_prefix = f"""\
# Identity
You are Clawhouse, the platform agent main.

## SOUL.md
Be brief.

## IDENTITY.md
Name: Clawhouse.

# Tools
- clock: Return the current UTC time as an ISO-8601 timestamp.

# Project Context
## AGENTS.md
Follow the agreement.

## USER.md
Prefers tables.

## MEMORY.md
Lakebase holds sessions.

# Workspace
{directory}"""

    first = build_system_prompt(
        tools=(CLOCK,),
        runtime=RuntimeMeta(session_id=SESSION_A),
        bootstrap=bootstrap,
        workspace=workspace,
    )
    second = build_system_prompt(
        tools=(CLOCK,),
        runtime=RuntimeMeta(session_id=SESSION_B),
        bootstrap=bootstrap,
        workspace=workspace,
    )

    assert first.prefix == expected_prefix
    assert second.prefix == expected_prefix
    assert SESSION_A not in first.prefix
    assert first.suffix == f"# Runtime\nsession_id: {SESSION_A}"
    assert second.suffix == f"# Runtime\nsession_id: {SESSION_B}"
    assert first.text == f"{expected_prefix}\n\n{first.suffix}"


def test_the_clock_time_stays_in_the_per_turn_suffix() -> None:
    first = build_system_prompt(
        tools=(CLOCK,),
        runtime=RuntimeMeta(session_id=SESSION_A, time="2026-10-10T12:00:00Z"),
    )
    second = build_system_prompt(
        tools=(CLOCK,),
        runtime=RuntimeMeta(session_id=SESSION_A, time="2026-10-10T12:05:00Z"),
    )

    assert first.prefix == second.prefix == EXPECTED_PREFIX
    assert "2026-10-10" not in first.prefix
    assert first.suffix == f"# Runtime\nsession_id: {SESSION_A}\ntime: 2026-10-10T12:00:00Z"
    assert second.suffix == f"# Runtime\nsession_id: {SESSION_A}\ntime: 2026-10-10T12:05:00Z"


def test_empty_skills_project_and_workspace_sections_are_omitted() -> None:
    bootstrap = _bootstrap(dict.fromkeys(_NAMES, ""))

    prompt = build_system_prompt(
        tools=(CLOCK,),
        runtime=RuntimeMeta(session_id=SESSION_A),
        bootstrap=bootstrap,
    )

    assert prompt.prefix == EXPECTED_PREFIX
    assert "# Skills" not in prompt.text
    assert "# Project Context" not in prompt.text
    assert "# Workspace" not in prompt.text


def test_a_truncation_notice_appears_once_and_names_no_file() -> None:
    bootstrap = BootstrapContext(
        files=(
            BootstrapFile(name="AGENTS.md", text="Follow the agreement."),
            BootstrapFile(name="SOUL.md", text="[MISSING] SOUL.md"),
            BootstrapFile(name="IDENTITY.md", text=""),
            BootstrapFile(name="USER.md", text=""),
            BootstrapFile(name="MEMORY.md", text=""),
        ),
        notice="Bootstrap context was truncated to fit the budget.",
    )

    prompt = build_system_prompt(
        tools=(CLOCK,),
        runtime=RuntimeMeta(session_id=SESSION_A),
        bootstrap=bootstrap,
    )

    assert prompt.text.count("Bootstrap context was truncated to fit the budget.") == 1
    assert "## SOUL.md\n[MISSING] SOUL.md" in prompt.prefix
    assert "## IDENTITY.md" not in prompt.text
    project = (
        "# Project Context\n"
        "## AGENTS.md\n"
        "Follow the agreement.\n\n"
        "Bootstrap context was truncated to fit the budget."
    )
    assert project in prompt.text


def test_system_prompt_preserves_deterministic_order_of_tools() -> None:
    prompt = build_system_prompt(
        tools=(
            CLOCK,
            ToolCard(name="billing__get_balance", description="Get billing balance"),
            ToolCard(name="system_ai__describe_table", description="Describe table"),
        ),
        runtime=RuntimeMeta(session_id=SESSION_A),
    )
    tools_section = (
        "# Tools\n"
        "- clock: Return the current UTC time as an ISO-8601 timestamp.\n"
        "- billing__get_balance: Get billing balance\n"
        "- system_ai__describe_table: Describe table"
    )
    assert tools_section in prompt.prefix


def test_custom_assistant_name_and_emoji_in_identity() -> None:
    prompt = build_system_prompt(
        tools=(CLOCK,),
        runtime=RuntimeMeta(session_id=SESSION_A),
        assistant_name="Jarvis",
        signature_emoji="🤖",
    )
    assert "# Identity\nYou are Jarvis 🤖, the platform agent main." in prompt.prefix


def test_birth_ritual_section_injected_when_requested() -> None:
    prompt = build_system_prompt(
        tools=(CLOCK,),
        runtime=RuntimeMeta(session_id=SESSION_A),
        birth_ritual=True,
    )
    assert "# Birth Ritual" in prompt.prefix
    assert "preferred name" in prompt.prefix
    assert "role" in prompt.prefix
    assert "tone" in prompt.prefix
    assert "emoji" in prompt.prefix
    assert "save_profile" in prompt.prefix


def test_context_file_rendered_in_project_context() -> None:
    bootstrap = BootstrapContext(
        files=(
            BootstrapFile(name="AGENTS.md", text="Operating rules."),
            BootstrapFile(name="CONTEXT.md", text="Domain and architecture notes."),
        ),
        notice=None,
    )
    prompt = build_system_prompt(
        tools=(CLOCK,),
        runtime=RuntimeMeta(session_id=SESSION_A),
        bootstrap=bootstrap,
    )
    assert "## CONTEXT.md\nDomain and architecture notes." in prompt.prefix


_NAMES = ("AGENTS.md", "SOUL.md", "IDENTITY.md", "USER.md", "MEMORY.md")


def _bootstrap(contents: dict[str, str]) -> BootstrapContext:
    return BootstrapContext(
        files=tuple(BootstrapFile(name=name, text=contents.get(name, "")) for name in _NAMES),
        notice=None,
    )
