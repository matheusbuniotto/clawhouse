# ADR-C: Config externa + contrato de job

Date: 2026-10-14
Status: proposed (preferida: Arquiteto CCF)
Related: ADR-0005, #78, [config-externa.md](../config-externa.md), [contrato-job.md](../contrato-job.md)

## Context

O runner precisa de um contrato estável antes de refatorar `turn`/`resume`/`schedules` (risco R1). Hoje a "config" é misturada: markdown no Git, agentes custom no Lakebase, modelos/MCP no env, schedule em tool e em `/schedule`.

## Decision (preferida)

1. **Config versionada** `claw/agents/<id>/agent.yaml` + markdown, validada na carga. Schema em [config-externa.md](../config-externa.md).
2. **Contrato de job** único: NL → card (schedule legível, identidade, tabelas) → `jobs_create`. Detalhe em [contrato-job.md](../contrato-job.md).
3. Remover `task_type="agentic"` / `ai_query` do job (merge de `feat/platform-agent-jobs`).
4. Congelar esses dois contratos **antes** de mexer em `turn.py` / `resume_turn` / `schedules.py`.

## Considered options

| Opção | Por que descartada |
| --- | --- |
| Manter agentes custom do Lakebase como oficiais | Sem revisão por PR; não é config externa versionada. |
| Dois caminhos de schedule (`/schedule` + `jobs_create`) | Modelo escolhe o errado; #90 proíbe tool paralela. Preferência: depreciar `/schedule` (B1). |
| Manter `agentic` | Inteligência fora do runner; contradiz a visão. |
| Config em UC Volume / tabela | Infra nova sem ganho no Q4. |
| Mudar `turn`/`resume` antes de fechar o contrato | Risco R1. |

## Consequences

- Loader pydantic novo; testes de schema inválido.
- `/schedule` in-app: decisão residual (B1 preferida) — se mantida, fora do caminho de produção.
- Em aberto: owner de jobs órfãos e política de expiração ([riscos.md](../riscos.md)).
