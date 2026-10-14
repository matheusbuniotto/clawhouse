# Contrato de job (proposta)

**Status:** proposta preferida, não fechada. Decisão em [ADR-C](adr/C-config-e-contrato-de-job.md). Estado atual em [contratos.md §1](contratos.md).

Fluxo: pedido em linguagem natural → card de aprovação → `jobs_create` → Databricks Job.

## Entradas (o que o agente propõe)

| Campo | Tipo | Regra |
| --- | --- | --- |
| `agent_id` | str | Agente da config que dono do job; tem que ter `jobs` na config |
| `nome` | str | Prefixado pelo runner: `crabriks-<agent_id>-<slug>` |
| `tarefa` | `sql` \| `python` | `agentic` sai (ver ADR-A) |
| `query` / `path` | str | SQL só pode tocar tabelas de `dados.leitura`/`dados.escrita` |
| `schedule` | cron 5 campos ou Quartz | Convertido por `to_quartz_cron`; inválido = erro antes do card |
| `timezone` | IANA | Default `America/Sao_Paulo` (proposta; hoje é `UTC`) |
| `pausado` | bool | Default `false` |
| `expira_em` | data | Default `hoje + jobs.expiracao_padrao_dias` |

## O card de aprovação mostra (obrigatório)
1. **Schedule legível**: "todo dia útil às 09:00 (America/Sao_Paulo)", não só o cron.
2. **Identidade**: "Será criado e executado como **SP `ccf-jobs`**" ou "⚠️ como **seu usuário** (fallback declarado na config)".
3. **Tabelas tocadas**: leitura e escrita, extraídas da query ou do `dados` da config.
4. Agente, owner e expiração.

Sem esses 4 itens o card não é emitido: o turno devolve erro ao modelo (`ModelRetry`).

## Identidade (ver [politica-identidade.md](politica-identidade.md))
- Job criado **e executado** (`run_as`) como o SP do domínio do agente.
- Fallback para o usuário só se `fallback_usuario: true` na config **e** aprovado no card.
- Falha do SP → job **não é criado** e o erro volta ao chat. Sem fallback silencioso.

## Registro no job (tags do Databricks Job)

```text
crabriks_agent_id   = ccf-pix-fracionado
crabriks_identity   = sp:<application_id> | usuario:<email>
crabriks_requested_by = <email de quem aprovou>
crabriks_owner      = <owner da config>
crabriks_expires_at = 2027-01-12
crabriks_config_sha = <commit do agent.yaml>
```

Também vai para o log do app e para o `tool_result` no transcript.

## Saída da tool

```json
{"job_id": 123, "nome": "crabriks-ccf-pix-fracionado-diario",
 "identidade": {"tipo": "service_principal", "label": "ccf-jobs"},
 "schedule": {"quartz": "0 0 9 ? * MON-FRI", "timezone": "America/Sao_Paulo", "legivel": "dias úteis 09:00"},
 "expira_em": "2027-01-12"}
```

## Erros
| Caso | Comportamento |
| --- | --- |
| Agente sem `jobs` na config | Recusa antes do card |
| Tabela fora de `dados` | Recusa antes do card |
| Cron inválido (incl. `dom` e `dow` ambos explícitos) | Recusa antes do card |
| SP indisponível ou sem permissão | Job não é criado; erro com a identidade tentada |
| Card negado | Nada é criado (já é assim hoje) |

## Em aberto
- **Owner de job órfão**: agente removido da config, owner saiu do grupo.
- **Expiração**: pausar ou deletar ao expirar; quem renova.

Ver [riscos.md](riscos.md).
