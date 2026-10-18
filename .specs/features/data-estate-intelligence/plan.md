# Data Estate Intelligence

## Problem

A data team's hardest questions are about the estate, not the syntax: "who can read this table?",
"what depends on it?", "is it safe to drop this column?", "why did the 4am run fail?".
Clawhouse can list catalogs, describe a table, run SQL, and inspect a Job run
(`src/clawhouse/capabilities/databricks.py` L336–438, L439–899), but it cannot read Unity Catalog
grants, lineage, or attach a failure to the tables it feeds. OpenClaw has no first-party catalog,
lineage, or audit tool (`docs/tools/index.md` lists none). Evidence:
`.specs/features/data-estate-intelligence/intent.md`; `docs/clawhouse-vs-openclaw.md` §4 item 2.

When this ships, a user asks who can read a table, what feeds it, what it feeds, and why a run
failed, and gets a cited, caller-scoped answer in chat.

## Flow

This reuses the existing Unity Catalog client, the DBSQL executor, and the run inspectors instead of
adding a catalog service or a lineage store.

1. user turn -> `clawhouse.agent.turn` (exists) wires `DatabricksCapability` (exists)
2. `clawhouse.capabilities.databricks.DatabricksTools` (exists) gains `uc_list_grants`,
   `uc_table_lineage`, `uc_column_lineage`, and `job_run_failure`
3. grants call `client.grants.get_effective(...)` on the forwarded client; lineage runs the
   same statement-execution API as `dbsql_query` on that client, never `_call`, against
   `system.access.table_lineage` and `system.access.column_lineage`; failure analysis calls
   `jobs.get_run` on the forwarded client (the existing run inspectors stay for other tools)
4. out: tool results -> existing `tool_result` SSE frame (`api/app.py` L1375) -> transcript
   renderer

## Impact

| Front | What changes |
| --- | --- |
| domain | new term: Estate read - a read that must use the caller's identity and fail closed; lives in `capabilities/databricks.py` |
| domain | existing term: `_call` ambient fallback - estate tools opt out; who branches today: every `DatabricksTools._call` caller |
| stored data | nothing to migrate - every answer is queried live |
| dependency | none new - `databricks-sdk` `GrantsAPI` and the existing DBSQL path |

## Relations

`None - no stored-data shape change`

## Surface

`None - nothing consumed outside` (tool calls flow through the existing
`/api/sessions/{id}/turns` SSE route).

## Landing

| One-way door | Literal shape | Alternative rejected |
| --- | --- | --- |
| Estate reads fail closed | each estate tool calls the forwarded `WorkspaceClient` directly, never `_call`; when `user_token == ""` or the call raises a permission error it returns `{"error": "not visible to you"}` | reuse `_call`'s ambient fallback - would disclose metadata the caller cannot see (ADR-0009) |
| Lineage source | SQL `FROM system.access.table_lineage WHERE source_table_full_name = :fqn OR target_table_full_name = :fqn` | infer lineage from job source or a manual mapping - incomplete and unverifiable |
| Grants source | `client.grants.get_effective(securable_type="table", full_name=<fqn>)`, returning `principal`, `privileges`, and inherited entries | `information_schema` only - misses group inheritance and non-table securables |

- Nothing else in this change is hard to reverse.

## Criteria

Grouped by slice - one observable outcome each, never a layer.

### S1: Permissions (P1)

A user can ask who can read a table and get the effective grantees.

**Acceptance Criteria**

1. WHEN the model calls `uc_list_grants(full_name)` THEN the system SHALL return a list of `{principal, privilege, inherited}` from `grants.get_effective` and SHALL include the securable `full_name`.
2. IF the caller cannot see the securable THEN the system SHALL return `{"error": "not visible to you"}` and SHALL NOT return an empty list.
3. The system SHALL resolve grants with the forwarded user token and SHALL NOT call the ambient `WorkspaceClient`.
4. IF `full_name` does not contain exactly two dots THEN the system SHALL return `{"error": "full_name must be catalog.schema.table"}`.

### S2: Lineage and impact (P1)

A user can ask what feeds a table and what it feeds, at table and column level.

**Acceptance Criteria**

5. WHEN the model calls `uc_table_lineage(full_name)` THEN the system SHALL return `upstream` and `downstream` arrays of `{table, last_seen}` from `system.access.table_lineage`.
6. WHEN the model calls `uc_column_lineage(full_name, column)` THEN the system SHALL return `upstream` and `downstream` arrays of `{table, column, last_seen}` from `system.access.column_lineage`.
7. IF lineage returns no rows THEN the system SHALL return `{"table": <fqn>, "upstream": [], "downstream": [], "note": "no lineage found"}`.
8. The system SHALL cap each lineage direction at 50 distinct tables ordered by `last_seen` descending.

### S3: Run failure (P2)

A user can ask why a run failed and get the failing task and its error.

**Acceptance Criteria**

9. WHEN the model calls `job_run_failure(run_id)` THEN the system SHALL return `run_id`, `life_cycle_state`, `result_state`, `state_message`, `duration_ms`, and `run_page_url`.
10. WHEN the run has failed tasks THEN the system SHALL return each failed task's `task_key`, `result_state`, and `state_message`.
11. IF the run is still running THEN the system SHALL return `life_cycle_state` and SHALL NOT label it a failure.

**Independent test:** stub `grants.get_effective`, `statement_execution.execute_statement`, and
`jobs.get_run`; assert every tool's success, permission-error, empty-lineage, and still-running
responses.

## Out of scope

Product capabilities only.

| Excluded | Why |
| --- | --- |
| Audit log (`system.access.audit`) | separate read surface; this slice is grants + lineage + failure |
| Billing (`system.billing`) | separate capability and ranking (cost ledger) |
| Dashboard / AI-BI discovery | needs the AI/BI API, not table lineage |
| Job and dashboard impact beyond table lineage | table lineage does not carry those entities reliably |
| Caching or snapshots | live reads first; caching is a reversible follow-up |
| Remediation or grant changes | read-only capability |
| PII classification | not a lineage read |

## Assumptions

| Assumption | Chosen default | Rationale | Confirmed? |
| --- | --- | --- | --- |
| Impact scope | upstream/downstream tables and columns only | `system.access.table_lineage` carries tables; jobs/dashboards need another source | n |
| Freshness | live query per call, no cache | no staleness contract to design yet | n |
| Grants view | `get_effective` (includes inheritance) | answers "who can read", not "what was granted directly" | n |
| Result cap | 50 distinct tables per direction | bounds the transcript while covering normal estates | n |
| Full-name validation | require `catalog.schema.table` | prevents ambiguous two-part names from reaching UC | n |

**Open questions:** none - all resolved or logged above.

## Observable

Worksheet, not the review. `n/a` needs its reason.

| Surface | Decision | Landing |
| --- | --- | --- |
| tool `uc_list_grants` | output shape | AC 1 |
| tool `uc_list_grants` | error and unauthorised shape | AC 2, 4 |
| tool `uc_table_lineage` | output shape | AC 5 |
| tool `uc_table_lineage` | empty state | AC 7 |
| tool `uc_column_lineage` | output shape | AC 6 |
| tool `job_run_failure` | output shape | AC 9, 10 |
| tool `job_run_failure` | non-failure state | AC 11 |
| all estate tools | rate limits | n/a - DBSQL and Unity Catalog enforce platform limits |
| screen `chat` | error state | existing - tool-result renderer shows the error text |

## Sources

- `.specs/features/data-estate-intelligence/intent.md` - problem, who, done
- `docs/clawhouse-vs-openclaw.md` §4 item 2 - Databricks-only advantage
- `.agents/skills/databricks-unity-catalog/references/5-system-tables.md` L198–330 - lineage schema
- `src/clawhouse/capabilities/databricks.py` - existing UC/DBSQL/Jobs reuse
- `docs/adr/0009-user-code-execution-identity.md` - fail-closed reads
