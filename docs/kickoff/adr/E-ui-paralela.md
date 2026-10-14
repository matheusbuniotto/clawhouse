# ADR-E: #92 em paralelo, fora do OKR

Date: 2026-10-14
Status: proposed (preferida: Arquiteto CCF)
Related: #92, [riscos.md](../riscos.md) R7

## Context

#92 aproxima o chat do OpenClaw 2.0 (só features existentes). Sem regra clara, disputa o mesmo código do contrato de turno/card.

## Decision (preferida)

- #92 roda **em paralelo** e **fora do OKR** do Q4.
- Só **consome** o contrato: eventos SSE, shape do card de aprovação, tools. Não muda identidade, schedule, tags do job nem schema de config.
- Se o card ganhar campos novos (schedule legível, identidade, tabelas), #92 só renderiza; a fonte é o backend (contrato de job).

## Considered options

| Opção | Por que descartada |
| --- | --- |
| #92 no caminho crítico do OKR | Atrasa o agente CCF; visual ≠ entrega. |
| #92 pode mudar eventos SSE / shape do card | Quebra o contrato congelado (R1/R7). |
| Adiar #92 totalmente | Perde alinhamento visual; o Arquiteto CCF pediu paralelo, não bloqueio. |

## Consequences

- PRs de #92 não tocam `databricks.py` (jobs/identity), `settings.py` (config) nem o schema de `agent.yaml`.
- DoD de #92: screenshots + testes de frontend; smoke #77 continua verde.
