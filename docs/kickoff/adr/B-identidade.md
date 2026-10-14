# ADR-B: Identidade de jobs — SP por domínio

Date: 2026-10-14
Status: proposed (preferida: Matheus + Arquiteto CCF)
Related: #78, [politica-identidade.md](../politica-identidade.md)

## Context

Hoje `default_workspace_client` / `_call` / `get_toolset` usam OBO primeiro e caem no SP do app em silêncio. A regra do Matheus já inverte: SP dedicado primeiro, OBO explícito. O Arquiteto CCF endurece: SP **por domínio**, nunca global.

## Decision (preferida)

- SP dedicado **por agente/domínio**, declarado no `agent.yaml`.
- Fallback OBO só se `fallback_usuario: true` **e** aprovado no card.
- Identidade gravada no job (tags + `run_as`), no log e no resultado da tool.
- Falha do SP ⇒ o job falha (sem retry com outra identidade).
- Texto completo: [politica-identidade.md](../politica-identidade.md).

## Considered options

| Opção | Por que descartada |
| --- | --- |
| SP global = SP do app (auth ambiente) | Acumula permissão; mistura runtime e produção; viola "nunca global". |
| Só OBO (adicionar escopo de jobs) | Contraria a regra do Matheus; job some se o usuário sair. |
| Fallback silencioso (status quo) | Sem rastreabilidade; identidade errada em prod. |
| Um SP por agente (não por domínio) | Overhead de gestão; domínio é a unidade de permissão do UC. |

## Consequences

- Novos campos em `Settings` / secrets do app; tags no Job; mudança no resultado de `jobs_*` → Decision Record de implementação + atualizar [contratos.md](../contratos.md).
- Confirmar se OBO precisa de escopo de jobs em `databricks.yml` antes de habilitar `fallback_usuario`.
