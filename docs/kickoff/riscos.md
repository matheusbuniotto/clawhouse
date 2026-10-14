# Riscos

| # | Risco | Mitigação |
| --- | --- | --- |
| R1 | Refatorar `turn`/`resume`/`schedules` quebra o agendamento que funciona hoje | **Congelar os contratos de config e de job antes** de tocar em `turn.py`, `resume_turn` e `schedules.py`. Testes de caracterização são a rede de segurança (PR #93 para `jobs_create`; criar os de `turn`/`resume` antes de #79/#83) |
| R2 | Card de aprovação sem contexto suficiente → aprovação às cegas | Card **obrigatoriamente** mostra schedule legível, identidade e tabelas tocadas ([contrato-job.md](contrato-job.md)) |
| R3 | Job criado com identidade errada (hoje: SP do app em silêncio) | [politica-identidade.md](politica-identidade.md); falha do SP = falha do job |
| R4 | `jobs.create` via OBO falha por falta de escopo em `databricks.yml` | Confirmar em prod; fallback OBO só se o escopo for adicionado |
| R5 | Bug de cron `dom`+`dow` gera Quartz inválido | Validar antes do card; teste já pina o comportamento atual |
| R6 | Config inválida descoberta em runtime | Validação na carga ([config-externa.md](config-externa.md)) |
| R7 | #92 (UI) disputa o mesmo código do chat | #92 só consome o contrato; não muda eventos SSE nem tools |

## Em aberto (sem dono ainda)
- **Owner de jobs órfãos**: o agente sai da config, o owner sai do grupo, ou o usuário que aprovou o fallback OBO sai da empresa. Proposta inicial: o `owner` da config herda; sem owner → pausar e alertar.
- **Expiração**: ao expirar, pausar ou deletar? Quem renova e por qual fluxo (card de renovação?)?
