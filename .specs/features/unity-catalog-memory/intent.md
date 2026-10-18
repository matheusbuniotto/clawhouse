# Intent: Unity Catalog Memory & Recall

Status: intent (not a plan; no code yet)
Source ranking: `docs/clawhouse-vs-openclaw.md` §3 rows 2–3 (F5 × A5 / F5 × A4).

## Problem

A data team's most repeated conversation is context: "revenue on that table is net of refunds",
"the nightly job owns the partition", "we tried that join in March and it duplicated rows". Clawhouse
forgets all of it. `MEMORY.md` is read once into the system prompt (`src/clawhouse/capabilities/bootstrap.py`,
`agent/prompt.py` L126–143) and is platform-owned, not user- or team-writable (ADR-0005). There is no
memory search and no transcript search: `store/store.py` exposes create/list/rename/delete/clear
(L189–201) but no search, and `api/app.py` has no search route. OpenClaw has both a memory subsystem
and `sessions_search` (`docs/concepts/memory.md`, `docs/concepts/session-search.md`).

## Who feels it

The analyst who re-explains the same schema every week; the engineer returning to a session from a
month ago; the team lead who wants the agent's accumulated table knowledge to survive a person
leaving. The platform owner wants it to be *correct and governed*, not a model hallucinating
definitions.

## What "done" looks like

- The user can ask "what do we know about `main.sales.orders`?" and get a cited answer assembled from
  past accepted turns and Unity Catalog metadata (comment, columns, lineage), with links back to the
  source session/table.
- The user can search past sessions by phrase and reopen the exact turn; results respect session
  ownership (only the caller's sessions).
- Memory is written deliberately (an explicit save/confirm action or an approved tool call), not
  silently; the user can inspect, correct, and delete an entry.
- Memory entries carry provenance (session id, table, author, timestamp) and can be re-validated
  against current UC metadata; stale entries are marked, not asserted.
- The prompt stays cache-stable: memory is injected as a bounded, recency-ranked suffix, never as an
  unbounded dump into the prefix.

## Why Databricks wins (and OpenClaw cannot follow)

OpenClaw's memory is Markdown in a local workspace (`docs/concepts/memory.md`) with no catalog. Here,
Unity Catalog is a live source of truth: table comments, columns, tags, and lineage can seed and
verify memory, and Lakebase is already the session/transcript store (`docs/adr/0002-lakebase-workspace-storage.md`;
`store/store.py`). The differentiator is **governed, table-grounded recall**, not a generic vector
store.

## Open questions (resolve in the plan, not here)

- Lexical (Postgres FTS) vs. vector (pgvector) vs. hybrid retrieval on Lakebase — one-way door.
- Is memory per-user, per-agent, or per-team? ADR-0005 deliberately deferred per-user roots.
- What is the write path: a tool with approval, an explicit UI action, or both?
- How much UC metadata is refreshed vs. cached, and who pays for the calls?
