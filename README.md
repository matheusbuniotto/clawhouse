# Crabriks 🦀

> Databricks-native agent runtime & chat app powered by **Pydantic AI**, **Lakebase Postgres**, and **Model Serving**.

---

## Architecture

Crabriks is organized into clean domain boundaries with zero circular dependencies:

```
src/crabriks/
├── agent/         # Reasoning engine, prompt composition, turn execution, models
├── capabilities/  # Tools, skill catalogs (SKILL.md), Model Context Protocol (MCP)
├── api/           # FastAPI chat endpoints, SSE streaming, Databricks SSO identity
├── store/         # Lakebase Postgres (OAuth-authenticated) & in-memory session store
└── settings.py    # Environment configuration & typed settings
```

---

## Quickstart

### 1. Install dependencies
```bash
uv sync
```

### 2. Run locally
```bash
CRABRIKS_DEV_USER=you@example.com \
CRABRIKS_STORE=memory \
uv run uvicorn crabriks.app:app --reload
```
Open **`http://localhost:8000/chat`**.

> **Note**: To execute turns locally, provide `DATABRICKS_HOST`, `DATABRICKS_TOKEN`, and `SERVING_ENDPOINT`.

---

## Features

- **Databricks Native**: Deploys as a Databricks App with SSO reverse-proxy header auth (`X-Forwarded-Access-Token`).
- **Lakebase Storage**: Sessions, transcripts, and run locks persist in managed Lakebase Postgres with auto-minted OAuth tokens.
- **Multi-Model Picker**: Defaults to Databricks Model Serving; supports any OpenAI-compatible provider (OpenRouter, local gateways).
- **Tool Capabilities**:
  - **Skills**: Discover and run markdown-based skills (`claw/agents/main/skills/*/SKILL.md`).
  - **MCP**: Connect to Model Context Protocol HTTP endpoints with automatic secret scrubbing.
  - **Approvals & Guardrails**: Pause sensitive tool calls for interactive approval before execution.

---

## Model Providers

Add external OpenAI-compatible endpoints via `CRABRIKS_MODELS`:

```bash
export CRABRIKS_MODELS='[
  {
    "id": "openrouter-llama-3.3-70b",
    "label": "Llama 3.3 70B (OpenRouter)",
    "model": "meta-llama/llama-3.3-70b-instruct",
    "base_url": "https://openrouter.ai/api/v1",
    "api_key_env": "OPENROUTER_API_KEY"
  }
]'
export OPENROUTER_API_KEY=sk-or-...
```

---

## Sensitive Tool Guardrails

Protect destructive or privileged tools with interactive user approvals:

```bash
export CRABRIKS_SENSITIVE_TOOLS="bash,delete_file,drop_table"
```

Pending approvals freeze the run and appear in the UI approvals inbox (`/approvals`).

---

## Deploy to Databricks

Deploy as a Databricks Asset Bundle (DAB):

```bash
databricks bundle deploy --profile <PROFILE> \
  --var serving_endpoint=databricks-meta-llama-3-3-70b-instruct \
  --var postgres_branch=projects/crabriks/branches/production \
  --var postgres_database=projects/crabriks/branches/production/databases/databricks-postgres
```

---

## Quality Gates

Crabriks enforces zero-warning code quality across all files:

```bash
prek run -a          # Fast staged / all-file checks (ruff, complexipy, pyright)
uv run pytest        # Run test suite
```

Manual checks:
```bash
uv run ruff check --fix . && uv run ruff format .
uv run complexipy src --max-complexity-allowed 15
uv run pyright
uv run vulture src --min-confidence 80
npx jscpd@5 src --threshold 3 --min-lines 5 --min-tokens 50
```
