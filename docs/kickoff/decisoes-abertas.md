# Decisões abertas (A–E)

Cada decisão: o que **já está travado**, a **opção preferida** (Arquiteto CCF / Matheus — ainda **não fechada**), alternativas descartadas (com motivo), quem decide e prazo (preencher no kickoff).

ADRs curtos em [`adr/`](adr/). Fechar = aceitar o ADR + registrar o prazo.

---

## A. Escopo Q4 do runner

**Travado (Matheus):** Crabriks é agent runner e recebe só (1) configs externas, (2) jobs, (3) MCP Databricks.

**Preferida (Arquiteto CCF):** runner só; config versionada; NL → card → `jobs_create`; 2–3 agentes CCF reais. Fora: tools custom por agente, orquestração multi-agente, conectores além do MCP Databricks, lógica CCF no runner. → [ADR-A](adr/A-escopo-q4.md), [nao-e-do-crabriks.md](nao-e-do-crabriks.md).

| Alternativa | Por que descartada |
| --- | --- |
| Plataforma genérica com agents autorados no chat | Isolamento multi-tenant; ADR-0005 adiou |
| Orquestração multi-agente | Fora do Q4 |
| Lógica CCF no código do runner | Viola os 3 inputs |

- **Quem decide:** Matheus.
- **Prazo:** ____

---

## B. Identidade de jobs

**Travado (Matheus):** SP dedicado primeiro; OBO só como fallback explícito (log + chat); sem fallback silencioso.

**Preferida (Arquiteto CCF):** SP **por domínio** (nunca global); fallback OBO só se declarado na config **e** aprovado no card; identidade no job + log; falha do SP ⇒ job falha. → [ADR-B](adr/B-identidade.md), [politica-identidade.md](politica-identidade.md).

| Alternativa | Por que descartada |
| --- | --- |
| SP global = SP do app | Viola "nunca global"; mistura runtime e produção |
| Só OBO | Contraria a regra do Matheus |
| Status quo (OBO → SP app silencioso) | Sem rastreabilidade |

- **Quem decide:** Matheus (+ admin do workspace para o SP do domínio).
- **Prazo:** ____

---

## C. Config externa + contrato de job

**Travado:** agendar = NL → `jobs_create` (protegido); não criar tool `create_schedule` (#90); inteligência no Crabriks, não em `ai_query` no job.

**Preferida (Arquiteto CCF):** `agent.yaml` versionado e validado na carga; contrato de job com card (schedule legível, identidade, tabelas); remover `agentic`; congelar contratos antes de mexer em `turn`/`resume`/`schedules`. → [ADR-C](adr/C-config-e-contrato-de-job.md), [config-externa.md](config-externa.md), [contrato-job.md](contrato-job.md).

| Alternativa | Por que descartada |
| --- | --- |
| Manter `/schedule` + `jobs_create` | Dois caminhos; preferência B1 = depreciar `/schedule` |
| Manter `agentic` | Contraria a visão |
| Refatorar `turn` antes do contrato | Risco R1 |

**Em aberto dentro de C:** owner de jobs órfãos; política de expiração ([riscos.md](riscos.md)).

- **Quem decide:** Matheus.
- **Prazo:** ____

---

## D. Aceite

**Travado:** smoke pós-deploy de #77 (inclui agendar em linguagem natural).

**Preferida (Arquiteto CCF):** smoke #77 **+** um agente CCF real agendado via SP do domínio. → [ADR-D](adr/D-aceite.md).

| Alternativa | Por que descartada |
| --- | --- |
| Só smoke #77 | Não prova SP nem config versionada |
| Aceite = merge de #78–#91 inteiro | Demais; várias issues não bloqueiam o CCF |

- **Quem decide:** Matheus.
- **Prazo:** ____

---

## E. #92 (UI) vs OKR

**Travado:** #92 = visual OpenClaw 2.0, só features existentes.

**Preferida (Arquiteto CCF):** #92 **paralela**, **fora do OKR**, só consome o contrato (não muda identidade, schedule, tags, schema). → [ADR-E](adr/E-ui-paralela.md).

| Alternativa | Por que descartada |
| --- | --- |
| #92 no caminho crítico | Atrasa o agente CCF |
| #92 muda eventos SSE / shape do card | Quebra o contrato congelado |

- **Quem decide:** Matheus.
- **Prazo:** ____
