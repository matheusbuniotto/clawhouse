# Clawhouse — DatabricksClaw MVP

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
uv run complexipy src --max-complexity-allowed 10
uv run pyright
```

CI (`quality.yml`) runs ruff, complexipy, pyright, vulture, jscpd, and pytest on push/PR to main. Keep `main` green: small commits, gates passing locally first.

## Patterns

- Pure resolvers first: path/context composition does no I/O; stores hide behind injected dependencies.
- Typed boundaries: frozen dataclasses for cross-module shapes (`WorkspacePaths`, prompt results, turn results).
- One test seam: `run_turn(session_id, user_message) -> TurnResult` at the chat entrypoint covers composition, tools, and persistence. Drop to `build_system_prompt` assertions only for ordering/cache-stability.
- External behavior in tests, never internals; exact expected values over adjectives.
- Databricks Apps ambient client fallback: User forwarded OAuth tokens in Databricks Apps may lack workspace write or warehouse enumeration permissions. Capabilities must provide ambient `WorkspaceClient()` fallback (Service Principal) for platform resources while attributing actions to the user.
- Lakeflow Jobs workspace file format: Lakeflow Jobs SQL tasks (`SqlTaskFile`) strictly require workspace items of `Type: FILE`. `workspace.import_` creates a `NOTEBOOK` (causing fetch failure). Always use `workspace.upload(...)` with `format=ImportFormat.AUTO` and ensure parent directories exist via `workspace.mkdirs(...)`.
- Inline human approvals: Mutating tool calls pause turn execution and emit `approval_required` SSE events to the UI. The UI renders inline `[Approve]` / `[Deny]` action buttons in the transcript stream.
- Single-turn agent delegation: In chat turns mentioning `@AgentName`, delegation is prompt persona injection in the active turn, not multi-process spawning. The active agent directly adopts the target persona, system prompt, and emoji.
- Agentic Jobs & DBSQL `ai_query`: Autonomous analytical workflows (`Query => Agent analysis => Output`) execute directly inside Lakeflow Jobs using DBSQL `ai_query` on the SQL Warehouse, eliminating dedicated cluster provisioning and producing agent analysis in task outputs.
- Lakeflow Job Lifecycle: `jobs_create` supports `task_type="agentic"`, `task_type="sql"`, and `task_type="python"`, plus Quartz cron schedules. `jobs_edit` updates settings/schedules/queries, `jobs_delete` removes jobs, and `jobs_get_run_output` retrieves execution logs and analytical reports.
- Issues carry behavior and acceptance criteria, never file paths or code snippets (they rot).
- Vertical slices: each ticket is demoable end to end through every layer it touches, sized for one fresh context.

### Good-looking code in Clawhouse

- **Early returns first**: Guard clauses handle errors, empty checks, and bounds at the top; the happy path has zero indentation.
- **Small named helpers**: One level of abstraction per function; break nested blocks and loops into small, focused pure functions.
- **Typed models over dicts**: Frozen dataclasses or Pydantic models for every boundary; zero untyped `dict[str, Any]` across modules.
- **Ruff layout**: Target 100 chars, double quotes, no trailing commas when fitting one line, strict standard imports (`I`).
- **Deep modules**: Hide complex operations behind a minimal interface; caller learns 1 function, gets full leverage.

## Agent skills

### Issue tracker

Issues live as GitHub issues. See `docs/agents/issue-tracker.md`.

### Triage labels

Five canonical roles mapped to same-named GitHub labels. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context layout. See `docs/agents/domain.md`.

### Writing for agents

Skill for editing and maintaining project instructions, skills, prompts, and domain docs using high-density, agent-optimized writing standards. See `.agents/skills/writing-for-agents/SKILL.md`.
