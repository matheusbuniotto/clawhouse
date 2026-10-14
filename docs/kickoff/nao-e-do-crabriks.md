# Não é do Crabriks

O runner recebe **só**: (1) config externa versionada, (2) jobs, (3) conexão MCP Databricks. Tudo abaixo fica fora. PR que adicione qualquer item volta.

| Fora | Onde vive / alternativa |
| --- | --- |
| Lógica do CCF (regras de bait, scoring, formato do report) | Repo/produto do CCF; entra como SQL/skill/prompt via config |
| Tools custom por agente (código Python por agente) | Não. Agente usa as tools da plataforma + MCP Databricks |
| Orquestração multi-agente (agente chama agente, planner, swarm) | Fora do Q4 |
| Conectores além do MCP Databricks (Slack, Sheets, webhooks novos) | Fora. Os existentes (`sheets.py`, `delivery_send_webhook`) ficam como estão, sem expansão |
| Segundo caminho de agendamento (tool `create_schedule`, `/schedule` novo) | Agendar = `jobs_create` (#90) |
| `task_type="agentic"` / `ai_query` dentro do job | Inteligência fica no Crabriks (`feat/platform-agent-jobs`) |
| Agentes criados no chat rodando em produção | Rascunho; para rodar, vira `agent.yaml` via PR |
| SP global / auth ambiente para jobs | Política de identidade |
| Redesenho de UI | #92, em paralelo e fora do OKR |
