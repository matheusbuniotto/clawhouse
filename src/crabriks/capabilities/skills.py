"""Skills discovery, frontmatter validation, catalog, and on-demand loading."""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from crabriks.capabilities.workspace import WorkspacePaths

MAX_SKILL_SIZE = 32_768  # 32 KB


@dataclass(frozen=True, slots=True)
class SkillCard:
    name: str
    description: str


class SkillError(Exception):
    """Base exception for skill errors."""


class InvalidSkillFrontmatter(SkillError, ValueError):
    """Frontmatter is missing, malformed, or not a mapping."""


class MissingSkillField(SkillError, ValueError):
    """Frontmatter is missing required 'name' or 'description'."""


class DuplicateSkillName(SkillError, ValueError):
    """Two skills share the same name."""


class SkillNotFoundError(SkillError, KeyError):
    """Skill with the requested name was not found."""


class SkillOversizeError(SkillError, ValueError):
    """Skill body exceeds the maximum size limit."""


@dataclass(frozen=True, slots=True)
class SkillFrontmatter:
    name: str
    description: str


@dataclass(frozen=True, slots=True)
class SkillEntry:
    name: str
    description: str
    path: Path

    def match_score(self, query: str) -> int:
        name_lower = self.name.lower()
        desc_lower = self.description.lower()
        full_text = f"{name_lower} {desc_lower}"
        if query == name_lower:
            return 100
        if query in name_lower:
            return 80
        if query in desc_lower:
            return 50
        words = [w for w in re.findall(r"\w+", query) if len(w) > 1]
        matches = sum(1 for w in words if w in full_text)
        return matches * 10


def parse_skill_markdown(text: str) -> tuple[SkillFrontmatter, str]:
    """Parse frontmatter and body from a SKILL.md file."""
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        raise InvalidSkillFrontmatter("SKILL.md must start with '---'")
    closing_idx = _find_closing_delimiter(lines)
    raw_frontmatter = "".join(lines[1:closing_idx])
    raw_body = "".join(lines[closing_idx + 1 :])
    data = _parse_frontmatter_yaml(raw_frontmatter)
    frontmatter = _validate_frontmatter_fields(data)
    return frontmatter, raw_body.strip()


def _find_closing_delimiter(lines: list[str]) -> int:
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            return idx
    raise InvalidSkillFrontmatter("SKILL.md is missing closing '---' delimiter")


def _parse_frontmatter_yaml(raw: str) -> dict[str, Any]:
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise InvalidSkillFrontmatter(f"Invalid YAML in frontmatter: {exc}") from exc
    if not isinstance(data, dict):
        raise InvalidSkillFrontmatter("Frontmatter must be a YAML mapping")
    return data


def _validate_frontmatter_fields(data: dict[str, Any]) -> SkillFrontmatter:
    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        raise MissingSkillField("Frontmatter requires non-empty 'name'")
    description = data.get("description")
    if not isinstance(description, str) or not description.strip():
        raise MissingSkillField("Frontmatter requires non-empty 'description'")
    return SkillFrontmatter(name=name.strip(), description=description.strip())


@dataclass(frozen=True, slots=True)
class SkillsCatalog:
    """Catalog of discovered skills for a session."""

    entries: tuple[SkillEntry, ...] = ()

    def cards(self) -> tuple[SkillCard, ...]:
        return tuple(SkillCard(name=e.name, description=e.description) for e in self.entries)

    def search(self, query: str) -> tuple[SkillCard, ...]:
        query_norm = query.strip().lower()
        if not query_norm:
            return ()
        scored: list[tuple[int, SkillEntry]] = []
        for entry in self.entries:
            score = entry.match_score(query_norm)
            if score > 0:
                scored.append((score, entry))
        scored.sort(key=lambda item: (-item[0], item[1].name))
        return tuple(SkillCard(name=e.name, description=e.description) for _, e in scored)

    def read(self, name: str) -> str:
        entry = next((e for e in self.entries if e.name == name), None)
        if entry is None:
            raise SkillNotFoundError(f"Skill '{name}' not found")
        text = entry.path.read_text(encoding="utf-8")
        _, body = parse_skill_markdown(text)
        if len(body.encode("utf-8")) > MAX_SKILL_SIZE:
            raise SkillOversizeError(
                f"Skill '{name}' body exceeds maximum size of {MAX_SKILL_SIZE} bytes"
            )
        return body

    def __bool__(self) -> bool:
        return bool(self.entries)

    def __len__(self) -> int:
        return len(self.entries)


def load_skills(skills_dir: Path | None) -> SkillsCatalog:
    """Discover and validate skills in the skills directory."""
    if skills_dir is None or not skills_dir.is_dir():
        return SkillsCatalog()
    entries: list[SkillEntry] = []
    seen_names: set[str] = set()
    for child in sorted(skills_dir.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        skill_file = child / "SKILL.md"
        if not skill_file.is_file():
            continue
        text = skill_file.read_text(encoding="utf-8")
        frontmatter, _ = parse_skill_markdown(text)
        if frontmatter.name in seen_names:
            raise DuplicateSkillName(f"Duplicate skill name '{frontmatter.name}'")
        seen_names.add(frontmatter.name)
        entries.append(
            SkillEntry(
                name=frontmatter.name,
                description=frontmatter.description,
                path=skill_file,
            )
        )
    entries.sort(key=lambda e: e.name)
    return SkillsCatalog(entries=tuple(entries))


@dataclass
class SkillsCache:
    """Per-session cached skills discovery."""

    _entries: dict[tuple[str, Path | None], SkillsCatalog] = field(default_factory=dict)

    def get_or_discover(
        self,
        session_id: str,
        workspace: WorkspacePaths | None,
    ) -> SkillsCatalog:
        key = (session_id, workspace.skills if workspace else None)
        if key in self._entries:
            return self._entries[key]
        catalog = load_skills(workspace.skills if workspace else None)
        self._entries[key] = catalog
        return catalog
