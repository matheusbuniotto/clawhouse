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
uv run complexipy src --max-complexity-allowed 15

# Type check
uv run pyright
```

### 4. Run the chat page

```bash
CRABRIKS_DEV_USER=you@example.com CRABRIKS_STORE=memory \
  uv run uvicorn crabriks.app:app --reload
```

The page is at <http://localhost:8000/chat>. A turn needs a Databricks user token and a serving endpoint. Forward the token as `X-Forwarded-Access-Token`, or set `DATABRICKS_TOKEN` when the caller is `CRABRIKS_DEV_USER`. Also set `SERVING_ENDPOINT` and `DATABRICKS_HOST`. Without them the page loads, and a turn returns 401 or 503.

On Databricks Apps, `app.yaml` names the serving endpoint and the Lakebase Autoscaling endpoint. The platform injects `PGHOST`, `PGUSER`, `PGDATABASE`, `PGPORT`, and `PGSSLMODE`. The app mints a short-lived database password from `LAKEBASE_ENDPOINT`. Do not set `CRABRIKS_DEV_USER` or `DATABRICKS_TOKEN` on the deployed app.
