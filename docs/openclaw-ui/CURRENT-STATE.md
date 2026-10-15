# Clawhouse frontend — current state (as-is baseline)

Companion to [`SHOTS.md`](SHOTS.md) (OpenClaw visual reference) and
[`SCREENSHOTS.md`](SCREENSHOTS.md). This file records **what the Clawhouse frontend is
today**, with file-and-line evidence, so a follow-up issue can state improvements as
checkable deltas instead of adjectives.

Verified against the working tree on 2026-10-11.

---

## 1. Where the frontend actually lives

| Path | Role | Reality |
| --- | --- | --- |
| `src/clawhouse/api/app.py` | The HTTP layer. Declares every page, asset, and API route. | Single source of truth for routing. |
| `src/clawhouse/static/*.html` | The 5 screens, as 5 standalone HTML documents. | Served directly; no template engine. |
| `src/clawhouse/static/{chat,sessions,new}.js` | Compiled output of `frontend/*.ts`. | `tsc` output (4-space indent, trailing `export {}`). |
| `src/clawhouse/static/{approvals,status}.js` | **Hand-written JavaScript.** | No TypeScript source exists for either; not in any build or lint gate. |
| `frontend/*.ts` + `frontend/tsconfig.json` | Upstream TypeScript sources. | `outDir: "../src/clawhouse/static"`, `files: ["chat.ts", "sessions.ts", "new.ts"]`. |
| `.venv/lib/python3.11/site-packages/clawhouse/static/` | Stale wheel copy. | Contains only `chat.css`, `chat.js`, `index.html` — exactly the three files in `pyproject.toml`'s wheel `force-include`. |

**Two problems fall out of this immediately.**

1. **There is no frontend build step.** `Makefile` targets are `all, help, format, lint,
   test, check, sync, deploy, status, logs` — none compiles TypeScript. `tsc` is reachable
   only by hand via `frontend/tsconfig.json`. `quality.yml` and `.pre-commit-config.yaml`
   are Python-only, so `frontend/*.ts` is type-checked by nothing automatic.
2. **The installed package is missing 8 of the 11 served files.** `app.py` serves
   `chat.js`, `chat.css`, `sessions.js`, `new.js`, `approvals.js`, `status.js` and five
   HTML pages, but the wheel force-includes only three files. Under `databricks.yml`
   (`command: uvicorn clawhouse.api.app:app` with `PYTHONPATH: src`) the synced source tree is
   used and everything resolves — the inconsistency is latent, not live.

---

## 2. Per-screen inventory

All five page routes require a caller; without an `x-forwarded-email` header they return
**401** (`src/clawhouse/api/identity.py`).

| Route | HTML | JS/TS | API calls | Renders | Affordances |
| --- | --- | --- | --- | --- | --- |
| `GET /`, `GET /chat` | `index.html` | `chat.js` ← `frontend/chat.ts` | `GET /api/me`, `/api/models`, `/api/sessions/{id}/transcript`, `POST /api/sessions/{id}/turns` (SSE) | `#who` identity text, `select#model`, `main#log` with `p.bubble.user` / `p.bubble.assistant` / `p.tool`, `p#status` | Enter-to-send (Shift+Enter = newline); model persisted in `sessionStorage`; auto-scroll; all inputs disabled during a turn; `input.focus()` after a turn. Session id resolved `?session=` → `sessionStorage` → `crypto.randomUUID()` |
| `GET /sessions` | `sessions.html` | `sessions.js` ← `sessions.ts` | `GET /api/sessions` (once) | `ul.sessions` → `li.session` (link + `created_at` via `toLocaleString()`) | Click a row → **full page navigation** to `/chat?session={id}` |
| `GET /new` | `new.html` | `new.js` ← `new.ts` | `POST /api/sessions` | Static copy `Agent main · built-in, read-only` + one button | Submit → `location.href = /chat?session={id}` |
| `GET /approvals` | `approvals.html` | `approvals.js` (hand-written) | `GET /api/approvals`, `POST /api/approvals/{id}/approve`, `/deny` | Pending cards (`tool-name`, `pre.args-json`, Approve/Deny) + history rows with `span.status-badge` | Approve/Deny → re-`load()`. **No CSS exists for any of these selectors.** |
| `GET /status` | `status.html` | `status.js` (hand-written) | `GET /api/status` (once) | `dl.status-grid` (user, auth mode, token, workspace, model endpoint, storage), session rows with a run-state badge, `a#log-tail-link` | Link opens Databricks logs in a new tab |

Asset routes: `/chat.css`, `/chat.js`, `/sessions.js`, `/new.js`, `/approvals.js`,
`/status.js` (`src/clawhouse/api/app.py:210–232`).

**Only chat streams.** Transport is `StreamingResponse(..., media_type="text/event-stream")`
with frames `token`, `tool_call`, `tool_result`, `approval_required`, `done`, `error`,
parsed by hand client-side. Sessions, approvals, and status each fetch **once** — no
polling, no refresh.

---

## 3. Design-token surface

The entire design system is `src/clawhouse/static/chat.css`. Its `:root` block
(lines 3–17) is **12 tokens**:

```css
@import url("https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:...&family=IBM+Plex+Sans:...&display=swap");

:root {
  color-scheme: light;
  --bg: #f3efe6;      --ink: #1f1a14;     --muted: #6d645b;
  --line: #e2d9cc;    --chip: #1f1a14;    --chip-ink: #f7f3eb;
  --tool: #efe8dc;    --accent: #9a3412;  --accent-ink: #fff7f2;
  --error: #9f1239;   --shadow: 0 16px 40px rgb(31 26 20 / 6%);
  font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
}
```

**Absent, and this is the point:** no `prefers-color-scheme` (zero occurrences anywhere in
the repo), no `[data-theme]`, no dark palette, no `--accent-hover` / `--accent-subtle`, no
success/warn/info status tokens, no radius scale, no spacing scale, no elevation scale
beyond the single `--shadow`, no `--font-mono` token, no duration/easing tokens, no
z-index tokens, and no focus-ring token (`outline: 2px solid rgb(154 52 18 / 35%)` is
duplicated at lines 196 and 215).

### Hard-coded layout constraints

| Declaration | Line | Consequence |
| --- | --- | --- |
| `.shell { width: min(720px, calc(100% - 32px)); height: 100vh; }` | 35–36 | **One fixed 720 px column.** No rail, no two-pane, no panel host. |
| `.bubble { max-width: 38rem; white-space: pre-wrap; }` | 139–142 | Assistant output is plain text; wrapping is CSS, not a renderer. |
| `textarea { resize: none; }` | 203 | Composer cannot be resized or auto-grown. |
| `body { min-height: 100vh; }` | 25 | — |
| `.empty { margin: 18vh 0 0; }` | 132 | Empty state is vertical-space maths. |

**Radii are literal and unrelated**: `16px 16px 4px` (`:149`) as a bubble tail, then
`8px` (`:165`), `10px` (`:188`, `:310`), `14px` (`:206`, `:225`), `12px` (`:273`), `6px`
(`:318`), `8px` (`:343`).

**Font sizes are literal px**: `11px`, `12px`, `13px`, `14px`, `15px`, `16px` scattered
across 14 declarations. The mono family name is hard-coded twice rather than tokenised.

**Navigation is a full page reload.** Each of the five HTML files repeats the same five
`<a href>` links by hand (e.g. `index.html:14–20`) and each route is a separate document
(`app.py:182–206`).

---

## 4. Capability facts

| Question | Answer | Evidence |
| --- | --- | --- |
| Client-side routing | **None.** One document per route, nav repeats in all 5 HTML files. | `api/app.py:182–206` |
| Session rail / sidebar | **None.** Sessions live on their own page behind a nav link. | `chat.css` has no rail/sidebar selector |
| Session switching | **Full page navigation.** | `sessions.js` sets `location.href` |
| WebSocket / `EventSource` | **None.** Transport is hand-parsed SSE. | zero matches in `static/` |
| SSE streaming | **Chat only.** | `api/app.py` `_stream_turn` |
| Markdown rendering | **None.** Every node is written with `textContent`. | zero `innerHTML` / `marked` matches; `chat.js` `el()` sets `textContent` |
| Syntax highlighting | **None.** | zero matches |
| Auto-resizing composer | **No.** `rows="1"` + `resize: none`, no height logic. | `index.html:29`, `chat.css:203` |
| Abort / cancel a turn | **No.** The only response is disabling inputs. | zero `AbortController` matches |
| Tool-call rendering | One flat `p.tool` string per call/result. **No states, no collapse, no diff** — even though the backend already emits distinct `tool_call` / `tool_result` / `approval_required` / `error` frames. | `chat.js` `renderEntry`, `chat.css:160–172` |
| Dark mode | **No.** `color-scheme: light` at `chat.css:4`. | `prefers-color-scheme` = 0 occurrences |
| Accessibility | `aria-live="polite"` on `#log`; `role="status"` on `#status`; 2 visually-hidden labels. No `aria-busy`, no `aria-label`, no focus management beyond `input.focus()`. | grep of `static/` |
| UI tests | HTML-string and status-code assertions only. **No DOM, snapshot, visual, or a11y tests.** | `tests/test_chat.py`, `test_status.py`, `tests/test_approvals.py` |
| Frontend type-checking | **None automated.** `frontend/*.ts` is not checked by `prek`, ruff, pyright, or CI. | `.pre-commit-config.yaml`, `.github/workflows/quality.yml` |
| First-paint font | `@import`s Google Fonts from the Databricks app origin. | `chat.css:1` |

---

## 5. Gaps that block the OpenClaw look

Each gap is stated as a checkable delta against [`SHOTS.md`](SHOTS.md). Ordered by
leverage.

1. **Replace the five-anchor top nav with a persistent shell and session rail** — one
   global rail, sessions as grouped rows, in-place switching, no document reload.
   *Today:* five HTML documents each repeating `<a href>` links (`index.html:14–20`,
   `api/app.py:182–206`).
2. **Introduce a real token layer** — surfaces, one accent with hover/subtle variants,
   radius/spacing/elevation/type scales, `--font-mono`, focus ring. *Today:* 12 tokens
   (`chat.css:3–17`); radii are literal 6/8/10/12/14/16 px; the mono family is hard-coded.
3. **Make dark the default with a light mode** — `data-theme`/`data-theme-mode`, dark as
   `#0e1015`-class canvas with a stepped surface ladder. *Today:* `color-scheme: light`,
   `--bg: #f3efe6`, zero `prefers-color-scheme`.
4. **Render assistant output as markdown** — headings, lists, tables, blockquotes, code
   blocks with syntax highlighting and copy-to-clipboard. *Today:* `textContent` +
   `white-space: pre-wrap`.
5. **Turn tool activity into real rows with states** — status chip, collapse/expand,
   inputs/outputs, and a one-line human summary; wire up the `tool_call`/`tool_result`/
   `error` distinction the backend already sends. *Today:* one flat `p.tool` string.
6. **Style the Approvals screen.** *Today:* `approval-card`, `approval-header`,
   `btn-approve`, `btn-deny`, `args-json`, `approval-history-row`, `resolver` have **zero**
   CSS rules — the screen renders unstyled. (`.status-badge.running/.idle/.error` *is*
   styled, with literal hex at `chat.css:325–338` — status colors that belong in tokens.)
7. **Give sessions a list worth reading** — titles, relative timestamps, status, sorting,
   filtering, and transcript search. *Today:* `ul.sessions` → link + `toLocaleString()`.
8. **Rebuild the New-session screen as an empty-state hero + composer** — agent identity,
   one-line instruction, context pickers above the composer, primary action as the only
   saturated element. *Today:* a static caption and one button.
9. **Add an abort control for a running turn.** *Today:* no `AbortController`; the only
   signal is disabled inputs.
10. **Auto-grow the composer and put the toolbar inside it** — attach, permission pill,
    model pill, reasoning pill, send. *Today:* `rows="1"`, `resize: none`, a separate
    `select` in a `.model-row` above the textarea.
11. **Give loading, empty, and error states a real treatment** — a skeleton primitive,
    per-region empty states, inline errors. *Today:* one italic line and a `p#status`.
12. **Fix the build and the wheel** — add a `tsc` build to the Makefile and CI, move
    `approvals`/`status` into the TS pipeline, and make the wheel `force-include` match
    what `app.py` actually serves. *Today:* 8 of 11 files are outside the build and the
    package.
13. **Drop the third-party font import from the critical path.** *Today:* `chat.css:1`
    requests Google Fonts from the app origin on first paint.

---

## 6. Where the code contradicts ADR-0004

1. **"FastAPI serves 5 TS views"** — only **3** TS views exist. `approvals.js` and
   `status.js` are hand-written and absent from `tsconfig.json`'s `files`. The runtime
   serves 5 HTML + 6 JS routes, not 5 TS views.
2. **"Approvals — pending tool approvals + history"** — the screen exists structurally but
   ships with **zero CSS selectors**, so it renders unstyled; the ADR reads as if a screen
   were delivered.
3. **"Frontend ticket builds 5 screens only"** — true of routes, but two of the five sit
   outside the TS build *and* outside every lint/type gate, so the stated build discipline
   covers 3 of 5.
4. **Chat screen scope** ("streaming + tool-call display + error states") — **matches**;
   all three are implemented.
5. **Status screen scope** ("connection/auth snapshot + run status + log tail link") —
   **matches**.
6. **Route names** — the ADR names `/chat`, `/sessions`, `/new`, `/approvals`, `/status`;
   the code additionally aliases `/` to chat (`api/app.py:182–183`) and passes session
   selection as `?session=` rather than a route parameter.

---

## 7. Not verified

- Whether the deployed workspace copy currently matches `src/clawhouse/static/`
  (`Makefile sync` excludes `frontend/`, so an uncompiled TS change drifts silently).
- The exact rendered appearance of the Approvals screen, given it has no matching CSS —
  inferable only by rendering it.
- Whether `chat.css`'s Google Fonts `@import` resolves under the Databricks Apps egress
  policy.
- No "before" screenshots were captured for this document: every page route is gated by
  `_require_caller` (401 without `x-forwarded-email`) and booting the real app needs
  Lakebase via `open_store()`. Capturing them needs a Playwright run with the `/api/*`
  routes stubbed.
