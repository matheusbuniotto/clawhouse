# ADR-0003: Pydantic AI as the DatabricksClaw agent runtime

Date: 2026-10-10
Status: accepted (approved 2026-10-10 via HTML review: FastAPI+TS ✅ | Lakebase ✅ | PydanticAI ✅)
Deciders: crabriks maintainers
Related: [ADR-0001 FastAPI + TypeScript UI](0001-fastapi-typescript-ui.md), [ADR-0002 Lakebase + user workspace storage](0002-lakebase-workspace-storage.md), [issue #1 spec](../..), [issue #2 RFC](https://github.com/matheusbuniotto/crabriks/issues/2)

## Context

DatabricksClaw MVP needs exactly one Python agent runtime for v1 (issue #1, Implementation Decisions: "one framework for MVP — deep-agents or pydantic-ai — not both"). The runtime must sit under an already-decided architecture:

- **FastAPI backend + TypeScript/HTML frontend**, hosted as a Databricks App (ADR-0001).
- **Lakebase (managed Postgres) for sessions/transcripts/run locks, user workspace for agent personal files** (ADR-0002).
- **`system.ai` MCP tools over `streamable-http`, with per-request Databricks tokens and `serverName__toolName` namespacing** (issue #1, MCP decisions).
- **Databricks identity** for auth; no separate credential store (issue #1, Auth model).
- A deterministically composed system prompt (cache-stable prefix + per-turn suffix), lazy-loaded `SKILL.md` skills, a curated `MEMORY.md` plus retrievable `memory/*.md`, and a serialized single-turn orchestrator (issue #1, User Stories 8–38).

The runtime is a **coding/agent + harness** choice, not just an LLM wrapper: it must give us the agent loop, tool calling, structured output, MCP client, streaming, session persistence, guardrails, retries, evals, and observability without us re-implementing them.

This ADR confirms the expected fit for **Pydantic AI** (core + Harness + Evals), records the primary-source evidence, and disqualifies **deep-agents** as the v1 runtime.

## Decision

**Adopt Pydantic AI (`pydantic-ai` core, `pydantic-ai-harness`, `pydantic-evals`) as the single Python agent runtime for DatabricksClaw MVP.**

- Agent loop, tool calling, structured output, retries, usage limits, cancellation: `pydantic_ai.Agent`.
- Coding/agent harness primitives: `pydantic-ai-harness` — `Coder`, `FileSystem`, `Shell`, `Skills`, `Memory`, `RepoContext`, `Guardrails`, `StepPersistence`, `ConversationSearch`, `Instrumentation`.
- MCP: `pydantic_ai.mcp.MCPToolset` (or the `MCP` capability) over Streamable HTTP, with per-run dynamic toolsets for per-user Databricks tokens.
- Streaming to the TS frontend: `pydantic_ai.ui.vercel_ai.VercelAIAdapter` (or `AGUIAdapter`) served from FastAPI as SSE.
- Sessions/transcripts: core `Conversation` / `ConversationTypeAdapter` for a Lakebase `jsonb` column, or `StepPersistence` + `PostgresStepStore` over an asyncpg pool; long-term `MEMORY.md` via `Memory` + `PostgresMemoryStore`.
- Evaluation: `pydantic-evals` (deterministic, LLM-judge, span-based, and agentic trajectory evaluators).

No must-have gate failed. Two integration adaptations are required (Databricks model provider wiring and MCP tool-name formatting); both are local to modules the spec already requires us to build, and neither changes the choice.

## Comparison matrix (primary sources)

| Dimension | Pydantic AI (core + Harness) | deep-agents (LangChain/LangGraph) |
|---|---|---|
| Agent loop / tool calling | Typed `Agent`, `@agent.tool`/`tool_plain`, toolsets, `output_type` structured output (tool/native/prompted modes), retries, `UsageLimits`, cancellation ([Agents](https://pydantic.dev/docs/ai/core-concepts/agent/), [Tools](https://pydantic.dev/docs/ai/tools-toolsets/tools/), [Output](https://pydantic.dev/docs/ai/core-concepts/output/)) | `create_deep_agent` harness over LangChain `create_agent` + LangGraph runtime ([overview](https://docs.langchain.com/oss/python/deepagents/overview)) |
| MCP `streamable-http` client | First-party `MCPToolset(url)` auto-detects Streamable HTTP; `auth`/`headers`, `process_tool_call`, `.prefixed()`, tool-error behavior, dynamic per-run toolsets ([MCP client](https://pydantic.dev/docs/ai/mcp/client/)) | `langchain.mcp.MCPAdapter` (beta, `langchain[mcp]>=1.4.0`) built on FastMCP; `http(s)` URLs over Streamable HTTP ([MCP](https://docs.langchain.com/oss/python/langchain/mcp)) |
| Per-user auth for MCP | Documented pattern: `@agent.toolset(per_run_step=False)` builds a per-run `MCPToolset(auth=ctx.deps.mcp_token)`; docs explicitly warn a shared instance is a single identity ([per-user auth](https://pydantic.dev/docs/ai/mcp/client/#per-user-authentication)) | FastMCP auth (bearer/OAuth 2.1) + per-user server auth ([MCP auth](https://docs.langchain.com/oss/python/langchain/mcp/auth)) |
| Streaming to a TS frontend | First-party `VercelAIAdapter` / `AGUIAdapter` with `dispatch_request()` + `StreamingResponse` SSE; official **FastAPI + TypeScript** example ([UI event streams](https://pydantic.dev/docs/ai/integrations/ui/overview/), [Vercel AI](https://pydantic.dev/docs/ai/integrations/ui/vercel-ai/), [chat app example](https://pydantic.dev/docs/ai/examples/conversational-agents/chat-app/)) | Typed LangGraph event projections incl. `stream.subagents`; frontend integration via LangGraph/LangSmith ecosystem ([Streaming](https://docs.langchain.com/oss/python/deepagents/event-streaming)) |
| Session / transcript persistence | Core `Conversation` + `ConversationTypeAdapter` (store in your own `jsonb`); `StepPersistence` with **Postgres** (`PostgresStepStore`, asyncpg pool), snapshot/continue/fork, tool-effect ledger ([Persistence](https://pydantic.dev/docs/ai/core-concepts/persistence/), [Step Persistence](https://pydantic.dev/docs/ai/harness/step-persistence/)) | LangGraph checkpointers / store; durable execution, but the checkpoint backend is LangGraph-shaped, not a plain Postgres conversation table ([overview](https://docs.langchain.com/oss/python/deepagents/overview)) |
| Long-term memory matching `MEMORY.md` + `memory/*.md` | `Memory` capability: `MEMORY.md` main notebook + topic files, bounded injection, `read_memory`/`search_memory`/`write_memory`, per-user `namespace`, **Postgres store**, CAS + idempotency ([Memory](https://pydantic.dev/docs/ai/harness/memory/)) | `AGENTS.md` memory files always loaded; stored in State/Store/Filesystem backend — no curated-summary + on-demand topic-file model ([Memory](https://docs.langchain.com/oss/python/deepagents/overview#memory)) |
| Skills (`SKILL.md`) | `Skills` capability: catalog = name+description, load body on demand via `load_capability`, include/exclude, per-run catalog stable for cache ([Skills](https://pydantic.dev/docs/ai/harness/skills/)) | Agent Skills standard, progressive disclosure at startup ([Skills](https://docs.langchain.com/oss/python/deepagents/overview#skills)) |
| Bootstrap context (`AGENTS.md`, `SOUL.md`, `IDENTITY.md`, `USER.md`) | `RepoContext` loads `AGENTS.md`/`CLAUDE.md`; plus a pure `instructions` callable/`system_prompt` split we control ([Repo Context](https://pydantic.dev/docs/ai/harness/repo-context/), [Agents](https://pydantic.dev/docs/ai/core-concepts/agent/)) | `AGENTS.md` memory + skills inventory ([overview](https://docs.langchain.com/oss/python/deepagents/overview)) |
| Coding tools | `Coder` = `read_file`/`write_file`/`edit_file`/`list_files`/`grep`/`shell` + delegation + repo context + compaction ([Harness](https://pydantic.dev/docs/ai/harness/), [Coder](https://pydantic.dev/docs/ai/harness/coder/)) | Virtual filesystem tools (`ls`, `read_file`, `write_file`, `edit_file`, `delete`, `glob`, `grep`, `execute`) ([overview](https://docs.langchain.com/oss/python/deepagents/overview#virtual-filesystem-access)) |
| Guardrails / HITL | `InputGuardrail`/`OutputGuardrail`/`ToolGuardrail`, built-in secret/PII detectors, approval via deferred tools ([Guardrails](https://pydantic.dev/docs/ai/harness/guardrails/)) | LangGraph interrupts (`interrupt_on`) for approval ([Human-in-the-loop](https://docs.langchain.com/oss/python/deepagents/human-in-the-loop)) |
| Evals / harness | `pydantic-evals`: deterministic, LLM judge, span-based, **agentic trajectory** evaluators, online evaluation, pytest integration ([Evals](https://pydantic.dev/docs/ai/evals/evals/), [Testing](https://pydantic.dev/docs/ai/guides/testing/)) | LangSmith evaluation ecosystem (proprietary-first) |
| Observability | OpenTelemetry GenAI spans; Logfire optional, any OTLP backend ([Instrumentation](https://pydantic.dev/docs/ai/capabilities/instrumentation/), [Harness](https://pydantic.dev/docs/ai/harness/)) | LangSmith-first tracing |
| Retries / limits / timeouts | Explicit 7-layer retry model; `UsageLimits`; timeouts for model/tool/MCP ([Retries](https://pydantic.dev/docs/ai/core-concepts/retries/), [Timeouts](https://pydantic.dev/docs/ai/core-concepts/timeouts/)) | LangGraph/LangChain runtime retries/policies |
| Runtime weight / coupling | Core is a lean typed loop; Harness is a separate capability package. No graph runtime required. | Built on LangChain core + **LangGraph runtime**; middleware stack; heavier and more opinionated. |
| Maturity / version policy | Core Pydantic AI has a strict version policy; **Harness is 0.x and may break between minors** ([version policy](https://pydantic.dev/docs/ai/harness/#version-policy)) | `deepagents` / `langchain.mcp` both marked beta/0.x in places; LangChain ecosystem churn |
| License / provenance | Pydantic (MIT) | LangChain (MIT) |

## Why Pydantic AI

Pydantic AI's primitives map almost one-to-one onto the DatabricksClaw design doc DAG, so the runtime supplies the hard parts and we only own the Databricks-specific seams. `Skills`, `Memory`, `RepoContext`, `Guardrails`, `StepPersistence`, `ConversationSearch`, `Coder`, and `pydantic-evals` cover, respectively, the spec's skills subsystem, `MEMORY.md`/`memory/*.md`, bootstrap context, security guardrails, transcript/run-lock persistence, long-term recall, coding tools, and worked-example trace assertions. Critically, the two seams that make DatabricksClaw *Databricks* — per-request token injection into `system.ai` MCP tools, and a Lakebase-backed transcript store — are both first-class and documented: `MCPToolset` supports per-run dynamic toolsets for per-user credentials, and persistence is deliberately unopinionated (store a `Conversation` in your own Postgres `jsonb`, or use `PostgresStepStore` over asyncpg). Streaming to the already-chosen FastAPI + TypeScript frontend is first-party (`VercelAIAdapter`/`AGUIAdapter` with an official FastAPI + TypeScript example), so ADR-0001 does not need to change. Deep-agents is a credible harness, but it drags in the LangGraph runtime and middleware stack, its memory model (`AGENTS.md` always loaded) does not match the spec's curated `MEMORY.md` plus on-demand topic files, and its persistence/observability center of gravity is LangGraph/LangSmith rather than a plain Postgres conversation store. For a v1 that is explicitly one chat surface with one runtime, Pydantic AI is the lower-coupling, better-mapped fit.

## Must-have gate (does Pydantic AI fail anything?)

| Must-have | Verdict | Primary-source evidence |
|---|---|---|
| MCP `streamable-http` client for `system.ai` | **PASS** | `MCPToolset('https://.../mcp')` is recommended Streamable HTTP; URL ending `/sse` is the only SSE inference ([MCP client](https://pydantic.dev/docs/ai/mcp/client/#streamable-http)). Databricks MCPs are reachable at `https://<host>/ai-gateway/mcp-services/<catalog>.<schema>.<service>` ([Use MCP tools in a Python agent](https://docs.databricks.com/aws/en/agents/custom-agents/use-mcp-tools)). |
| Per-request Databricks token injection | **PASS** | Documented per-user pattern: build the toolset per run via `@agent.toolset(per_run_step=False)` and `MCPToolset(..., auth=ctx.deps.mcp_token)`; a shared instance is explicitly a single identity ([per-user auth](https://pydantic.dev/docs/ai/mcp/client/#per-user-authentication)). Databricks Apps forwards the user token in `x-forwarded-access-token`; FastAPI/Flask read `request.headers` ([Databricks Apps auth](https://docs.databricks.com/aws/en/dev-tools/databricks-apps/auth)). |
| Streaming to FastAPI → TS | **PASS** | `VercelAIAdapter.dispatch_request(request, agent=agent)` from a FastAPI endpoint returns a `StreamingResponse` of SSE; official FastAPI + TypeScript example in docs ([UI event streams](https://pydantic.dev/docs/ai/integrations/ui/overview/#usage-with-starlettefastapi), [Vercel AI](https://pydantic.dev/docs/ai/integrations/ui/vercel-ai/), [chat app](https://pydantic.dev/docs/ai/examples/conversational-agents/chat-app/)). |
| Session handling with Lakebase transcript store | **PASS** | `result.conversation` + `ConversationTypeAdapter.dump_json/validate_json` for a Postgres `jsonb` column, or append `new_messages_json()` per turn; `StepPersistence` ships `PostgresStepStore(pool)` (asyncpg-compatible, caller-owned pool) with continue/fork ([Persistence](https://pydantic.dev/docs/ai/core-concepts/persistence/), [Step Persistence backends](https://pydantic.dev/docs/ai/harness/step-persistence/#backends)). Lakebase is managed Postgres ([Databricks Lakebase](https://docs.databricks.com/oltp/projects)). |
| UC-scoped auth passthrough | **PASS** | Same per-run `deps` → dynamic toolset path; Databricks enforces UC grants on the forwarded token, and app scopes (`sql`, `ai-gateway`, `model-serving`, `vector-search`, …) gate what the app may do ([Databricks Apps auth](https://docs.databricks.com/aws/en/dev-tools/databricks-apps/auth)). |
| Coding/agent tool surface | **PASS** | `Coder` provides read/write/edit/list/grep/shell + delegation; `FileSystem`/`Shell` can be composed with allow/deny globs and credential scrubbing ([Harness](https://pydantic.dev/docs/ai/harness/), [Coder](https://pydantic.dev/docs/ai/harness/coder/)). |
| Harness: evals, retries, guardrails, observability | **PASS** | `pydantic-evals` incl. agentic trajectory + online eval; layered retries; `Input/Output/ToolGuardrail`; OTel GenAI spans ([Evals](https://pydantic.dev/docs/ai/evals/evals/), [Retries](https://pydantic.dev/docs/ai/core-concepts/retries/), [Guardrails](https://pydantic.dev/docs/ai/harness/guardrails/), [Instrumentation](https://pydantic.dev/docs/ai/capabilities/instrumentation/)). |

**Conclusion: no must-have fails.** There are two required integrations, not disqualifiers:

1. **Databricks model provider is not first-party.** Pydantic AI has no `databricks:` provider. Use `OpenAIChatModel(<serving-endpoint>, provider=OpenAIProvider(base_url='https://<workspace>/serving-endpoints', api_key=<token>))`, since Databricks Model Serving / Unity Gateway exposes an OpenAI-compatible Chat Completions API; use `ResolveModelId` or `SelectModel` to supply the per-request token from `deps` ([Other endpoints](https://pydantic.dev/docs/ai/models/compatible-apis/#other-endpoints), [Resolve Model ID](https://pydantic.dev/docs/ai/capabilities/resolve-model-id/), [Select Model](https://pydantic.dev/docs/ai/capabilities/select-model/)). Model profile may need tuning for tool-calling/structured-output quirks. **Owned by the model-config module.**
2. **MCP tool-name separator differs from the spec.** Pydantic AI's `.prefixed('server')` yields `server_tool` (single underscore) and does not implement the spec's deterministic numeric-suffix collision disambiguation. The spec already requires a dedicated MCP source module (`serverName__toolName`, length caps, deterministic ordering). Implement the name normalization there — via a custom toolset wrapper / FastMCP tool transformation, or by building the tool list ourselves — rather than relying on `.prefixed`. **Owned by the MCP source module.**

## Rejected alternative: deep-agents

deep-agents is a real harness and would satisfy the broad "coding agent + harness" brief (virtual filesystem, subagents, skills, `AGENTS.md` memory, LangGraph interrupts, MCP via FastMCP). It is rejected for v1 because:

- **Heavier coupling.** It requires LangChain core + the LangGraph runtime and middleware stack, versus Pydantic AI's lean typed loop plus an optional capability package. For a single chat surface, that is surface area we do not need.
- **Memory model mismatch.** The spec wants a curated `MEMORY.md` summary plus retrievable `memory/*.md` notes. deep-agents' memory is `AGENTS.md` files that are always loaded, which is the bootstrap-context role, not the curated-summary role.
- **Persistence fit.** ADR-0002 pins Lakebase. Pydantic AI persistence is explicitly unopinionated and ships a plain `PostgresStepStore`; deep-agents persistence is LangGraph-checkpointer-shaped.
- **Ecosystem center of gravity.** deep-agents' eval/observability story is LangSmith-first; DatabricksClaw wants framework-neutral OTel and code-first evals.
- **Beta surface.** `langchain.mcp` is beta (`>=1.4.0`) and `deepagents` moves quickly; Pydantic AI core has a stricter version policy, and the parts we lean on for Databricks seams (MCP client, persistence, UI adapters) are documented and stable.

This is a v1 decision, not a permanent verdict: if a later phase needs multi-agent graph orchestration, deep-agents/LangGraph can be revisited.

## Consequences

- `app_entrypoint` and the turn orchestrator build on `pydantic_ai.Agent` + capabilities; `run_turn(session_id, user_message) -> TurnResult` remains the single test seam and is framework-agnostic at the boundary.
- The six-doc design DAG maps to Pydantic AI capabilities: workspace → `resolve_agent_workspace` + `FileSystem`/`Coder`; bootstrap context → `RepoContext` + our pure prompt builder; skills → `Skills`; MCP → `MCPToolset` behind our MCP source module; system prompt → `instructions`/`system_prompt` (cache-stable) + `Caching`; turn orchestrator → `Agent.run`/`run_stream_events` with `UsageLimits` and a single-in-flight guard.
- Streaming is implemented with `VercelAIAdapter`/`AGUIAdapter` on the FastAPI route; the TS frontend consumes the Vercel AI data stream. The turn contract stays transport-agnostic, per ADR-0001.
- Lakebase stores `Conversation` JSON (or StepPersistence snapshots) and `Memory` Postgres rows; both share one pool.
- We take a dependency on `pydantic-ai`, `pydantic-ai-harness` (0.x), and `pydantic-evals`; versions must be pinned and upgraded deliberately.
- Evals/tests can use `TestModel`/`FunctionModel` with `ALLOW_MODEL_REQUESTS=False` for deterministic, network-free unit tests, plus `pydantic-evals` for worked-example traces.

## Open risks

1. **Databricks Apps reverse proxy + long SSE turns.** Databricks Apps forwards requests through a reverse proxy, handles TLS/H2C, and advises asynchronous patterns because synchronous waits "can time out" ([Best practices](https://docs.databricks.com/aws/en/dev-tools/databricks-apps/best-practices)). The spec already bounds turns to a request cycle, but a streaming turn that stays open must be validated end-to-end. **Mitigation:** spike an SSE turn through a deployed app; if buffering or a proxy timeout appears, fall back to chunked NDJSON/polling (the `StreamingResponse` seam is unchanged) or cap turn duration.
2. **Harness is 0.x.** `pydantic-ai-harness` APIs may move between minor releases. **Mitigation:** pin exact versions, read release-note migration guidance, keep capability usage thin and behind our own modules.
3. **Databricks model profile gaps.** Tool calling and structured output depend on the serving endpoint's OpenAI-compat behavior; thinking/structured-output flags may need a custom `OpenAIModelProfile`. **Mitigation:** integration test against the target `databricks-*` endpoint early.
4. **MCP naming/collision contract.** Pydantic AI does not implement `serverName__toolName` or numeric-suffix disambiguation. **Mitigation:** own it in the MCP source module (already required by the spec) and unit-test collision cases.
5. **Multi-instance run locks.** Databricks Apps horizontal scaling uses best-effort session affinity, not a distributed lease ([Horizontal scaling](https://docs.databricks.com/aws/en/dev-tools/databricks-apps/horizontal-scaling)). ADR-0002's Lakebase lock is the right enforcement point; Pydantic AI does not provide the lock. **Mitigation:** implement the single-in-flight guard in the Lakebase-backed store, not in process memory.
6. **MCP partial availability.** Spec requires a failing `tools/list` to omit that server, not kill the session. `MCPToolset` opens/closes toolsets per run; per-server failure isolation must be verified. **Mitigation:** connect/validate each server independently in the MCP source module and omit failures.

## Fallback if a gate later fails

If the SSE-through-Databricks-Apps risk cannot be mitigated, the runtime choice is unaffected: keep Pydantic AI and change only the transport (chunked NDJSON/polling instead of SSE). If per-user MCP auth with dynamic toolsets proves unworkable in a deployed app, fall back to a thin Databricks `DatabricksMCPClient` bridge exposed as Pydantic AI function tools (the same `process_tool_call`/toolset seam), preserving the agent loop and persistence. The only scenario that would reopen the framework decision is if Pydantic AI could not run its loop inside the Databricks App runtime at all; the evidence above shows it can.

## Sources (primary)

- Pydantic AI docs (`llms-full.txt`): Agents, Tools, Output, MCP client, UI event streams (AG-UI/Vercel AI), Persistence, Message history, Harness (Skills, Memory, Step Persistence, Guardrails, Coder), Pydantic Evals, Unit testing, Retries, compatible APIs, Select/Resolve model.
- deep-agents docs: overview, MCP, streaming, subagents, persistence.
- Databricks docs: Databricks Apps overview/key concepts/auth/best practices/horizontal scaling, MCPs, MCP auth & networking, Use MCP tools in a Python agent, Unity Gateway.
- In-repo: ADR-0001, ADR-0002, GitHub issue #1, GitHub issue #2.
