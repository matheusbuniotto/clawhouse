"""Read the platform agent's bootstrap files. Missing files are markers."""

from dataclasses import dataclass
from pathlib import Path

from crabriks.capabilities.workspace import WorkspacePaths

_NOTICE = "Bootstrap context was truncated to fit the budget."
_TOTAL_CAP = 20_000
# Total overflow gives these up in order. AGENTS.md is never reduced further.
_OVERFLOW = ("MEMORY.md", "USER.md", "IDENTITY.md", "SOUL.md")


@dataclass(frozen=True, slots=True)
class BootstrapFile:
    name: str
    text: str
    missing: bool = False


@dataclass(frozen=True, slots=True)
class BootstrapContext:
    """The five bootstrap files in fixed order, plus at most one truncation notice."""

    files: tuple[BootstrapFile, ...]
    notice: str | None


def load_bootstrap(
    paths: WorkspacePaths,
    *,
    user_directives: str | None = None,
) -> BootstrapContext:
    """Read the bootstrap files. A missing file yields a marker, not an exception."""
    files: list[BootstrapFile] = []
    truncated = False
    for name, path, limit in _sources(paths):
        text, cut, missing = _read(path, name, limit)
        if name == "CONTEXT.md" and missing:
            continue
        if name == "USER.md" and user_directives:
            if missing:
                missing = False
                text = user_directives[:limit]
                cut = len(user_directives) > limit
            else:
                combined = f"{text}\n\n{user_directives}".strip()
                cut = cut or (len(combined) > limit)
                text = combined[:limit]
        files.append(BootstrapFile(name=name, text=text, missing=missing))
        truncated = truncated or cut
    fitted, cut_more = _fit_total(tuple(files))
    if truncated or cut_more:
        return BootstrapContext(files=fitted, notice=_NOTICE)
    return BootstrapContext(files=fitted, notice=None)


def load_bootstrap_directives(user_directives: str) -> BootstrapContext:
    """Build a bootstrap context when only user directives are provided."""
    limit = 4_000
    text = user_directives[:limit]
    cut = len(user_directives) > limit
    files = (
        BootstrapFile(name="AGENTS.md", text="[MISSING] AGENTS.md", missing=True),
        BootstrapFile(name="SOUL.md", text="[MISSING] SOUL.md", missing=True),
        BootstrapFile(name="IDENTITY.md", text="[MISSING] IDENTITY.md", missing=True),
        BootstrapFile(name="USER.md", text=text, missing=False),
        BootstrapFile(name="MEMORY.md", text="[MISSING] MEMORY.md", missing=True),
    )
    fitted, cut_more = _fit_total(files)
    if cut or cut_more:
        return BootstrapContext(files=fitted, notice=_NOTICE)
    return BootstrapContext(files=fitted, notice=None)


def _sources(paths: WorkspacePaths) -> tuple[tuple[str, Path, int], ...]:
    return (
        ("AGENTS.md", paths.agents, 8_000),
        ("SOUL.md", paths.soul, 4_000),
        ("IDENTITY.md", paths.identity, 4_000),
        ("USER.md", paths.user_file, 4_000),
        ("MEMORY.md", paths.memory, 8_000),
        ("CONTEXT.md", paths.context_file, 8_000),
    )


def _fit_total(files: tuple[BootstrapFile, ...]) -> tuple[tuple[BootstrapFile, ...], bool]:
    texts = {item.name: item.text for item in files}
    protected = {item.name for item in files if item.missing}
    truncated = False
    for name in _OVERFLOW:
        extra = sum(len(text) for text in texts.values()) - _TOTAL_CAP
        if extra <= 0:
            break
        if name in protected:
            continue
        shortened = _shorten(texts[name], extra)
        if shortened == texts[name]:
            continue
        texts[name] = shortened
        truncated = True
    fitted = tuple(
        BootstrapFile(name=item.name, text=texts[item.name], missing=item.missing) for item in files
    )
    return fitted, truncated


def _shorten(text: str, extra: int) -> str:
    keep = len(text) - extra
    if keep <= 0:
        return ""
    return text[:keep]


def _read(path: Path, name: str, limit: int) -> tuple[str, bool, bool]:
    try:
        with path.open(encoding="utf-8") as handle:
            text = handle.read(limit + 1)
    except FileNotFoundError:
        return f"[MISSING] {name}", False, True
    if len(text) > limit:
        return text[:limit], True, False
    return text, False, False
