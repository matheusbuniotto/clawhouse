# Intent: Data Estate Intelligence (permissions, lineage, impact, run failures)

Status: intent (not a plan; no code yet)
Source ranking: `docs/clawhouse-vs-openclaw.md` §4 item 2 (Databricks-only; the strongest "obvious
choice" hook).

## Problem

A data team's hardest questions are about the estate, not the syntax: "who can read this table?",
"what jobs and dashboards depend on it?", "is it safe to drop this column?", "why did the 4am run
fail and what else did it break?". Clawhouse can list catalogs, describe a table, run SQL, and
inspect a Job run (`src/clawhouse/capabilities/databricks.py` L336–438, L439–899), but it cannot read
Unity Catalog grants, lineage, audit, or `system.*` tables — so the agent guesses or stops at
"describe table". OpenClaw has no catalog, lineage, audit, or billing source at all
(`docs/tools/index.md` lists no such tools).

## Who feels it

The analytics engineer before a schema change; the on-call data engineer at 04:15; the platform lead
doing an access review; the analyst who cannot tell whether a number changed because of a job or a
permission. These are the moments where a data team decides whether an assistant is trustworthy.

## What "done" looks like

- From chat, "who can read `main.sales.orders`?" returns the effective grantees (users/groups, with
  the privilege kind) scoped to what the caller is allowed to see, with the source (UC grants /
  `system.access`/`information_schema`) named.
- "What depends on this table?" returns upstream/downstream lineage (tables, jobs, dashboards) and a
  plain-language impact summary ("dropping `region` breaks 3 jobs and 1 dashboard").
- "Why did run `12345` fail?" returns the failing task, error, duration, and the downstream assets
  affected, with a link to the run and the relevant logs.
- Every answer is read-only and respect the caller's own visibility; the agent must say "I can't see
  that" rather than infer.
- A denied or partial read degrades to an explicit "unverified" answer, never a confident guess.

## Why Databricks wins (and OpenClaw cannot follow)

This is not a parity feature — OpenClaw has no equivalent. Unity Catalog grants and lineage,
`system.access.audit`, `system.access.table_lineage`, `system.lakeflow`, and
`system.billing` are governed, first-party sources. Clawhouse already has the UC client and the OBO
identity (`capabilities/databricks.py`; `api/identity.py`), and the Jobs screen already reads job
ACLs (`capabilities/jobs.py`). The work is adding the read paths and a reasoning surface, not
building a data catalog.

## Open questions (resolve in the plan, not here)

- Which `system.*` tables are available to the app's service principal vs. only to the user token?
- Lineage freshness/cost trade-off: query live on demand vs. cache a snapshot in Lakebase.
- How to present partial visibility honestly (redact vs. "not visible to you").
- Should this reuse the existing `dbsql_query`/Jobs tools or add dedicated read tools?
