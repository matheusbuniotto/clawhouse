# Kickoff — Crabriks como agent runner

Pacote de partida. Destino claro; opções preferidas do Arquiteto CCF / Matheus ainda **não fechadas** (fechar = aceitar o ADR + prazo).

## Visão (travada)

Crabriks é o **agent runner central**. Recebe **somente**:

1. **Configs externas** — versionadas em Git, validadas na carga ([config-externa.md](config-externa.md)).
2. **Jobs** — NL → card → `jobs_create` → Databricks Job ([contrato-job.md](contrato-job.md)).
3. **Conexão MCP Databricks** — servers em env, auth com token do usuário.

Lista do que **não** entra: [nao-e-do-crabriks.md](nao-e-do-crabriks.md).

## Escopo Q4 (preferido)

Runner só + 2–3 agentes CCF reais via config + agendamento NL via SP. #92 (UI) em paralelo, fora do OKR. Aceite = smoke #77 + um agente CCF agendado via SP ([ADR-D](adr/D-aceite.md)).

## Issues-âncora

| Issue | Papel |
| --- | --- |
| [#77](https://github.com/matheusbuniotto/crabriks/issues/77) | Epic pydantic-ai nativo + smoke |
| [#92](https://github.com/matheusbuniotto/crabriks/issues/92) | UI OpenClaw 2.0 (paralela, ADR-E) |

#78 é a primeira fatia (caracterização já em `dev` via PR #93).

## Como usar

1. Este README (destino).
2. [contratos.md](contratos.md) — o que o código faz **hoje**.
3. [decisoes-abertas.md](decisoes-abertas.md) A–E — preencher prazos; preferidas em [`adr/`](adr/).
4. Contratos-alvo: [config-externa.md](config-externa.md), [contrato-job.md](contrato-job.md), [politica-identidade.md](politica-identidade.md).
5. [riscos.md](riscos.md) — congela contratos antes de mexer em `turn`/`resume`/`schedules`.
6. [pydantic-ai-harness.md](pydantic-ai-harness.md) antes de tocar em `turn.py` / capabilities.
7. Próxima fatia em [fatias-e-dod.md](fatias-e-dod.md) → um PR pequeno para `dev`.

## Índice

| Doc | Conteúdo |
| --- | --- |
| [contratos.md](contratos.md) | Contratos atuais (código) |
| [config-externa.md](config-externa.md) | Schema proposto `agent.yaml` |
| [contrato-job.md](contrato-job.md) | Contrato de job + card |
| [politica-identidade.md](politica-identidade.md) | SP por domínio |
| [nao-e-do-crabriks.md](nao-e-do-crabriks.md) | Fora do runner |
| [decisoes-abertas.md](decisoes-abertas.md) | A–E com preferidas |
| [adr/](adr/) | ADRs curtos A–E (opções descartadas) |
| [riscos.md](riscos.md) | Riscos + órfãos/expiração |
| [pydantic-ai-harness.md](pydantic-ai-harness.md) | Mapa do harness |
| [fatias-e-dod.md](fatias-e-dod.md) | Ordem + DoD |

## Regras

- PR pequeno → `dev`; testes + lint verdes.
- Comportamento de produção (agendar em NL) só muda com caracterização antes.
- Contrato público muda → Decision Record em `docs/adr/` + atualizar `contratos.md` + nota no Notion.
- Decisão A–E sem prazo → **pare e peça ao Matheus**.
