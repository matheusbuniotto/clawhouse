#!/usr/bin/env python3
"""AST-based quality gate verifying file and function line count limits."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

MAX_FILE_LINES = 400
MAX_FUNCTION_LINES = 50


def check_file(path: Path) -> list[str]:
    violations: list[str] = []
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"{path}: failed to read: {exc}"]

    lines = len(content.splitlines())
    if lines > MAX_FILE_LINES:
        violations.append(
            f"{path}: file length {lines} lines exceeds maximum allowed {MAX_FILE_LINES} lines"
        )

    try:
        tree = ast.parse(content, filename=str(path))
    except SyntaxError as exc:
        return [*violations, f"{path}: syntax error: {exc}"]

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            end = getattr(node, "end_lineno", node.lineno)
            func_len = end - node.lineno + 1
            if func_len > MAX_FUNCTION_LINES:
                violations.append(
                    f"{path}:{node.lineno}: function '{node.name}' length {func_len} lines "
                    f"exceeds maximum allowed {MAX_FUNCTION_LINES} lines"
                )

    return violations


def main() -> int:
    files = [Path(arg) for arg in sys.argv[1:] if arg.endswith(".py")]
    if not files:
        src = Path("src")
        if not src.exists():
            sys.stderr.write("Error: src directory not found\n")
            return 1
        files = sorted(src.rglob("*.py"))

    all_violations: list[str] = []
    for file_path in files:
        if file_path.is_file() and "src" in file_path.parts:
            all_violations.extend(check_file(file_path))

    if all_violations:
        sys.stderr.write("AST limit checks failed:\n")
        for v in all_violations:
            sys.stderr.write(f"  - {v}\n")
        return 1

    sys.stdout.write(
        f"AST limit checks passed ({len(files)} files checked; "
        f"all <= {MAX_FILE_LINES} lines, functions <= {MAX_FUNCTION_LINES} lines).\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
