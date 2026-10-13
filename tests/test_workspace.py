"""Pure platform-agent workspace paths. Resolution does no I/O."""

from pathlib import Path

import pytest

from crabriks.settings import default_agent_root
from crabriks.workspace import UnsafeAgentName, resolve_agent_workspace


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
