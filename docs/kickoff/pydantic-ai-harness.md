# pydantic-ai / pydantic-ai-harness no Crabriks

Versões (`pyproject.toml`): `pydantic-ai>=2.55.0`, `pydantic-ai-harness[skills]==0.55.0`.

Regra do epic [#77](https://github.com/matheusbuniotto/crabriks/issues/77): **preferir o recurso nativo** ao código custom. Cada substituição é uma fatia com teste de caracterização antes.

## Mapa

| Peça | Onde | Nativo usado |
| --- | --- | --- |
| Agent | `src/crabriks/agent/core.py` (`crabriks_agent`) | `pydantic_ai.Agent`, `output_type=[str, DeferredToolRequests]` |
| Loop do turno | `src/crabriks/agent/turn.py` (`run_turn`, `resume_turn`, `_invoke_agent`) | `agent.run(..., capabilities=..., event_stream_handler=...)`, `DeferredToolResults` |
| Capabilities por turno | `turn.py` `_capabilities_for_turn` | `AbstractCapability` / `AgentCapability` |
| Tools Databricks + jobs | `src/crabriks/capabilities/databricks.py` (`DatabricksCapability`) | `FunctionToolset`, `ApprovalRequiredToolset` |
| MCP | `src/crabriks/capabilities/mcp.py` (`MCPCapability`) | `pydantic_ai.mcp.MCPToolset`, `.renamed()`, `WrapperToolset`, `CombinedToolset` |
| Skills | `src/crabriks/capabilities/skills.py` | `pydantic_ai_harness.Skills` + `LocalWorkspaceBackend` |
| Guardrail de tools sensíveis | `turn.py` `_sensitive_tool_guard` | `pydantic_ai_harness.guardrails.ToolGuardrail` |
| Compactação | `src/crabriks/capabilities/mentions.py` `tiered_compaction` | `TieredCompaction`, `ClearToolResults`, `SummarizingCompaction` |
| Medidor de contexto | `turn.py` | `pydantic_ai_harness.compaction.ReportContextUsage` |
| Slash commands | `src/crabriks/agent/commands.py` | custom (fora do agente, intencional) |
| `/schedule` | `src/crabriks/capabilities/schedules.py` + worker no lifespan de `api/app.py` | custom (`croniter`) — ver decisão B |

## Snippets reais

### Agent (`src/crabriks/agent/core.py`)

```python
@lru_cache(maxsize=1)
def crabriks_agent() -> Agent[TurnDeps, str | DeferredToolRequests]:
    agent: Agent[TurnDeps, str | DeferredToolRequests] = Agent(
        name="crabriks",
        deps_type=TurnDeps,
        output_type=[str, DeferredToolRequests],
    )
```

`TurnDeps` hoje só carrega `now`. O token **não** está em deps (#80).

### Chamada do agente (`src/crabriks/agent/turn.py`, `_invoke_agent`)

```python
result = await crabriks_agent().run(
    user_prompt,
    message_history=history,
    deferred_tool_results=deferred_results,
    model=ctx.model,
    instructions=prompt.text,
    deps=TurnDeps(now=ctx.now),
    event_stream_handler=_persist_and_emit(
        claimed, queue, skip_tool_call_id=skip_tool_call_id, usage=usage
    ),
    capabilities=_capabilities_for_turn(claimed, mcp, birth_ritual=birth_ritual),
)
if isinstance(result.output, DeferredToolRequests):
    return await _handle_deferred_approvals(claimed, queue, result.output)
```

### Mutação de capability compartilhada (`turn.py`, `_capabilities_for_turn`) — alvo de #80

```python
if claimed.ctx.databricks_capability is not None:
    cap = claimed.ctx.databricks_capability
    if not cap.user_token and claimed.ctx.user_token:
        cap.user_token = claimed.ctx.user_token
    capabilities.append(cap)
```

### Gate de aprovação de jobs (`src/crabriks/capabilities/databricks.py`)

```python
def get_wrapper_toolset(self, toolset: AbstractToolset[Any]) -> AbstractToolset[Any]:
    def approval_required(_ctx, tool_def, args) -> bool:
        if tool_def.name == "dbsql_query":
            sql = str(args.get("query", ""))
            return not is_readonly_query(sql)
        return tool_def.name in _APPROVAL_REQUIRED_TOOLS

    return ApprovalRequiredToolset(toolset, approval_required_func=approval_required)
```

### Fallback silencioso de identidade (`databricks.py`, `DatabricksTools._call`) — alvo de #78 passo 2

```python
def _call(self, fn: Callable[[WorkspaceClient], _T]) -> _T:
    try:
        return fn(self.client)
    except Exception as exc:
        fallback = self._fallback_client()
        if fallback is not None and fallback is not self.client:
            logger.info("Call on user client failed (%s); trying ambient client", exc)
            return fn(fallback)
        raise
```

### Parser de `/schedule` (`src/crabriks/capabilities/schedules.py`) — alvo de #90

```python
_CRON_PATTERN = re.compile(r'^\s*/schedule\s+cron\s+["\']([^"\']+)["\']\s+(.+)$', re.DOTALL)
_EVERY_PATTERN = re.compile(r"^\s*/schedule\s+every\s+(\d+)([mh])\s+(.+)$", re.DOTALL)
```

## O que #78 / #80 / #90 tocam

### [#78](https://github.com/matheusbuniotto/crabriks/issues/78) — Agendamento e identidade de jobs
- **Passo 1:** testes de caracterização (PR #93). Sem código de produção.
- **Passo 2:** `jobs_identity(settings, user_token)` em `databricks.py`.
  - Novos campos em `Settings` (`src/crabriks/settings.py`).
  - `jobs_create`/`jobs_edit`/`jobs_run_now`/`jobs_delete` usam essa identidade em vez de `_call`.
  - O resultado ganha `identity: {kind, label}`.
- **Passo 3:** decisão B (`/schedule`). Toca `schedules.py`, `commands.py`, `api/app.py` (lifespan + rotas) e `store/store.py`.
- **Não tocar:** `to_quartz_cron`/`build_cron_schedule`, exceto para corrigir o bug `dom`+`dow` com teste novo.

### [#80](https://github.com/matheusbuniotto/crabriks/issues/80) — Token via deps, sem mutação
- `TurnDeps` (`agent/core.py`) ganha `user_token`.
- `_capabilities_for_turn` (`turn.py`) deixa de mutar `cap.user_token`.
- `DatabricksCapability` lê o token do contexto ou é criada por turno.
- Atenção: `app.py` (~L942) já cria a capability por request. O risco é o reuso em testes e no worker (`_make_turn_ctx`).

### [#90](https://github.com/matheusbuniotto/crabriks/issues/90) — Parser pydantic do `/schedule`
- Troca as regex de `schedules.py` por um modelo pydantic.
- `resolve_workspace_root` (`capabilities/agent_tools.py`) passa a receber a raiz explícita.
- **Não** adicionar tool `create_schedule`.
- Se a decisão B for B1, #90 vira "remover".

### Vizinhas que mexem no mesmo código
| Issue | O que mexe |
| --- | --- |
| #79 | `history.py` / ModelMessages nativos |
| #81 | `ToolCard`s no prompt |
| #82 | unificar `ApprovalRequiredToolset` + `ToolGuardrail` + Sheets |
| #83 | queue/worker de `turn.py` → `agent.iter` / `run_stream_events` |
| #84 | `_prompt_for` / `_Claimed` |
| #89 | `MCPToolset.prefixed()` |
| #91 | tools retornam tipos + `ModelRetry` |
