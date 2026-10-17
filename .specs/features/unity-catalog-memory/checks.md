# Unity Catalog Memory checks

Profile: light
Plan: `.specs/features/unity-catalog-memory/plan.md`

20 checks in 2 slices · 3 one-way doors · 0 open, of which 0 block

## Checks

### S1 - Search past sessions · 2 files · 56 KB · ~14k

**C1** - `GET /api/search?q=refunds&limit=2` returns `200` and at most 2 results, each with `session_id`, `role`, `excerpt` of at most 240 characters, and `created_at`, ordered newest first (AC 1)
Proof: `uv run pytest tests/test_memory_api.py::test_search_returns_at_most_limit_newest_first -q`

**C2** - `GET /api/search` returns only entries whose session `owner_id` equals the caller (AC 2)
Proof: `uv run pytest tests/test_memory_api.py::test_search_excludes_other_owners -q`

**C3** - `GET /api/search?q=` and `GET /api/search?q=%20` each return `422` (AC 3)
Proof: `uv run pytest tests/test_memory_api.py::test_search_empty_q_returns_422 -q`

**C4** - `GET /api/search` with no match returns `200` and `results` `[]` (AC 4)
Proof: `uv run pytest tests/test_memory_api.py::test_search_no_match_returns_empty_results -q`

**C5** - A Sessions search input of 2 or more characters requests `GET /api/search` and replaces the session list with the returned rows (AC 5)
Proof: `npx vitest run frontend/sessions.test.ts -t "search of 2 characters replaces the session list"`

**C6** - A failed `GET /api/search` shows an inline error and leaves the previous session list in the DOM (AC 6)
Proof: `npx vitest run frontend/sessions.test.ts -t "search failure keeps the previous list"`

**C7** - `GET /api/search`, `GET /api/memory`, `POST /api/memory`, and `DELETE /api/memory/{memory_id}` each return `401` when the caller has no identity
Proof: `uv run pytest tests/test_memory_api.py::test_memory_routes_without_identity_return_401 -q`

### S2 - Durable cited memory · 4 files · 106 KB · ~27k

**C8** - `POST /api/memory` with `text`, `source_session_id`, and `table_fqn` returns `201` and a body with `id`, `text`, and `created_at`, and the stored row has that `owner_id` (AC 7)
Proof: `uv run pytest tests/test_memory_api.py::test_post_memory_returns_201_and_persists_owner -q`

**C9** - `POST /api/memory` whose `source_session_id` is not owned by the caller returns `404` (AC 8)
Proof: `uv run pytest tests/test_memory_api.py::test_post_memory_foreign_session_returns_404 -q`

**C10** - `POST /api/memory` with missing or blank `text` returns `422`
Proof: `uv run pytest tests/test_memory_api.py::test_post_memory_blank_text_returns_422 -q`

**C11** - `DELETE /api/memory/{memory_id}` for an owned row returns `204`, and a later `GET /api/memory` does not include that `id` (AC 9)
Proof: `uv run pytest tests/test_memory_api.py::test_delete_owned_memory_returns_204_and_omits_it -q`

**C12** - `DELETE /api/memory/{memory_id}` for an unknown or other-owner id returns `404`
Proof: `uv run pytest tests/test_memory_api.py::test_delete_missing_memory_returns_404 -q`

**C13** - `GET /api/memory` returns `200` and only entries whose `owner_id` equals the caller, each with `id`, `text`, `table_fqn`, `source_session_id`, and `created_at`
Proof: `uv run pytest tests/test_memory_api.py::test_get_memory_returns_only_caller_entries -q`

**C14** - A turn injects at most 5 memory entries, ordered by `ts_rank` then `created_at` descending, totaling at most 2000 characters, each line prefixed with its `id` and `created_at` (AC 10)
Proof: `uv run pytest tests/test_memory_prompt.py::test_turn_injects_at_most_5_entries_and_2000_chars -q`

**C15** - The injected block contains no entry whose `owner_id` differs from the caller (AC 11)
Proof: `uv run pytest tests/test_memory_prompt.py::test_turn_injection_excludes_other_owners -q`

**C16** - `recall` returns a JSON array of at most 5 objects, each with `id`, `text`, `table_fqn`, `source_session_id`, and `created_at` (AC 12)
Proof: `uv run pytest tests/test_memory_tools.py::test_recall_returns_at_most_5_with_citation_fields -q`

**C17** - `remember(text, table_fqn)` persists one row for the caller and returns that row's `id` (AC 13)
Proof: `uv run pytest tests/test_memory_tools.py::test_remember_persists_caller_row_and_returns_id -q`

**C18** - A completed turn that does not call `remember` and does not `POST /api/memory` inserts 0 rows into `memory_entries`
Proof: `uv run pytest tests/test_memory_tools.py::test_turn_without_remember_writes_zero_memory_rows -q`

**C19** - Lakebase open creates `clawhouse.memory_entries` with `id`, `owner_id`, `text`, `source_session_id`, `table_fqn`, and `created_at`, and `transcript_search_idx` as a GIN index on `to_tsvector('english', content)`
Proof: `uv run pytest tests/test_memory_lakebase.py::test_memory_entries_and_transcript_search_idx -q`

**C20** - A Lakebase FTS query for a term returns the matching transcript entry and returns no row owned by another `owner_id`
Proof: `uv run pytest tests/test_memory_lakebase.py::test_fts_returns_owner_match_only -q`

## Coverage

| Set (size) | Member -> proof | Unproven |
| --- | --- | --- |
| `GET /api/search` statuses (3) | `200` C1 · `401` C7 · `422` C3 | - |
| `GET /api/memory` statuses (2) | `200` C13 · `401` C7 | - |
| `POST /api/memory` statuses (4) | `201` C8 · `401` C7 · `404` C9 · `422` C10 | - |
| `DELETE /api/memory/{memory_id}` statuses (3) | `204` C11 · `401` C7 · `404` C12 | - |
| Landing doors (3) | `clawhouse.memory_entries` columns C19 · `transcript_search_idx` GIN C19 · explicit writes only C17 | - |
| Relations (3) | `Owner` owns entries C13 · `MemoryEntry` C8 · nullable `source_session_id` constrained to an owned `Session` C9 | - |
| search result fields (4) | `session_id` C1 · `role` C1 · `excerpt` C1 · `created_at` C1 | - |
| injection bounds (3) | 5 entries C14 · 2000 characters C14 · `id` and `created_at` prefix C14 | - |
| memory tools (2) | `recall` C16 · `remember` C17 | - |
| sessions screen states (2) | list replaced C5 · inline error keeps previous list C6 | - |
| startup schema (2) | Lakebase open C19 · in-memory `SessionStore` used by `tests/test_memory_api.py` C8 | - |
| silent write (1) | turn without `remember` inserts 0 rows C18 | - |

- Claims naming a status code or route: C1, C3, C4, C7, C8, C9, C10, C11, C12, C13 — each proof crosses that route
- No other check claims more than the single case its proof exercises

## Swept

- validation: C3, C10
- failure modes: C6, C9, C12
- idempotency: n/a - duplicate `text` is allowed; `id` disambiguates
- authorization: C2, C7, C15
- concurrency: n/a - no shared mutable ranking state; each request reads committed rows
- data lifecycle: C11, C19
- dependency failure: C6
- state transitions: n/a - a memory row is inserted or deleted; it has no status machine
- observability: n/a - no logging requirement in this plan

## Handoff

- S1 = 14k, in `api/app.py` and `static/sessions.js`; S2 adds `store/store.py`, `store/shapes.py`, `capabilities/mentions.py`, and `agent/turn.py` at 41k total, under the 150k budget — one builder
- **Boundary:** C1–C20 closed in the memory commit
- **Settled mid-build:** in-memory rank is term frequency then `created_at`; Lakebase rank is `ts_rank`
- **Abandoned:** none
