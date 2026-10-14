# ADR-D: Critério de aceite do pacote / Q4 runner

Date: 2026-10-14
Status: proposed (preferida: Arquiteto CCF)
Related: #77, [fatias-e-dod.md](../fatias-e-dod.md)

## Context

Sem aceite objetivo o time não sabe quando o runner está pronto para o CCF.

## Decision (preferida)

O runner está pronto quando **as duas** condições valem:

1. **Checklist smoke de #77** (login, turno, streaming, aprovação aprovar/negar, `/compact`, @mentions, criar agente, **agendar em linguagem natural → card → job em Workflows → dispara**, tools MCP listadas, context meter).
2. **Um agente CCF real** (config versionada, 1 das baits reais) **agendado via SP** do domínio: card mostra identidade SP + schedule legível + tabelas; job criado com tags `crabriks_*`; run dispara no horário como o SP.

## Considered options

| Opção | Por que descartada |
| --- | --- |
| Só smoke #77 | Não prova SP dedicado nem config versionada. |
| Só "um agente CCF" sem smoke | Não prova que o resto do runner não quebrou. |
| Aceite = merge de todas as sub-issues #78–#91 | Demais; várias (#83, #86, #88) não bloqueiam o agente CCF. |

## Consequences

- Fatias 1–3 de [fatias-e-dod.md](../fatias-e-dod.md) (caracterização, remover `agentic`, identidade SP) são o caminho crítico.
- Aceite é demonstrável em prod/staging, não só em CI.
