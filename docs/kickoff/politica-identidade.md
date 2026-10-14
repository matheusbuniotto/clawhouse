# Política de identidade (proposta escrita)

**Status:** proposta preferida (Matheus + Arquiteto CCF), não fechada. Decisão em [ADR-B](adr/B-identidade.md).

## Regras
1. **SP dedicado por agente/domínio.** Cada domínio (ex.: `ccf`) tem o seu SP, declarado no `agent.yaml` (`jobs.identidade.service_principal`).
2. **Nunca um SP global.** O SP do app (auth ambiente, `WorkspaceClient()`) **não** cria nem executa jobs de agentes.
3. **Fallback para o usuário (OBO)** só quando as duas condições valem:
   - declarado na config (`fallback_usuario: true`);
   - aprovado no card, que mostra "como seu usuário".
4. **Identidade registrada** no job (tags `crabriks_identity`, `run_as`), no log do app e no resultado da tool mostrado no chat.
5. **Falha do SP ⇒ o job falha.** Sem retry com outra identidade.

## Diferença para o código atual (ver [contratos.md §3](contratos.md))

| Hoje | Política |
| --- | --- |
| OBO primeiro (`default_workspace_client`, `databricks.py` ~L869) | SP do domínio primeiro |
| Falha → SP do app em silêncio (`_call` ~L273, `get_toolset` ~L898) | Falha → erro; fallback OBO só se declarado e aprovado |
| Identidade não aparece no resultado nem no job | Tags no job + `identidade` no resultado + log |
| `databricks.yml` sem escopo de jobs para OBO | Fallback OBO exige adicionar o escopo **ou** fica indisponível |

## Fora do escopo desta política
- Leitura interativa no chat (UC, DBSQL read-only, MCP) continua com o OBO do usuário. A política vale para **criação e execução de jobs**.
- O LLM é chamado com o SP do app (serving endpoint), como hoje.
