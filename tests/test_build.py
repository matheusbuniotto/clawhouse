"""The wheel ships every static file the app serves."""

import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "src" / "clawhouse" / "static"
STATIC_PREFIX = "clawhouse/static/"


def _local_static_files() -> set[str]:
    return {
        str(path.relative_to(STATIC)).replace("\\", "/")
        for path in STATIC.rglob("*")
        if path.is_file()
    }


def _wheel_static_entries(tmp_path: Path) -> set[str]:
    result = subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(tmp_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    wheel = next(tmp_path.glob("*.whl"))
    with zipfile.ZipFile(wheel) as archive:
        return {
            name.removeprefix(STATIC_PREFIX)
            for name in archive.namelist()
            if name.startswith(STATIC_PREFIX)
        }


def test_the_wheel_ships_every_committed_static_file(tmp_path: Path) -> None:
    local = _local_static_files()
    shipped = _wheel_static_entries(tmp_path)

    assert local, "no static files under src/clawhouse/static"
    assert local <= shipped, f"wheel is missing {sorted(local - shipped)}"


def test_spa_shell_is_present() -> None:
    assert (STATIC / "index.html").is_file()
    assert (STATIC / "assets").is_dir()
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert "/assets/" in html
    assert "Clawhouse" in html


def test_ast_limits_in_src() -> None:
    script = ROOT / "scripts" / "check_ast_limits.py"
    result = subprocess.run(
        [__import__("sys").executable, str(script)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"AST checks failed:\n{result.stderr}\n{result.stdout}"
