"""The wheel ships every static file the app serves, and every script is compiled."""

import re
import subprocess
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_SOURCE = ROOT / "src" / "clawhouse" / "api" / "app.py"
FRONTEND = ROOT / "frontend"
STATIC = ROOT / "src" / "clawhouse" / "static"
STATIC_PREFIX = "clawhouse/static/"
IMPORT_SPECIFIER = re.compile(r"""(?:\bfrom\s+|\bimport\s*\(|\bimport\s+)["'](\./[^"']+)["']""")


def _served_static_files() -> set[str]:
    """Every static filename `app.py` hands to a FileResponse, in serve order."""
    source = APP_SOURCE.read_text(encoding="utf-8")
    return set(re.findall(r'STATIC / "([^"]+)"', source))


def _force_include_declared() -> set[str]:
    manifest = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return set(manifest["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"])


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


def test_the_wheel_ships_every_served_static_file(tmp_path: Path) -> None:
    served = _served_static_files()
    shipped = _wheel_static_entries(tmp_path)

    assert served, "no static files are served"
    assert served <= shipped, f"wheel is missing {sorted(served - shipped)}"


def test_force_include_declares_every_served_static_file() -> None:
    assert _force_include_declared() == {
        f"src/clawhouse/static/{name}" for name in _served_static_files()
    }


def test_every_imported_module_is_served_and_shipped() -> None:
    served = _served_static_files()
    declared = _force_include_declared()
    imports = 0

    for name in sorted(served):
        if not name.endswith(".js"):
            continue
        source = (STATIC / name).read_text(encoding="utf-8")
        for specifier in IMPORT_SPECIFIER.findall(source):
            imports += 1
            target = specifier.removeprefix("./")
            assert target in served, f"{name} imports {specifier}, which is not served"
            assert f"src/clawhouse/static/{target}" in declared, (
                f"{name} imports {specifier}, which is not in the wheel force-include"
            )

    assert imports > 0, "no relative imports found in served scripts"


def test_every_served_script_has_a_typescript_source() -> None:
    sources = {path.stem for path in FRONTEND.glob("*.ts") if not path.name.endswith(".test.ts")}
    scripts = sorted(name for name in _served_static_files() if name.endswith(".js"))

    assert scripts, "no served scripts found"
    for script in scripts:
        stem = Path(script).stem
        assert stem in sources, f"{script} has no frontend/{stem}.ts source"
