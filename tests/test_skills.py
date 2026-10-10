"""Unit tests for skills: frontmatter validation, catalog search, on-demand read, and caching."""

from pathlib import Path

import pytest

from crabriks.prompt import SkillCard
from crabriks.skills import (
    MAX_SKILL_SIZE,
    DuplicateSkillName,
    InvalidSkillFrontmatter,
    MissingSkillField,
    SkillNotFoundError,
    SkillOversizeError,
    SkillsCache,
    load_skills,
    parse_skill_markdown,
)
from crabriks.workspace import resolve_agent_workspace


def test_parse_valid_frontmatter_and_body() -> None:
    text = """---
name: sql
description: Run a warehouse query.
---
# SQL Skill
Instructions for SQL."""
    data, body = parse_skill_markdown(text)
    assert data.name == "sql"
    assert data.description == "Run a warehouse query."
    assert body == "# SQL Skill\nInstructions for SQL."


def test_parse_frontmatter_missing_opening_delimiter() -> None:
    text = "name: sql\ndescription: Run a query.\n---\nbody"
    with pytest.raises(InvalidSkillFrontmatter, match="must start with '---'"):
        parse_skill_markdown(text)


def test_parse_frontmatter_missing_closing_delimiter() -> None:
    text = "---\nname: sql\ndescription: Run a query.\nbody without closing"
    with pytest.raises(InvalidSkillFrontmatter, match="missing closing '---'"):
        parse_skill_markdown(text)


def test_parse_frontmatter_invalid_yaml() -> None:
    text = "---\n: : bad yaml\n---\nbody"
    with pytest.raises(InvalidSkillFrontmatter, match="Invalid YAML"):
        parse_skill_markdown(text)


def test_parse_frontmatter_not_a_mapping() -> None:
    text = "---\n- item 1\n- item 2\n---\nbody"
    with pytest.raises(InvalidSkillFrontmatter, match="YAML mapping"):
        parse_skill_markdown(text)


@pytest.mark.parametrize(
    "frontmatter",
    [
        "description: Only description\n",
        "name: ''\ndescription: Has desc\n",
        "name: '   '\ndescription: Has desc\n",
    ],
)
def test_parse_frontmatter_missing_name(frontmatter: str) -> None:
    text = f"---\n{frontmatter}---\nbody"
    with pytest.raises(MissingSkillField, match="requires non-empty 'name'"):
        parse_skill_markdown(text)


@pytest.mark.parametrize(
    "frontmatter",
    [
        "name: sql\n",
        "name: sql\ndescription: ''\n",
        "name: sql\ndescription: '   '\n",
    ],
)
def test_parse_frontmatter_missing_description(frontmatter: str) -> None:
    text = f"---\n{frontmatter}---\nbody"
    with pytest.raises(MissingSkillField, match="requires non-empty 'description'"):
        parse_skill_markdown(text)


def test_load_skills_empty_or_missing_directory(tmp_path: Path) -> None:
    assert len(load_skills(None)) == 0
    assert len(load_skills(tmp_path / "non-existent")) == 0

    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    assert len(load_skills(skills_dir)) == 0


def test_load_skills_discovers_skills_under_workspace_folder(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    sql_dir = skills_dir / "sql"
    sql_dir.mkdir(parents=True)
    (sql_dir / "SKILL.md").write_text(
        "---\nname: sql\ndescription: Run a warehouse query.\n---\n# SQL\nRun queries.\n",
        encoding="utf-8",
    )

    bash_dir = skills_dir / "bash"
    bash_dir.mkdir(parents=True)
    (bash_dir / "SKILL.md").write_text(
        "---\nname: bash\ndescription: Run shell commands.\n---\n# Bash\nRun commands.\n",
        encoding="utf-8",
    )

    catalog = load_skills(skills_dir)
    assert len(catalog) == 2
    assert catalog.cards() == (
        SkillCard(name="bash", description="Run shell commands."),
        SkillCard(name="sql", description="Run a warehouse query."),
    )


def test_load_skills_ignores_files_and_directories_without_skill_md(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "README.md").write_text("Ignore me", encoding="utf-8")
    (skills_dir / "empty-dir").mkdir()
    (skills_dir / ".hidden-dir").mkdir()

    catalog = load_skills(skills_dir)
    assert len(catalog) == 0


def test_load_skills_duplicate_name_raises_error(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    first = skills_dir / "first"
    first.mkdir(parents=True)
    (first / "SKILL.md").write_text(
        "---\nname: duplicate\ndescription: First duplicate.\n---\nbody",
        encoding="utf-8",
    )

    second = skills_dir / "second"
    second.mkdir(parents=True)
    (second / "SKILL.md").write_text(
        "---\nname: duplicate\ndescription: Second duplicate.\n---\nbody",
        encoding="utf-8",
    )

    with pytest.raises(DuplicateSkillName, match="Duplicate skill name 'duplicate'"):
        load_skills(skills_dir)


def test_skills_search_matches_name_and_description(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    sql_dir = skills_dir / "sql"
    sql_dir.mkdir(parents=True)
    (sql_dir / "SKILL.md").write_text(
        "---\nname: sql\ndescription: Run a warehouse SQL query.\n---\nbody",
        encoding="utf-8",
    )

    review_dir = skills_dir / "review"
    review_dir.mkdir(parents=True)
    (review_dir / "SKILL.md").write_text(
        "---\nname: code-review\ndescription: Review pull requests and git diffs.\n---\nbody",
        encoding="utf-8",
    )

    catalog = load_skills(skills_dir)

    # Search by exact name
    assert catalog.search("sql") == (
        SkillCard(name="sql", description="Run a warehouse SQL query."),
    )

    # Search by description keyword
    assert catalog.search("warehouse") == (
        SkillCard(name="sql", description="Run a warehouse SQL query."),
    )

    # Search by goal phrase
    assert catalog.search("review pull requests") == (
        SkillCard(name="code-review", description="Review pull requests and git diffs."),
    )

    # Search with no match
    assert catalog.search("nonexistent") == ()

    # Blank query
    assert catalog.search("   ") == ()


def test_skills_read_returns_exact_body(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    sql_dir = skills_dir / "sql"
    sql_dir.mkdir(parents=True)
    (sql_dir / "SKILL.md").write_text(
        "---\nname: sql\ndescription: Run a query.\n---\n# Instructions\nExecute the query.",
        encoding="utf-8",
    )

    catalog = load_skills(skills_dir)
    assert catalog.read("sql") == "# Instructions\nExecute the query."


def test_skills_read_unknown_name_raises_not_found(tmp_path: Path) -> None:
    catalog = load_skills(tmp_path)
    with pytest.raises(SkillNotFoundError, match="Skill 'unknown' not found"):
        catalog.read("unknown")


def test_skills_read_rejects_oversize_body(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    big_dir = skills_dir / "big"
    big_dir.mkdir(parents=True)
    oversize_body = "x" * (MAX_SKILL_SIZE + 1)
    (big_dir / "SKILL.md").write_text(
        f"---\nname: big\ndescription: Large skill.\n---\n{oversize_body}",
        encoding="utf-8",
    )

    catalog = load_skills(skills_dir)
    with pytest.raises(SkillOversizeError, match="exceeds maximum size"):
        catalog.read("big")


def test_skills_read_accepts_exact_max_size(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    exact_dir = skills_dir / "exact"
    exact_dir.mkdir(parents=True)
    exact_body = "x" * MAX_SKILL_SIZE
    (exact_dir / "SKILL.md").write_text(
        f"---\nname: exact\ndescription: Exactly max size.\n---\n{exact_body}",
        encoding="utf-8",
    )

    catalog = load_skills(skills_dir)
    assert len(catalog.read("exact")) == MAX_SKILL_SIZE


def test_discovery_runs_once_per_session_and_is_cached(tmp_path: Path) -> None:
    workspace = resolve_agent_workspace(tmp_path, "main")
    workspace.skills.mkdir(parents=True)
    sql_dir = workspace.skills / "sql"
    sql_dir.mkdir()
    (sql_dir / "SKILL.md").write_text(
        "---\nname: sql\ndescription: Initial description.\n---\ninitial body",
        encoding="utf-8",
    )

    cache = SkillsCache()
    session_a = "11111111-1111-4111-8111-111111111111"
    session_b = "22222222-2222-4222-8222-222222222222"

    first_catalog = cache.get_or_discover(session_a, workspace)
    assert first_catalog.cards() == (SkillCard(name="sql", description="Initial description."),)

    # Modify skill on disk
    (sql_dir / "SKILL.md").write_text(
        "---\nname: sql\ndescription: Updated description.\n---\nupdated body",
        encoding="utf-8",
    )

    # Same session still returns the cached catalog
    cached_catalog = cache.get_or_discover(session_a, workspace)
    assert cached_catalog.cards() == (SkillCard(name="sql", description="Initial description."),)
    assert cached_catalog is first_catalog

    # Different session discovers the new state
    new_catalog = cache.get_or_discover(session_b, workspace)
    assert new_catalog.cards() == (SkillCard(name="sql", description="Updated description."),)
