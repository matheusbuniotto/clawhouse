# OpenClaw Quickwins

## Problem

Users interacting with Clawhouse face friction in four routine chat interactions that break the fast, fluid terminal-like experience promised by the OpenClaw design:
1. Users have to remember and type out raw slash commands by hand; while `@agent` mentions autocomplete, typing `/` shows no palette even though the backend already supports slash suggestions.
2. During active streaming or long turn outputs, any user attempt to scroll up to review previous tables or instructions is aggressively clobbered by automatic scroll-to-bottom on every incoming token, with no quick button to jump back down.
3. Users inspecting analytical outputs and generated code must manually drag-select prose to copy assistant answers or SQL blocks into notebooks, tickets, or editors.
4. Switching between sessions or pages clears unsent composer text, causing users to lose typed prompts and drafted instructions.

When this ships, typing `/` displays an immediate suggestions palette, scrolling up during a turn pauses auto-scroll and reveals a floating return-to-bottom button (`↓`), assistant turns offer a one-click copy markdown action, and composer drafts persist seamlessly per session.

## Flow

This feature wires existing backend suggestion endpoints and standard browser storage/DOM primitives without introducing new network protocols or backend dependencies.

1. `Composer input` -> `frontend/mentions.ts` (exists) - detects trigger char (`/` or `@`) and queries `/api/composer/suggestions`
2. `Suggestions list` -> `frontend/chat.ts` (exists) - renders popover, binds arrow keys/Tab/Enter, and inserts `/command` into textarea
3. `User scroll in transcript` -> `frontend/chat.ts` (exists) - detects scroll up, pauses auto-scroll, toggles floating `button#scroll-bottom`
4. `Assistant turn rendered` -> `frontend/transcript.ts` (exists) - appends action bar with copy icon; clicks write raw text to `navigator.clipboard`
5. `Textarea input change` -> `frontend/chat.ts` (exists) - caches active draft to `sessionStorage` under `clawhouse.draft.<session_id>`

## Impact

| Front | What changes |
| --- | --- |
| domain | new term: `SlashCommand` - a prefixed command token (`/jobs`, `/schedule`, `/compact`, `/model`, `/reset`) matching backend capabilities |
| domain | existing term: `Suggestion` - previously represented agent/mention options, now also represents slash command suggestions in `mentions.ts` |
| stored data | nothing to migrate; drafts stored in browser-local ephemeral `sessionStorage` |

## Relations

None - no stored-data shape change

## Surface

None - nothing consumed outside (consumes existing `GET /api/composer/suggestions?type=/` endpoint)

## Landing

| One-way door | Literal shape | Alternative rejected |
| --- | --- | --- |
| Composer trigger parsing | `/(?:^|\s)([/@])([^\s]*)$/` | Dedicated separate `/` input component; rejected because it fragments composer single-surface UX |
| Ephemeral draft storage key | `clawhouse.draft.<session_id>` | Single global draft key; rejected because switching sessions would overwrite other session drafts |

- Nothing else in this change is hard to reverse

## Criteria

### S1: Slash Commands in Composer (P1)

Typing `/` in the composer reveals slash commands from the backend with keyboard navigation and insertion.

**Acceptance Criteria**

1. WHEN the user types `/` at the beginning of the composer or following whitespace THEN the system SHALL fetch suggestions from `GET /api/composer/suggestions?type=/` and display the suggestions popover.
2. WHILE the suggestions popover is visible WHEN the user presses ArrowDown or ArrowUp THEN the system SHALL move the active selection highlight.
3. WHILE the suggestions popover is visible WHEN the user presses Enter or Tab THEN the system SHALL insert the selected command into the composer and close the popover.
4. WHILE the suggestions popover is visible WHEN the user presses Escape or clicks outside THEN the system SHALL close the popover.
5. IF the network request for suggestions fails THEN the system SHALL hide the popover without disabling composer input.

**Independent test:** Open chat, type `/` in the empty composer, verify the dropdown lists `/compact`, `/jobs`, `/schedule`, `/model`, `/reset`, navigate with arrows, press Tab, and verify `/compact ` is inserted.

### S2: Scroll Interrupt & Floating Return-to-Bottom (P1)

Scrolling up during turn reading or streaming preserves scroll position and shows a floating jump button.

**Acceptance Criteria**

6. WHILE a turn is streaming tokens IF the user scrolls up past 80 pixels from the bottom THEN the system SHALL pause auto-scrolling to the bottom.
7. WHILE the transcript scroll position is more than 80 pixels above the bottom THEN the system SHALL display a floating circular `button#scroll-bottom` with a down-arrow icon.
8. WHEN the user clicks `button#scroll-bottom` THEN the system SHALL smooth-scroll to the bottom of the transcript and hide the button.
9. WHEN the transcript reaches within 40 pixels of the bottom THEN the system SHALL hide `button#scroll-bottom` and resume auto-scroll on new incoming tokens.

**Independent test:** Generate or load a long transcript, scroll up 200px, verify the `↓` floating button appears, trigger a streaming turn, verify scroll position does not jump, click the button, and verify the transcript scrolls to bottom.

### S3: Assistant Message Copy Action (P1)

Assistant turns provide a one-click action to copy the full markdown message to the clipboard.

**Acceptance Criteria**

10. The system SHALL render an action toolbar containing a copy button on every assistant turn.
11. WHEN the user clicks the copy button on an assistant turn THEN the system SHALL write the assistant turn's full markdown content to `navigator.clipboard`.
12. WHEN markdown content is copied THEN the system SHALL display visual confirmation text ("Copied!") on the button for 2 seconds before reverting to the default icon.
13. IF `navigator.clipboard.writeText` rejects THEN the system SHALL display error feedback ("Failed to copy") without throwing an unhandled exception.

**Independent test:** Render an assistant message, hover over the message to view the copy button, click it, verify clipboard contains the raw markdown text, and verify "Copied!" feedback is displayed.

### S4: Composer Draft Persistence (P1)

Unsent message drafts survive session switches and page reloads.

**Acceptance Criteria**

14. WHEN the user modifies the composer textarea THEN the system SHALL save the current text to `sessionStorage` under `clawhouse.draft.<session_id>`.
15. WHEN a session is mounted or switched THEN the system SHALL populate the composer textarea with any draft saved for that session ID.
16. WHEN the composer form is submitted successfully THEN the system SHALL remove the saved draft for that session ID from `sessionStorage`.

**Independent test:** Type "Review quarterly revenue" in session A, navigate to session B, verify composer is blank or shows session B's draft, navigate back to session A, verify "Review quarterly revenue" is restored in the textarea, submit the message, and verify `sessionStorage` no longer contains the draft.

## Out of scope

| Excluded | Why |
| --- | --- |
| Full 2-pane swappable right panel | Multi-screen architecture change requiring separate design slice |
| DBSQL table grid component | Rich tabular renderer with CSV export belongs in its own dedicated data slice |
| Mermaid diagram rendering pipeline | Requires bundle integration of mermaid library and layout isolation |

## Assumptions

| Assumption | Chosen default | Rationale | Confirmed? |
| --- | --- | --- | --- |
| Suggestion popover styling | Reuses existing `@` mention popover layout and classes | Consistent look and feel across composer triggers | y |
| Scroll threshold distance | 80px from bottom | Standard tolerance to prevent small bounce scrolls from accidentally pausing streaming | y |

**Open questions:** none - all resolved or logged above.

## Observable

| Surface | Decision | Landing |
| --- | --- | --- |
| screen `chat` | empty composer state with slash suggestions | AC 1 |
| screen `chat` | suggestions network failure | AC 5 |
| screen `chat` | floating scroll button visibility & animation | AC 7, AC 8, AC 9 |
| screen `chat` | copy button states (idle, hover, copied, error) | AC 10, AC 12, AC 13 |
| screen `chat` | draft recovery upon session navigation | AC 15 |

## Sources

- `docs/openclaw-DESIGN.md` - OpenClaw architecture and UI inventory
- `docs/openclaw-ui/SHOTS.md` §2, §3, §4 - Visual references for composer toolbar, draft indicators, scroll affordances, and hover actions
