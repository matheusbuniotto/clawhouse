---
name: databricks-sdk
description: Build Databricks-backed Python (FastAPI backend). Invoke for WorkspaceClient usage, warehouse SQL execution, Unity Catalog calls, serving endpoints, jobs, and per-request user-token auth. The SDK is a project dependency.
---

# Databricks SDK

Official Python SDK, pinned in `pyproject.toml`. Source of truth is the installed package (`uv run python -c "help(databricks.sdk)"`) and https://docs.databricks.com/dev-tools/sdk-python.html.

## Client

```python
from databricks.sdk import WorkspaceClient
w = WorkspaceClient()  # auth from env/CLI profile/keyring, same as the CLI
```

## Frequent surfaces for this project

- `w.statement_execution.execute_statement(...)` — SQL on a warehouse (MVP query tool)
- `w.catalogs`, `w.schemas`, `w.tables`, `w.functions` — Unity Catalog lookup
- `w.jobs` — trigger notebook/job runs
- `w.serving_endpoints` — model serving (OpenAI-compatible chat completions)
- Per-request user tokens (Databricks Apps forward `x-forwarded-access-token`): construct the client with that token per request so Unity Catalog grants follow the caller, never a shared identity.

## Rules

- One shared client for app-level calls; one per-request client for user-scoped calls.
- Never log tokens or embed them in tool descriptions and errors.
- `databricks-ai-bridge` (Genie, vector search) is out of v1 scope; reach for it only when a ticket names Genie or vector search.
