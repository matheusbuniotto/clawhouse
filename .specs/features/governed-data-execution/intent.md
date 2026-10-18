# Intent: Governed Data Execution

Status: intent (not a plan; no code yet)
Source ranking: `docs/clawhouse-vs-openclaw.md` §3 row 1 (F5 × A5).

## Problem

Clawhouse can query with `dbsql_query` and orchestrate Lakeflow Jobs, but it cannot run code the way
a data engineer actually works: read a governed table into pandas, validate assumptions, join two
sources, or prototype Spark before promoting it. Today the only escapes are SQL through
`uc_describe_table`/`dbsql_query` (`src/clawhouse/capabilities/databricks.py` L336–438) or an
indirect `jobs_create` round-trip — both round-trips lose the ad-hoc, inspect-the-result loop that
makes an agent useful. OpenClaw's answer is a local `exec`/sandbox (`docs/tools/exec.md`,
`docs/gateway/sandboxing.md`), which cannot touch Unity Catalog under the user's identity.

## Who feels it

The data engineer or analyst in the chat: "load orders, drop nulls, show me rows by region" is
currently a dead end unless they already wrote the SQL. The platform owner feels it too, because the
safe alternative — giving the agent a shell — is exactly what they do not want on a governed
platform.

## What "done" looks like

- From chat, the user can ask for a Python/Spark analysis over a Unity Catalog table and get real
  output (rows, summary, a chart-ready table) back in the transcript.
- Execution runs on Databricks compute (serverless or an existing cluster) **as the requesting
  user's forwarded OBO identity**, never as a shared ambient credential, with UC grants enforced by
  Databricks rather than by Clawhouse path mapping.
- The same capability is reachable from a scheduled or Job-triggered turn, so a prototype can be
  promoted to a recurring analysis without rewriting it.
- Failures and timeouts are first-class transcript events (a failed run card with the Databricks
  error), not a silence or an HTTP 500.
- Every execution's user, workspace, compute, and statement id are recorded so the status/telemetry
  surfaces can attribute it.

## Why Databricks wins (and OpenClaw cannot follow)

OpenClaw's sandbox is a local container/SSH target; it has no Unity Catalog, no OBO identity, and no
serverless compute. Clawhouse already holds the OBO token and an ambient fallback (`api/identity.py`;
`databricks.py` L328–347) and already creates Jobs. The moat is not "run code" — it is "run code
governed, as the right user, on the data platform."

## Open questions (resolve in the plan, not here)

- Serverless vs. warehouse vs. jobs-compute-with-`spark_python_task` — which is the one-way door?
- How does this relate to the existing `jobs_create(task_type="python")` path?
- What is the approval story for destructive code (writes, `DROP`, external egress)?
