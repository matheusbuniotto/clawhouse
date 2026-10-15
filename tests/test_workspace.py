"""Pure platform-agent workspace paths. Resolution does no I/O."""

from pathlib import Path

import pytest

from clawhouse.capabilities.workspace import (
    UnsafeAgentName,
    provision_agent_workspace,
    resolve_agent_workspace,
)
from clawhouse.settings import default_agent_root


def test_a_safe_name_composes_the_platform_layout() -> None:
    paths = resolve_agent_workspace(Path("/data/platform"), "main")

    directory = Path("/data/platform/claw/agents/main")
    assert paths.directory == directory
    assert paths.agents == directory / "AGENTS.md"
    assert paths.soul == directory / "SOUL.md"
    assert paths.identity == directory / "IDENTITY.md"
    assert paths.user_file == directory / "USER.md"
    assert paths.memory == directory / "MEMORY.md"
    assert paths.memory_dir == directory / "memory"
    assert paths.skills == directory / "skills"
    assert paths.context == directory / "context"
    assert paths.context_file == directory / "CONTEXT.md"
    assert paths.workspace_dir == directory / "workspace"


@pytest.mark.parametrize(
    "name",
    [
        "",
        ".",
        "..",
        "../main",
        "main/../secret",
        "a/b",
        "a\\b",
        "/etc/passwd",
        "main\x00",
        " main",
        "main ",
        "a" * 65,
        "foo.bar",
        "..\\..\\windows",
    ],
)
def test_unsafe_names_are_rejected_and_not_normalized(name: str) -> None:
    with pytest.raises(UnsafeAgentName):
        resolve_agent_workspace(Path("/data/platform"), name)


def test_resolution_creates_nothing_and_does_not_resolve_dotdot(tmp_path: Path) -> None:
    root = tmp_path / "workspace" / ".." / "secret"
    before = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))

    paths = resolve_agent_workspace(root, "platform-main")

    after = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))
    assert after == before
    assert paths.directory == root / "claw" / "agents" / "platform-main"
    assert ".." in paths.directory.parts
    assert not paths.directory.exists()
    assert not paths.agents.exists()


def test_the_default_root_holds_the_shipped_agent_folder() -> None:
    paths = resolve_agent_workspace(default_agent_root(), "main")

    assert paths.agents.is_file()
    assert paths.soul.is_file()
    assert paths.identity.is_file()
    assert paths.user_file.is_file()
    assert paths.memory.is_file()


def test_a_relative_root_stays_relative() -> None:
    paths = resolve_agent_workspace(Path("platform"), "agent_1")

    assert paths.agents == Path("platform/claw/agents/agent_1/AGENTS.md")
    assert paths.agents.is_absolute() is False


def test_provision_agent_workspace_creates_directory_and_files(tmp_path: Path) -> None:
    paths = provision_agent_workspace(
        root=tmp_path,
        agent_name="data_analyst",
        agents_text="You analyze tables.\n",
        identity_name="Data Analyst",
        signature_emoji="📊",
        soul_text="Be analytical.\n",
        context_text="Project Alpha context.\n",
    )

    assert paths.directory.is_dir()
    assert paths.workspace_dir.is_dir()
    assert paths.skills.is_dir()
    assert paths.agents.read_text(encoding="utf-8") == "You analyze tables.\n"
    assert paths.identity.read_text(encoding="utf-8") == "Name: Data Analyst\nEmoji: 📊\n"
    assert paths.soul.read_text(encoding="utf-8") == "Be analytical.\n"
    assert paths.context_file.read_text(encoding="utf-8") == "Project Alpha context.\n"


def test_provision_agent_workspace_optional_soul_and_context(tmp_path: Path) -> None:
    paths = provision_agent_workspace(
        root=tmp_path,
        agent_name="minimal_bot",
        agents_text="Minimal rules.\n",
        identity_name="Minimal Bot",
    )

    assert paths.directory.is_dir()
    assert paths.workspace_dir.is_dir()
    assert paths.agents.is_file()
    assert paths.identity.is_file()
    assert not paths.soul.exists()
    assert not paths.context_file.exists()
