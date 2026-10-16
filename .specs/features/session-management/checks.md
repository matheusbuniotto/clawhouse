# Session Management Checks

Profile: light
Plan: `.specs/features/session-management/plan.md`

22 checks in 4 slices · 3 one-way doors · 0 open, of which 0 block

## Checks

Grouped by the spec's slices; numbering runs across the whole feature.

### S1 - Session Metadata & Renaming Backend API · 3 files · 97 KB · ~24k

**C1** - Valid PATCH /api/sessions/{session_id} updates title in store and returns 200 with updated SessionOut (AC 1) · done
Proof: `uv run pytest tests/test_chat.py -k test_rename_session_success`

**C2** - PATCH /api/sessions/{session_id} with empty or whitespace-only title returns 422 (AC 2) · done
Proof: `uv run pytest tests/test_chat.py -k test_rename_session_blank_refused`

**C3** - PATCH /api/sessions/{session_id} for session owned by another user returns 403 (AC 3) · done
Proof: `uv run pytest tests/test_chat.py -k test_rename_session_forbidden`

**C4** - PATCH /api/sessions/{session_id} for non-existent session UUID returns 404 (AC 4) · done
Proof: `uv run pytest tests/test_chat.py -k test_rename_session_not_found`

**C5** - GET /api/sessions/{session_id} returns 200 with SessionOut for an existing owned session (AC 5) · done
Proof: `uv run pytest tests/test_chat.py -k test_get_session_success`

**C6** - GET /api/sessions/{session_id} returns 403 when accessed by another user (AC 5) · done
Proof: `uv run pytest tests/test_chat.py -k test_get_session_forbidden`

**C7** - GET /api/sessions/{session_id} returns 404 for a non-existent session UUID (AC 5) · done
Proof: `uv run pytest tests/test_chat.py -k test_get_session_not_found`

**C8** - GET /api/sessions/{session_id} returns 422 for a non-UUID session identifier (AC 5) · done
Proof: `uv run pytest tests/test_chat.py -k test_get_session_invalid_id`

**C9** - POST /api/sessions/{session_id}/clear deletes all transcript entries and returns 200 with cleared flag (AC 6) · done
Proof: `uv run pytest tests/test_chat.py -k test_clear_session_transcript_success`

**C10** - POST /api/sessions/{session_id}/clear returns 403 when called by another user (AC 6) · done
Proof: `uv run pytest tests/test_chat.py -k test_clear_session_transcript_forbidden`

**C11** - POST /api/sessions/{session_id}/clear returns 404 for non-existent session UUID (AC 6) · done
Proof: `uv run pytest tests/test_chat.py -k test_clear_session_transcript_not_found`

**C12** - POST /api/sessions/{session_id}/clear returns 422 for a non-UUID session identifier (AC 6) · done
Proof: `uv run pytest tests/test_chat.py -k test_clear_session_transcript_invalid_id`

**C13** - Session title resolution prioritizes custom title over first user entry, falling back to empty string (AC 7) · done
Proof: `uv run pytest tests/test_chat.py -k test_session_title_fallback_order`

### S2 - Chat Pane Header with Inline Rename & Reset · 1 file · 33 KB · ~8k

**C14** - Chat screen mounts sticky header element #chat-header displaying active session title or fallback (AC 8) · done
Proof: `npm test frontend/chat.test.ts -t "renders chat header with session title"`

**C15** - Clicking rename in #chat-header replaces title text with pre-populated input #chat-title-input (AC 9) · done
Proof: `npm test frontend/chat.test.ts -t "displays inline title input on rename click"`

**C16** - Submitting #chat-title-input sends PATCH request, updates header text, and fires clawhouse:session-renamed (AC 10) · done
Proof: `npm test frontend/chat.test.ts -t "saves new session title and dispatches renamed event"`

**C17** - Pressing Escape in #chat-title-input cancels edit mode without dispatching network request (AC 11) · done
Proof: `npm test frontend/chat.test.ts -t "cancels title edit on Escape key"`

**C18** - Confirming clear transcript in #chat-header calls POST clear endpoint and purges entries from #log (AC 12) · done
Proof: `npm test frontend/chat.test.ts -t "clears transcript after confirmation"`

### S3 - Sidebar Rail Inline Rename Action · 1 file · 11 KB · ~3k

**C19** - Sidebar rail renders .rail-session-rename button on each row and saves title via PATCH on Enter (AC 13, AC 14)
Proof: `npm test frontend/shell.test.ts -t "renames session in rail"`

**C20** - Receiving clawhouse:session-renamed event updates matching .rail-session-title in-place (AC 15)
Proof: `npm test frontend/shell.test.ts -t "updates rail session title on renamed event"`

### S4 - Enhanced Sessions Management Screen · 1 file · 2 KB · ~1k

**C21** - Sessions page renders #sessions-search and #sessions-count, dynamically filtering list on input (AC 16, AC 17)
Proof: `npm test frontend/sessions.test.ts -t "filters sessions list and updates counter"`

**C22** - Sessions page renders rename and clear buttons on each row, executing in-place updates (AC 18, AC 19, AC 20)
Proof: `npm test frontend/sessions.test.ts -t "executes inline rename and clear actions on sessions page"`

## Coverage

| Set (size) | Member -> proof | Unproven |
| --- | --- | --- |
| `PATCH /api/sessions/{session_id}` statuses (4) | `200` C1 · `403` C3 · `404` C4 · `422` C2 | - |
| `GET /api/sessions/{session_id}` statuses (4) | `200` C5 · `403` C6 · `404` C7 · `422` C8 | - |
| `POST /api/sessions/{session_id}/clear` statuses (4) | `200` C9 · `403` C10 · `404` C11 · `422` C12 | - |
| session title resolution order (3) | `custom` C1 · `first-user-message` C13 · `empty-fallback` C14 | - |
| chat header title edit keys (2) | `Enter` C16 · `Escape` C17 | - |
| session touchpoints for rename (3) | `chat-header` C16 · `sidebar-rail` C19 · `sessions-page` C22 | - |

- Claims naming a status code, route or response shape: C1, C2, C3, C4, C5, C6, C7, C8, C9, C10, C11, C12 - each has a proof that crosses the boundary
- No other check claims more than the single case its proof exercises

## Swept

Where each unwritten requirement landed. All nine, one line each, every time.

- validation: C2, C8, C12
- failure modes: C3, C4, C6, C7, C10, C11
- idempotency: C1, C9
- authorization: existing - _require_caller validates identity and session ownership in app.py
- concurrency: C1
- data lifecycle: C9
- dependency failure: n/a - no third-party external dependencies, uses local Lakebase or in-memory store
- state transitions: C1, C9
- observability: n/a - no new telemetry metrics required for basic session CRUD

## Handoff

Total size: 6 files · 143 KB · ~36k tokens.
Under the 150k budget — one builder, no ask.
Mechanism: one builder.
