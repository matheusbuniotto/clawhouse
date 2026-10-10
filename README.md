# Crabriks

## Development Setup

This project uses [uv](https://github.com/astral-sh/uv) and [prek](https://github.com/j178/prek) (Rust-powered Git hook manager).

### 1. Environment Setup

```bash
# Pin and install Python 3.11 with all dev dependencies
uv sync
```

### 2. Git Hooks & Quality Gate (`prek`)

Git hook shims are installed using `prek`:

```bash
# Install git hooks into .git/hooks/pre-commit
prek install

# Run checks against staged files (runs automatically on git commit)
prek run

# Run checks on all files
prek run -a
```

> **Fallback:** If `prek` is not installed globally, you can also run `uv run pre-commit run -a`.

### 3. Manual Checks

```bash
# Fast lint & format auto-fix
uv run ruff check --fix .
uv run ruff format .

# Cognitive complexity gate
uv run complexipy src -c 15

# Type check
uv run pyright
```
