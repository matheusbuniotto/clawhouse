"""Backward-compatible facade for crabriks.capabilities.skills."""

from crabriks.capabilities.skills import (
    MAX_SKILL_SIZE,
    DuplicateSkillName,
    InvalidSkillFrontmatter,
    MissingSkillField,
    SkillError,
    SkillFrontmatter,
    SkillNotFoundError,
    SkillOversizeError,
    SkillsCache,
    SkillsCatalog,
    load_skills,
    parse_skill_markdown,
)

__all__ = [
    "MAX_SKILL_SIZE",
    "DuplicateSkillName",
    "InvalidSkillFrontmatter",
    "MissingSkillField",
    "SkillError",
    "SkillFrontmatter",
    "SkillNotFoundError",
    "SkillOversizeError",
    "SkillsCache",
    "SkillsCatalog",
    "load_skills",
    "parse_skill_markdown",
]
