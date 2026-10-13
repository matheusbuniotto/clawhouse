---
name: writing-for-agents
description: Edit and maintain agent instructions, skills, system prompts, and project knowledge using writing-for-agents principles (high density, clear constraints, actionable guardrails, scannable markdown). Use when creating or editing AGENTS.md, SKILL.md, SOUL.md, IDENTITY.md, system prompts, or ADRs.
---

# Writing for Agents

Instructions, skills, and system prompts are compiled directly into model context. When writing or editing documents meant for AI agents to consume, write for machine parsing: high information density, unambiguous constraints, structured tables, and explicit failure modes.

## The 6 Rules of Writing for Agents

### 1. High Information Density (Zero Fluff)
- Every sentence must constrain behavior, define a domain invariant, or provide a sequential workflow.
- Cut pleasantries, filler phrases ("Please note that...", "It is important to remember that..."), and motivational prose.
- Prefer compact bullet points with **bold lead-ins** over narrative paragraphs.

### 2. Asymmetric Constraints (Explicit DO vs DO NOT)
Models frequently fall back on generic training data unless bounded by explicit prohibitions. Always state both sides:
- **Positive instruction**: what the agent MUST do and when.
- **Negative constraint**: what the agent MUST NOT do, common anti-patterns to avoid, and what is out of scope.
- Example:
  - *Do*: "Adopt the mentioned agent's persona directly in the active turn."
  - *Do NOT*: "Do NOT search for an external delegation tool or attempt to spawn a subagent process."

### 3. Concrete Values Over Subjective Adjectives
Never use qualitative adjectives when an exact rule or threshold exists:
- Avoid: "Keep functions simple and clean."
- Write: "Keep cognitive complexity <= 15 (`complexipy src --max-complexity-allowed 15`)."
- Avoid: "Return results quickly."
- Write: "Limit queries to `limit=100` and use `jobs_get_run` to check task states."

### 4. Table-Driven Scaffolding
Use markdown tables for parallel reference items (tools, arguments, permissions, states). Models parse tabular schemas more reliably than long prose lists.

| Tool | Effect | Approval |
| --- | --- | --- |
| `jobs_list(limit)` | Lists workspace jobs (max 100). | no |
| `jobs_create(name, task_type, ...)` | Creates a one-task Lakeflow job. | **yes** |
| `jobs_run_now(job_id, parameters)` | Triggers an immediate run. | **yes** |

### 5. Explicit Error and Fallback Paths
Every tool call or integration point can fail. Document the exact recovery branch:
- State what error code or message to expect.
- State whether to retry, fall back, or stop and inform the user.
- Explicitly forbid silent failure or infinite retry loops.

### 6. Scannable Progressive Disclosure
- Always include valid YAML frontmatter on skills: `name` and a trigger-rich `description` containing the keywords users and routers search for.
- Use strict markdown header levels (`#`, `##`, `###`).
- Keep top-level files focused; extract deep references into separate topical documents.

---

## Crabriks Project Surfaces

When editing documents across the Crabriks codebase, follow the specific conventions for each surface:

### Surface 1: Repo Root `AGENTS.md`
- **Audience**: AI coding assistants (Claude Code, Antigravity, Cursor) operating on this repository.
- **Scope**:
  - Technology stack and ADR references.
  - Development work loop and quality gates (`uv sync`, `prek run -a`, `complexipy`, `pyright`, `pytest`).
  - Architectural patterns (pure resolvers, typed boundaries, `run_turn` test seam).
  - Index of agent skills in `.agents/skills/`.
- **Rule**: Do not add code snippets or ephemeral file paths that rot. Document invariants and behavior.

### Surface 2: Platform Agent `claw/agents/main/AGENTS.md`
- **Audience**: Crabriks runtime agent interacting with Databricks users in chat sessions.
- **Scope**:
  - Behavioral guidelines for tool usage.
  - Unity Catalog discovery rules (`uc_*` tools must run before claiming data is unknown).
  - Lakeflow Jobs execution guidelines (SQL workspace `FILE` vs `NOTEBOOK`, warehouse targeting).
  - Human approval awareness (state intent in 1 sentence before mutating calls).
  - Single-turn persona adoption on `@AgentName` mentions.
- **Rule**: Keep instructions directly actionable during a turn.

### Surface 3: Skills (`.agents/skills/<name>/SKILL.md` & `claw/.../skills/`)
- **Structure**:
  1. YAML frontmatter (`name`, `description`).
  2. High-level summary of capability.
  3. Tool reference table (including whether human approval is required).
  4. Sequential step-by-step workflow.
  5. Negative constraints and safety rules.
  6. Failure modes and error handling.

### Surface 4: Agent Personal Files (`SOUL.md`, `IDENTITY.md`, `USER.md`, `MEMORY.md`)
- **Scope**: Extreme conciseness (1–3 lines).
- `SOUL.md`: Tone and voice directive.
- `IDENTITY.md`: Name and role.
- `USER.md`: Who the user is.
- `MEMORY.md`: High-level pointer to long-term memory.

### Surface 5: Architecture Decision Records (`docs/adr/XXXX-*.md`)
- **Structure**: Status (`Accepted`), Context, Decision, Consequences.
- **Rule**: Document the *why* and the chosen trade-offs, not just the implementation.

---

## Writing-for-Agents Verification Checklist

Before saving changes to any agent prompt, skill, or instruction file, verify:

- [ ] **Zero fluff**: Are pleasantries, conversational filler, and vague introductions removed?
- [ ] **Bipolar constraints**: Are both positive (DO) and negative (DO NOT) constraints present?
- [ ] **Exact identifiers**: Are tool names, parameters, file types, and paths spelled exactly as in code?
- [ ] **Approvals noted**: Are mutating operations clearly flagged as requiring human confirmation?
- [ ] **Failure branches**: Is there an explicit rule for what to do when an operation fails?
- [ ] **Valid frontmatter**: Do skills have opening and closing `---` delimiters with valid YAML `name` and `description`?
