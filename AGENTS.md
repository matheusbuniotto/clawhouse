# Crabriks — DatabricksClaw MVP

Databricks-native port of OpenClaw ideas as a Databricks App: one chat surface, one Python agent runtime, Databricks identity and storage throughout.

## Stack

- Backend FastAPI, frontend TypeScript/HTML served by the App. See `docs/adr/0001-fastapi-typescript-ui.md`.
- Sessions/transcripts in Lakebase; agent personal files in the user workspace. See `docs/adr/0002-lakebase-workspace-storage.md`.
- Agent runtime Pydantic AI (core + Harness + Evals). See `docs/adr/0003-pydantic-ai.md`.
- UI v1 is 5 screens: chat, sessions, new session, approvals, status. See `docs/adr/0004-ui-v1-5-screens.md`.
- OpenClaw reference inventory: `docs/openclaw-DESIGN.md` + `docs/openclaw-ui/SCREENSHOTS.md`.

## Work loop

```bash
uv sync            # Python 3.11 env + dev deps
prek install       # one-time: git hooks
prek run           # staged-file gates (auto on commit)
prek run -a        # all files
```

Manual equivalents when prek is unavailable:

```bash
uv run ruff check --fix . && uv run ruff format .
uv run complexipy src -c 15
uv run pyright
```

CI (`quality.yml`) runs ruff, complexipy, pyright, vulture, jscpd on push/PR to main. Keep `main` green: small commits, gates passing locally first.

## Patterns

- Pure resolvers first: path/context composition does no I/O; stores hide behind injected dependencies.
- Typed boundaries: frozen dataclasses for cross-module shapes (`WorkspacePaths`, prompt results, turn results).
- One test seam: `run_turn(session_id, user_message) -> TurnResult` at the chat entrypoint covers composition, tools, and persistence. Drop to `build_system_prompt` assertions only for ordering/cache-stability.
- External behavior in tests, never internals; exact expected values over adjectives.
- Issues carry behavior and acceptance criteria, never file paths or code snippets (they rot).
- Vertical slices: each ticket is demoable end to end through every layer it touches, sized for one fresh context.

## Agent skills

### Issue tracker

Issues live as GitHub issues. See `docs/agents/issue-tracker.md`.

### Triage labels

Five canonical roles mapped to same-named GitHub labels. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context layout. See `docs/agents/domain.md`.
