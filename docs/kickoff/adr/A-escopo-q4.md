# ADR-A: Escopo Q4 do runner

Date: 2026-10-14
Status: proposed (preferida: Arquiteto CCF)
Related: #77, [README](../README.md), [nao-e-do-crabriks.md](../nao-e-do-crabriks.md)

## Context

O Q4 precisa de um agente CCF em produção. O risco é o runner virar plataforma genérica demais e atrasar a entrega.

## Decision (preferida)

No Q4 o Crabriks é **só o runner**, via:

1. **Config versionada** (`agent.yaml` + markdown) para 2–3 agentes CCF reais.
2. **Agendamento em linguagem natural** → card → `jobs_create` (fluxo A de #78).
3. **MCP Databricks** como única conexão externa nova.

**Fora:** tools custom por agente, orquestração multi-agente, conectores além do MCP Databricks, lógica CCF no código do runner. Lista completa em [nao-e-do-crabriks.md](../nao-e-do-crabriks.md).

## Considered options

| Opção | Por que descartada / adiada |
| --- | --- |
| Plataforma genérica com agents autorados no chat (`create_agent` em produção) | Multi-tenant e isolamento; ADR-0005 já adiou. Rascunhos no Lakebase ficam; não rodam em job. |
| Orquestração multi-agente (subagentes, planner) | Fora do Q4; #86 toca mentions, não orquestração. |
| Embutir lógica CCF no runner | Viola "só 3 inputs"; product logic muda a cada bait. |
| Expandir conectores (Slack, Sheets novas) | Fora do Q4. Sheets/webhook existentes ficam sem expansão. |

## Consequences

- Aceite do Q4: checklist smoke de #77 + **um agente CCF real agendado via SP** (ver [fatias-e-dod.md](../fatias-e-dod.md)).
- #92 (UI OpenClaw) é paralelo, fora do OKR (ADR-E).
