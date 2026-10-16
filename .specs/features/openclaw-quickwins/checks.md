# OpenClaw Quickwins checks

Profile: light
Plan: `.specs/features/openclaw-quickwins/plan.md`

16 checks in 4 slices · 2 one-way doors · 0 open, of which 0 block

## Checks

Grouped by the spec's slices; numbering runs across the whole feature.

### S1 - Slash Commands in Composer · 4 files · 35 KB · ~8k

**C1** - Typing '/' at start of input or after space fetches slash suggestions from GET /api/composer/suggestions?type=/ (AC 1)
Proof: `npm test frontend/chat.test.ts -t "slash command triggers popover"`

**C2** - ArrowDown and ArrowUp move the active highlighted suggestion in the popover (AC 2)
Proof: `npm test frontend/chat.test.ts -t "slash command keyboard navigation"`

**C3** - Enter or Tab inserts the selected slash command and closes popover (AC 3)
Proof: `npm test frontend/chat.test.ts -t "slash command selection inserts command"`

**C4** - Escape or click outside closes the slash suggestion popover (AC 4)
Proof: `npm test frontend/chat.test.ts -t "slash command popover dismiss"`

**C5** - Suggestions fetch failure hides popover without blocking composer typing (AC 5)
Proof: `npm test frontend/chat.test.ts -t "slash command network error handled gracefully"`

### S2 - Scroll Interrupt & Floating Return-to-Bottom · 3 files · 45 KB · ~6k

**C6** - Scrolling up >80px from bottom pauses auto-scroll during token streaming (AC 6)
Proof: `npm test frontend/chat.test.ts -t "scrolling up pauses auto-scroll"`

**C7** - Floating button#scroll-bottom is visible when transcript is >80px above bottom (AC 7)
Proof: `npm test frontend/chat.test.ts -t "floating scroll button appears when scrolled up"`

**C8** - Clicking button#scroll-bottom scrolls to bottom of transcript (AC 8)
Proof: `npm test frontend/chat.test.ts -t "clicking scroll button returns to bottom"`

**C9** - Reaching within 40px of bottom hides button#scroll-bottom and resumes auto-scroll (AC 9)
Proof: `npm test frontend/chat.test.ts -t "reaching bottom resumes auto-scroll"`

### S3 - Assistant Message Copy Action · 3 files · 38 KB · ~6k

**C10** - Every assistant turn renders an action bar with a copy markdown button (AC 10)
Proof: `npm test frontend/transcript.test.ts -t "renders assistant copy action button"`

**C11** - Clicking copy button writes raw assistant markdown text to navigator.clipboard (AC 11)
Proof: `npm test frontend/transcript.test.ts -t "clicking copy button writes to clipboard"`

**C12** - Successful copy displays 'Copied!' feedback for 2 seconds (AC 12)
Proof: `npm test frontend/transcript.test.ts -t "displays copied confirmation text"`

**C13** - Clipboard rejection shows error state without throwing unhandled rejection (AC 13)
Proof: `npm test frontend/transcript.test.ts -t "handles clipboard rejection gracefully"`

### S4 - Composer Draft Persistence · 2 files · 32 KB · ~4k

**C14** - Input in composer textarea saves draft to sessionStorage under clawhouse.draft.<session_id> (AC 14)
Proof: `npm test frontend/chat.test.ts -t "composer saves draft to sessionStorage"`

**C15** - Mounting chat restores saved draft for the active session ID (AC 15)
Proof: `npm test frontend/chat.test.ts -t "chat restores draft on mount"`

**C16** - Submitting composer clears the saved draft for that session ID (AC 16)
Proof: `npm test frontend/chat.test.ts -t "submitting form clears saved draft"`

## Coverage

| Set (size) | Member -> proof | Unproven |
| --- | --- | --- |
| slash suggestion trigger positions (2) | `start-of-input` C1 · `after-whitespace` C1 | - |
| suggestion popover keyboard events (4) | `ArrowDown` C2 · `ArrowUp` C2 · `Enter` C3 · `Escape` C4 | - |
| scroll position states (2) | `within-40px-bottom` C9 · `over-80px-above-bottom` C6 | - |
| copy action feedback states (2) | `copied-success` C12 · `clipboard-rejection` C13 | - |
| draft storage lifecycle (2) | `saved-on-input` C14 · `cleared-on-submit` C16 | - |

- No check claims more than the single case its proof exercises

## Swept

- validation: C1
- failure modes: C5
- idempotency: C16
- authorization: existing - caller authenticated via ambient session
- concurrency: C6
- data lifecycle: C14, C16
- dependency failure: C13
- state transitions: C7, C9
- observability: n/a - client-side interaction state without telemetry

## Handoff

S1-S4 = 24k total, well under the 150k budget - one builder, no ask needed.

- **Boundary:** C1-C16 closed
- **Settled mid-build:** Immediate local default slash suggestions before remote fetch eliminates popover delay; defensive guard against empty models response.
- **Abandoned:** None
