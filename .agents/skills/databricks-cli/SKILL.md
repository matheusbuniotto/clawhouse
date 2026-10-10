---
name: databricks-cli
description: Operate the Databricks workspace from the shell. Invoke for warehouse SQL, Unity Catalog lookup, jobs, apps, Lakebase, or any workspace operation available in the CLI. Auth comes from CLI profiles (OAuth/keyring), never pasted tokens.
---

# Databricks CLI

Official CLI, already authenticated here (`databricks auth describe` shows the workspace). Source of truth is the CLI itself, not this file.

## Discover

```bash
databricks --help            # top-level groups
databricks <group> --help    # e.g. warehouses, catalog, jobs, apps, auth
```

## Frequent groups for this project

- `databricks warehouses` — list/get SQL warehouses (MVP query target)
- `databricks catalog` — Unity Catalog lookup (catalogs, schemas, tables, functions)
- `databricks jobs` — trigger and watch notebook/job runs
- `databricks apps` — deploy and manage the Databricks App
- `databricks sql` — execute SQL directly
- `databricks auth describe` — confirm who/where you are authenticated

## Rules

- Auth lives in CLI profiles and the OS keyring. Pass tokens only via env (`DATABRICKS_TOKEN`) when a command needs an explicit override.
- Confirm the workspace (`auth describe`) before any write, deploy, or trigger.
- Destructive operations (delete, reset, overwrite) need explicit human confirmation first.
