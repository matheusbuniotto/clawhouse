"""Platform skill library, read by harness Skills without a model-visible filesystem."""

from pathlib import Path

from pydantic_ai.workspaces import LocalWorkspaceBackend
from pydantic_ai_harness import Skills


def skills_capability(skills_dir: Path | None) -> Skills | None:
    """Offer the library for this turn, or nothing when the directory is absent."""
    if skills_dir is None or not skills_dir.is_dir():
        return None
    return Skills(".", workspace=LocalWorkspaceBackend(skills_dir))


def loaded_skill_text(content: object) -> str | None:
    """The skill body a `load_capability` result carries, when this value is one."""
    if not isinstance(content, dict):
        return None
    instructions = content.get("instructions")
    if isinstance(instructions, str):
        return instructions
    return None
