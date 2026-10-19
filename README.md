# Clawhouse for Databricks 🦀

> **OpenClaw-style AI assistant for your Lakehouse.** Runs as a Databricks App, acts as *you* through Unity Catalog, and asks before it touches anything. Built on **Pydantic AI**, **Lakebase Postgres**, and **Model Serving**.

> [!NOTE]
> Clawhouse for Databricks is an independent open-source project. It is **not affiliated** with clawhouse.com / Clawhouse LLC (a managed OpenClaw hosting service), OpenClaw, or Databricks.

---

## Quickstart

```bash
uv sync
CLAWHOUSE_DEV_USER=you@example.com \
CLAWHOUSE_STORE=memory \
uv run uvicorn clawhouse.api.app:app --reload
```

Open **`http://localhost:8000/chat`**.

> Provide `DATABRICKS_HOST`, `DATABRICKS_TOKEN`, and `SERVING_ENDPOINT` (or `CLAWHOUSE_MODELS`) to run live turns locally.

---

## Architecture

```text
src/clawhouse/
├── agent/         # Turn execution, @agent roster, command dispatch, prompt & history
├── capabilities/  # Databricks (UC/SQL/Jobs), Sheets, MCP, skills, ask_user & progress
├── api/           # FastAPI routes, SSE turn streaming, unified /api/jobs, SSO identity
├── store/         # Lakebase Postgres (OAuth) & in-memory session/transcript/schedule store
└── settings.py    # Environment configuration
```

---

## Core Capabilities

- **Per-Message `@agent` Routing**: Mention `@agent` in any message to route the turn to that agent's persona, workspace (`claw/agents/<name>/`), and skills while sharing conversation history.
- **Interactive Turn Cards**:
  - **`ask_user`**: Pauses the run and renders an inline question card with option buttons (headless scheduled runs automatically select `default`).
  - **`report_progress`**: Streams and updates a single in-place step checklist per `task_id`.
  - **Tool Approvals**: Sensitive tools (`jobs_*`, `sheets_*`, `delivery_*`, and `CLAWHOUSE_SENSITIVE_TOOLS`) pause the run for inline `[Approve]` / `[Deny]` confirmation or resolution in `/approvals`.
- **Unified Jobs (`/jobs`)**: Lists in-app cron schedules and Databricks Lakeflow Jobs visible to the caller (via OBO token or workspace ACL fallback), with **Run now**, schedule deletion, and links to run transcripts.
- **Composer Commands & Context**:
  - Slash commands: `/compact`, `/clear`, `/schedule <cron> | <prompt>`, `/skill:<name>`.
  - Context mentions: `@catalog.schema.table` (Unity Catalog schema), `@file:<path>`, `@agent` autocomplete.
  - Context-window ring indicator tracking sent input tokens.
- **Databricks & MCP Tools**: Unity Catalog discovery, read-only DBSQL queries, Lakeflow Jobs (`sql`, `agentic` via `ai_query`, `python`), Google Sheets (`system.ai.google_drive`), Slack/webhook delivery, and external HTTPS MCP servers with token scrubbing.

---

## Configuration

| Variable | Purpose |
| :--- | :--- |
| `SERVING_ENDPOINT` | Default Databricks Model Serving endpoint name |
| `LAKEBASE_ENDPOINT` | Lakebase Autoscaling resource key (omit or set `CLAWHOUSE_STORE=memory` locally) |
| `DATABRICKS_WAREHOUSE_ID` | SQL Warehouse ID for DBSQL queries and SQL/agentic job tasks |
| `CLAWHOUSE_MODELS` | JSON list of extra OpenAI-compatible model entries (`id`, `label`, `model`, `base_url`, `api_key_env`, `default`) |
| `CLAWHOUSE_MCP_SERVERS` | JSON list of HTTPS MCP servers (`name`, `url`, `timeout_seconds`) |
| `CLAWHOUSE_SENSITIVE_TOOLS` | Comma-separated list or JSON array of tool names requiring interactive approval |
| `CLAWHOUSE_DEV_USER` | Local dev identity fallback when `X-Forwarded-Email` is absent |

Example `CLAWHOUSE_MODELS`:

```bash
export CLAWHOUSE_MODELS='[
  {
    "id": "openai-gpt-6-luna",
    "label": "GPT-6 Luna (OpenRouter)",
    "model": "openai/gpt-6-luna",
    "base_url": "https://openrouter.ai/api/v1",
    "api_key_env": "OPENROUTER_API_KEY",
    "default": true
  }
]'
export OPENROUTER_API_KEY=sk-or-...
```

---

## Deploy

Direct sync and deploy to Databricks Apps:

```bash
make deploy
```

Or deploy via Databricks Asset Bundles (DAB):

```bash
databricks bundle deploy --profile <PROFILE>
```

---

## Quality Gates

```bash
make check           # Runs prek (ruff, complexipy, pyright), pytest, tsc, build check, and vitest
```

Individual checks:

```bash
uv run ruff check --fix . && uv run ruff format .
uv run complexipy src --max-complexity-allowed 15
uv run pyright
uv run vulture src --min-confidence 80
npx jscpd@5 src --threshold 3 --min-lines 5 --min-tokens 50
uv run pytest
npm test
```
