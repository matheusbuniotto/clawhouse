> Contratos **atuais** (código). Contratos-alvo: [config-externa.md](config-externa.md), [contrato-job.md](contrato-job.md), [politica-identidade.md](politica-identidade.md). Gaps = decisão A–E.

# Contratos atuais (estado em `dev`)

Descreve o que o código faz **hoje**. Mudar qualquer linha abaixo = mudança de contrato → ver DoD em [`fatias-e-dod.md`](fatias-e-dod.md).

Paths relativos à raiz do repo. Linhas aproximadas (podem andar; confira com `rg`).

---

## 1. Jobs: linguagem natural → `jobs_create` → Databricks Job

**Comportamento protegido (#78).** Pedir no chat "agenda X todo dia às 9h" funciona em produção hoje.

### Entrada
- Mensagem do usuário em linguagem natural.
- O modelo é orientado por `claw/agents/main/AGENTS.md` (seção Lakeflow Jobs) e `claw/agents/main/skills/lakeflow-jobs/SKILL.md` a chamar `jobs_create` com `cron_expression`.
- Tool: `DatabricksTools.jobs_create` — `src/crabriks/capabilities/databricks.py` (~L499).
  - `name: str`
  - `task_type: "python" | "sql" | "agentic"` (default `"sql"`)
  - `path`, `query`, `warehouse_id`, `parameters`
  - `agent_name`, `instructions` (só para `agentic`)
  - `cron_expression`, `timezone_id="UTC"`, `pause_status="UNPAUSED"`

### Processamento
1. **Gate de aprovação:** `jobs_create` está em `_APPROVAL_REQUIRED_TOOLS` (~L60). `DatabricksCapability.get_wrapper_toolset` (~L917) embrulha em `ApprovalRequiredToolset`. O turno pausa com `DeferredToolRequests`, a UI mostra o card, e `resume_turn` continua.
2. **Cron → Quartz:** `to_quartz_cron` (~L130). Cron de 5 campos vira `0 m h dom mon dow` com `?` em dow (se `*`) ou dom. 6/7 campos passam direto.
3. **Schedule:** `build_cron_schedule` (~L145) → `CronSchedule(quartz_cron_expression, timezone_id, pause_status)`; `None` sem cron.
4. **Task:**
   - `python` → `SparkPythonTask(python_file=path)`.
   - `sql` → `_build_sql_task` (~L458) grava `/Workspace/Shared/crabriks/<task_key>.sql` como `FILE` (via `workspace.upload`, não `import_`) e roda num SQL Warehouse.
   - `agentic` → `build_agentic_query` (~L166) embrulha a query com `ai_query(...)`.
5. `client.jobs.create(name=..., tasks=[task], schedule=...)` via `self._call(...)` (~L545).

### Saída
- Sucesso: `{"job_id": int, "name": str}` + `"scheduled": True` se houve schedule; + `task_type`/`agent_name` se agentic.
- O resultado volta como `tool_result` no transcript da sessão.

### Erros
- SQL task inválida → `{"error": "..."}` (não lança).
- `jobs.create` falha nas duas identidades → `{"error": "Failed to create job <name>: <msg>"}`.
- Aprovação negada → `jobs.create` **nunca** é chamado.

### O que NÃO faz
- Não roda um turno do Crabriks quando o job dispara. O resultado do job **não volta** ao chat.
- Não valida cron com `dom` e `dow` ambos explícitos: gera Quartz inválido (ex.: `0 9 1 * 1` → `0 0 9 1 * 1`). Bug conhecido, coberto por teste de caracterização (PR #93).
- Não informa no resultado **qual identidade** criou o job.

### Testes que pinam isso
- `tests/test_jobs_tools.py`
- `tests/test_jobs_create_characterization.py` (PR #93)

---

## 2. O que o agente recebe hoje (por turno)

Montado em `src/crabriks/agent/turn.py`:
- `_invoke_agent` (~L606)
- `_capabilities_for_turn` (~L451)
- `_prompt_for` (~L487)

| Input | Origem | Arquivo |
| --- | --- | --- |
| Persona / instruções | `claw/agents/main/{AGENTS,SOUL,IDENTITY,USER,MEMORY}.md` (Git, read-only) | ADR `docs/adr/0005-platform-controlled-agent.md`; `src/crabriks/agent/prompt.py` |
| Skills | `claw/agents/main/skills/*/SKILL.md` | `src/crabriks/capabilities/skills.py` |
| Modelos | `SERVING_ENDPOINT` + `CRABRIKS_MODELS` (JSON) | `src/crabriks/settings.py` (`models_from_env`) |
| MCP servers | `CRABRIKS_MCP_SERVERS` (JSON `[{name,url,timeout_seconds}]`) | `src/crabriks/settings.py` (`mcp_servers_from_env`) |
| Tools sensíveis | `CRABRIKS_SENSITIVE_TOOLS` | `src/crabriks/settings.py`; guard em `turn.py` (`_sensitive_tool_guard`) |
| Tools Databricks | `DatabricksCapability` (UC, DBSQL, `system_ai_query`, jobs) | `src/crabriks/capabilities/databricks.py` |
| Tools Sheets | `GoogleSheetsCapability` | `src/crabriks/capabilities/sheets.py` |
| Agentes custom | Lakebase `crabriks.custom_agents` + tool `create_agent` | `src/crabriks/store/store.py` (~L107); `src/crabriks/capabilities/agent_tools.py` |
| Contexto de @mention | Injetado como string `[Injected Context]` no prompt do usuário | `src/crabriks/capabilities/mentions.py` (#86) |
| Catálogo de tools no prompt | `ToolCard`s manuais (`DATABRICKS_TOOL_CARDS`, ~L403) | `turn.py` (#81 remove) |
| Histórico | Transcript do Lakebase → `to_model_messages` | `src/crabriks/agent/history.py` (#79) |

> Agentes custom (Lakebase) e o slash `/schedule` **não** são um dos 3 inputs da visão. Ver decisões C e B.

---

## 3. Identidade (credencial)

### Regra travada pelo Matheus (#78)
1. **SP dedicado** para jobs primeiro.
2. Sem SP dedicado → **OBO do usuário**, de forma explícita: log `warning` + identidade mostrada no chat.
3. **Nunca** cair silenciosamente em outra identidade.

### Como está hoje (ordem invertida)
- **Token por request:** `request_token` (`src/crabriks/settings.py` ~L80) usa primeiro o header encaminhado; o dev token vale só para `CRABRIKS_DEV_USER`.
- **Capability por request:** `src/crabriks/api/app.py` (~L942) cria `DatabricksCapability(user_token=token)` a cada request.
- **Client:**
  - `default_workspace_client` (`databricks.py` ~L869) tenta `WorkspaceClient(token=user, auth_type="pat")`.
  - Se falhar → `WorkspaceClient()` ambiente = **SP do app**.
- **Por chamada:** `DatabricksTools._call` (~L273). Se a chamada com o client do usuário falhar → repete com o ambiente (`_fallback_client`), só com `logger.info`.
- **No setup:** `DatabricksCapability.get_toolset` (~L898). Se a factory falhar → client ambiente.
- **Escopos OBO do app:** `databricks.yml` (`user_api_scopes`) lista `model-serving`, `sql`, `ai-functions`, `genie`, `workspace.workspace`, `mcp.external` e `ai-gateway`. **Não há escopo de jobs**, então na prática o `jobs.create` com OBO tende a falhar e cair no SP do app. Confirmar em prod antes de #78 passo 2.
- **`/schedule` worker:** `_make_turn_ctx` (`api/app.py` ~L228) usa `settings.dev_token or ""` → token vazio em prod. MCP é omitido e as tools Databricks caem no SP do app.
- **Mutação:** `_capabilities_for_turn` (~L469) muta `cap.user_token` (#80 corrige).

### Testes que pinam isso
- `tests/test_jobs_create_characterization.py` (seção "credential")
- `tests/test_databricks_tools.py` (`test_databricks_tools_fallback_when_user_client_lacks_scope`)

---

## 4. MCP Databricks

### Entrada
- Env `CRABRIKS_MCP_SERVERS`: JSON `[{"name": "...", "url": "https://...", "timeout_seconds": 30}]` (`src/crabriks/settings.py` ~L139).
- `MCPServerConfig` exige `https`. Nomes são únicos (`DuplicateMCPServerName`) (`src/crabriks/capabilities/mcp.py` ~L37).
- Token: o **token do usuário** do turno (`TurnContext.user_token`).

### Processamento (`src/crabriks/capabilities/mcp.py`)
1. `load_mcp_tools` (~L316). Sem servers → nada. **Sem token → omite todos os servers** (`logger.warning`).
2. Por server: `create_mcp_toolset` (~L231) → `MCPToolset(StreamableHttpTransport(url, headers={"Authorization": "Bearer <token>"}))`.
3. `tools/list` **antecipado** (`_fetch_server_tools`) para montar os nomes.
4. Nomes viram `<server>__<tool>`, truncados em 64 caracteres e desambiguados com sufixo `_N` (`disambiguate_tool_names`).
5. `RenamedToolset` + `ScrubbingToolset` (remove o token de descrições, schemas, resultados e erros).
6. `MCPCapability` entra em `_capabilities_for_turn`. `ToolCard`s MCP entram no prompt.

### Saída
- Tools `server__tool` disponíveis ao agente.
- Resultado da tool com o token trocado por `[REDACTED]`.

### Erros
- `tools/list` falhou num server → server **omitido** do turno (log `warning`, token removido). Os demais servers seguem.
- URL não-https → `InsecureMCPEndpoint` na carga da config (falha o boot).

### O que NÃO faz
- Não usa SP. Sem token de usuário (ex.: worker `/schedule`), não há MCP.
- Não usa `MCPToolset.prefixed()` nativo; o rename é manual (#89).
- Não exige aprovação por padrão. Só se a tool estiver em `CRABRIKS_SENSITIVE_TOOLS`.
- Não cacheia `tools/list` entre turnos (custo por turno).
