"""Bootstrap files for the platform agent: order, markers, and budgets."""

from pathlib import Path

from crabriks.bootstrap import load_bootstrap
from crabriks.workspace import resolve_agent_workspace

ORDER = ("AGENTS.md", "SOUL.md", "IDENTITY.md", "USER.md", "MEMORY.md")


def test_files_load_in_order_and_a_missing_file_is_a_marker(tmp_path: Path) -> None:
    paths = resolve_agent_workspace(tmp_path, "main")
    paths.directory.mkdir(parents=True)
    paths.agents.write_text("Follow the agreement.\n", encoding="utf-8")
    paths.user_file.write_text("Prefers tables.\n", encoding="utf-8")

    loaded = load_bootstrap(paths)

    assert tuple(item.name for item in loaded.files) == ORDER
    assert loaded.files[0].text == "Follow the agreement.\n"
    assert loaded.files[1].text == "[MISSING] SOUL.md"
    assert loaded.files[2].text == "[MISSING] IDENTITY.md"
    assert loaded.files[3].text == "Prefers tables.\n"
    assert loaded.files[4].text == "[MISSING] MEMORY.md"
    assert loaded.notice is None
    assert not paths.soul.exists()
    assert not paths.memory_dir.exists()


def test_each_file_is_capped_and_one_generic_notice_is_set(tmp_path: Path) -> None:
    paths = _write(
        tmp_path,
        {
            "AGENTS.md": "A" * 8000 + "AGENTS-TAIL",
            "SOUL.md": "é" * 4000 + "SOUL-TAIL",
            "IDENTITY.md": "I" * 10,
            "USER.md": "U" * 10,
            "MEMORY.md": "M" * 10,
        },
    )

    loaded = load_bootstrap(paths)

    by_name = {item.name: item.text for item in loaded.files}
    assert by_name["AGENTS.md"] == "A" * 8000
    assert by_name["SOUL.md"] == "é" * 4000
    assert by_name["IDENTITY.md"] == "I" * 10
    assert by_name["USER.md"] == "U" * 10
    assert by_name["MEMORY.md"] == "M" * 10
    assert "AGENTS-TAIL" not in by_name["AGENTS.md"]
    assert "SOUL-TAIL" not in by_name["SOUL.md"]
    assert loaded.notice == "Bootstrap context was truncated to fit the budget."
    assert ".md" not in loaded.notice


def test_overflow_shortens_memory_before_user(tmp_path: Path) -> None:
    paths = _write(
        tmp_path,
        {
            "AGENTS.md": "A" * 8000,
            "SOUL.md": "S" * 4000,
            "IDENTITY.md": "I" * 4000,
            "USER.md": "U" * 1000,
            "MEMORY.md": "M" * 3000 + "MEMORY-TAIL",
        },
    )

    loaded = load_bootstrap(paths)

    by_name = {item.name: item.text for item in loaded.files}
    assert by_name["AGENTS.md"] == "A" * 8000
    assert by_name["SOUL.md"] == "S" * 4000
    assert by_name["IDENTITY.md"] == "I" * 4000
    assert by_name["USER.md"] == "U" * 1000
    assert by_name["MEMORY.md"] == "M" * 3000
    assert loaded.notice == "Bootstrap context was truncated to fit the budget."
    assert sum(len(item.text) for item in loaded.files) == 20_000


def test_memory_is_emptied_before_user_soul_or_agents_lose_their_budget(
    tmp_path: Path,
) -> None:
    paths = _write(
        tmp_path,
        {
            "AGENTS.md": "A" * 8000 + "AGENTS-TAIL",
            "SOUL.md": "S" * 4000,
            "IDENTITY.md": "I" * 4000,
            "USER.md": "U" * 3991 + "USER-KEPT",
            "MEMORY.md": "M" * 8000 + "MEMORY-TAIL",
        },
    )

    loaded = load_bootstrap(paths)

    by_name = {item.name: item.text for item in loaded.files}
    assert by_name["AGENTS.md"] == "A" * 8000
    assert by_name["SOUL.md"] == "S" * 4000
    assert by_name["IDENTITY.md"] == "I" * 4000
    assert by_name["USER.md"] == "U" * 3991 + "USER-KEPT"
    assert by_name["MEMORY.md"] == ""
    assert loaded.notice == "Bootstrap context was truncated to fit the budget."


def test_a_full_budget_with_no_overflow_has_no_notice(tmp_path: Path) -> None:
    paths = _write(
        tmp_path,
        {
            "AGENTS.md": "A" * 8000,
            "SOUL.md": "S" * 4000,
            "IDENTITY.md": "I" * 4000,
            "USER.md": "U" * 4000,
            "MEMORY.md": "",
        },
    )

    loaded = load_bootstrap(paths)

    by_name = {item.name: item.text for item in loaded.files}
    assert by_name["MEMORY.md"] == ""
    assert by_name["AGENTS.md"] == "A" * 8000
    assert loaded.notice is None
    assert load_bootstrap(paths) == loaded


def test_a_missing_marker_survives_when_the_total_budget_overflows(tmp_path: Path) -> None:
    paths = _write(
        tmp_path,
        {
            "AGENTS.md": "A" * 8000,
            "SOUL.md": "S" * 4000,
            "IDENTITY.md": "I" * 4000,
            "USER.md": "U" * 4000,
        },
    )

    loaded = load_bootstrap(paths)

    by_name = {item.name: item.text for item in loaded.files}
    assert by_name["MEMORY.md"] == "[MISSING] MEMORY.md"
    assert by_name["USER.md"] == "U" * 3981
    assert by_name["IDENTITY.md"] == "I" * 4000
    assert by_name["SOUL.md"] == "S" * 4000
    assert by_name["AGENTS.md"] == "A" * 8000
    assert sum(len(item.text) for item in loaded.files) == 20_000
    assert loaded.notice == "Bootstrap context was truncated to fit the budget."


def test_truncation_leaves_the_git_files_unchanged(tmp_path: Path) -> None:
    original = "A" * 9000
    paths = _write(tmp_path, {"AGENTS.md": original})
    paths.agents.chmod(0o444)

    loaded = load_bootstrap(paths)

    assert loaded.files[0].text == "A" * 8000
    assert paths.agents.read_text(encoding="utf-8") == original
    assert not paths.soul.exists()


def test_user_directives_populate_missing_user_file_and_respect_caps(tmp_path: Path) -> None:
    paths = resolve_agent_workspace(tmp_path, "main")
    paths.directory.mkdir(parents=True)
    paths.agents.write_text("Agents.\n", encoding="utf-8")

    # missing USER.md is replaced by user_directives
    loaded = load_bootstrap(paths, user_directives="Prefers concise Python.\n")
    by_name = {item.name: item.text for item in loaded.files}
    assert by_name["USER.md"] == "Prefers concise Python.\n"
    assert loaded.notice is None

    # oversized user_directives is capped at 4000
    oversized = "D" * 5000
    loaded_capped = load_bootstrap(paths, user_directives=oversized)
    by_name_capped = {item.name: item.text for item in loaded_capped.files}
    assert len(by_name_capped["USER.md"]) == 4000
    assert by_name_capped["USER.md"] == "D" * 4000
    assert loaded_capped.notice == "Bootstrap context was truncated to fit the budget."


def test_optional_context_file_loaded_when_present(tmp_path: Path) -> None:
    paths = resolve_agent_workspace(tmp_path, "main")
    paths.directory.mkdir(parents=True)
    paths.agents.write_text("Agents.\n", encoding="utf-8")
    paths.context_file.write_text("Context documentation.\n", encoding="utf-8")

    loaded = load_bootstrap(paths)
    by_name = {item.name: item.text for item in loaded.files}
    assert by_name.get("CONTEXT.md") == "Context documentation.\n"


def _write(root: Path, contents: dict[str, str]):
    paths = resolve_agent_workspace(root, "main")
    paths.directory.mkdir(parents=True)
    for name, text in contents.items():
        (paths.directory / name).write_text(text, encoding="utf-8")
    return paths
