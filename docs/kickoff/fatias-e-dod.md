# Fatias e Definition of Done

## Ordem (caminho crítico → aceite D)

| # | Fatia | Issue / artefato | Depende de | Contrato público? |
| --- | --- | --- | --- | --- |
| 1 | Caracterização `jobs_create` | #78 passo 1 (PR #93, já em `dev`) | — | Não |
| 2 | Congelar schema `agent.yaml` + contrato de job (docs + loader stub) | ADR-C | Decisão C | **Sim** (schema) |
| 3 | Remover `agentic` / `ai_query` | `feat/platform-agent-jobs` | Decisão A/C | **Sim** (`jobs_create`) |
| 4 | Identidade: SP por domínio → OBO só se config+card | #78 passo 2 | Decisão B, fatia 2 | **Sim** (`identity`, secrets) |
| 5 | Card: schedule legível + identidade + tabelas | #78 / #82 | fatias 2–4 | **Sim** (payload do card) |
| 6 | Token via deps, sem mutação | #80 | fatia 1 | Não |
| 7 | Destino `/schedule` (preferência: depreciar) | #78 passo 3 + #90 | Decisão C | **Sim** se remover |
| 8 | Um agente CCF real via SP (aceite D) | — | fatias 2–5 | Demo |
| 9 | Restante #77 (#79, #81–#89, #91) | #77 | fatia 6+ | Por fatia |
| UI | Visual OpenClaw 2.0 | #92 | ADR-E | Não (só visual) |

**Não** mexer em `turn.py` / `resume_turn` / `schedules.py` antes das fatias 2–5 (risco R1).

## Aceite D (fechamento do pacote)

1. Checklist smoke de #77 completo.
2. Um agente CCF real (config versionada) agendado via SP: card correto; job com tags `crabriks_*`; run dispara como o SP.

Detalhe: [ADR-D](adr/D-aceite.md).

## Definition of Done (toda fatia)

- [ ] **Testes:** caracterização do comportamento afetado antes da mudança; testes novos com valores exatos; `uv run pytest` verde.
- [ ] **Qualidade:** `ruff check .`, `ruff format --check .`, `complexipy src --max-complexity-allowed 15`, `pyright` (`Makefile`).
- [ ] **PR:** pt-BR, "Parte de #NN", o que muda / o que não muda; CI verde; sem merge próprio sem aprovação.
- [ ] **Decision Record** se o contrato público mudar (`docs/adr/NNNN-*.md` + atualizar [contratos.md](contratos.md)). Conta: assinatura/resultado de tool, env/config, rota HTTP, evento SSE, identidade, schema `agent.yaml`.
- [ ] **Nota no Notion** (3–5 linhas): o que mudou, PR, ADR, como validar.
- [ ] **Smoke pós-deploy** (#77). Fatias de jobs: NL → card (schedule legível + identidade + tabelas) → job em Workflows → dispara → chat mostra a identidade.

## Quando parar e escalar

- Fatia depende de A–E sem prazo.
- Caracterização precisaria mudar para a fatia passar (= mudança de comportamento).
- CI exige secret/permissão nova no workspace.
