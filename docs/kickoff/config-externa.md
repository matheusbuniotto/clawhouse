# Schema da config externa (proposta)

**Status:** proposta preferida (Arquiteto CCF), não fechada. Decisão em [ADR-C](adr/C-config-e-contrato-de-job.md).

## Princípios
- **Uma pasta por agente, versionada em Git**: `claw/agents/<agent_id>/`, a mesma raiz de hoje (ADR-0005; `resolve_agent_workspace` em `src/crabriks/api/app.py` ~L275).
- **Validada na carga.** Config inválida derruba o boot ou rejeita o agente com erro claro. Nunca vira erro em runtime no meio de um turno.
- **Sem lógica de negócio.** Só referências: tabelas, MCP, schedule, identidade, prompts em markdown.
- Reaproveita os validadores que já existem: `MCPServerConfig` (https, nome único, timeout > 0) em `src/crabriks/capabilities/mcp.py` e `ModelEntry` em `src/crabriks/settings.py`.

## Arquivo: `claw/agents/<agent_id>/agent.yaml`

```yaml
schema_version: 1                  # obrigatório; o loader rejeita versões desconhecidas
id: ccf-pix-fracionado             # slug único; igual ao nome da pasta
dominio: ccf                       # usado para escolher o SP (política de identidade)
owner: time-ccf@empresa            # grupo dono; recebe jobs órfãos
descricao: "Analisa alertas de PIX fracionado em conta nova."

modelo: databricks                 # id de CRABRIKS_MODELS / SERVING_ENDPOINT (ModelEntry.id)

prompts:                           # arquivos markdown da própria pasta (padrão atual do main)
  agents: AGENTS.md
  soul: SOUL.md                    # opcional
skills: skills/                    # opcional; lido por pydantic_ai_harness.Skills

dados:                             # o que o agente pode tocar; o card mostra esta lista
  leitura: [ccf.alertas.pix, ccf.cadastro.contas]
  escrita: [ccf.analises.saida]

mcp:                               # só servers declarados em CRABRIKS_MCP_SERVERS
  - databricks-uc

jobs:
  identidade:
    service_principal: ${secret:ccf/jobs-sp-client-id}   # SP do domínio; nunca global
    fallback_usuario: false        # true só se declarado aqui E aprovado no card
  agendamentos_permitidos: true
  expiracao_padrao_dias: 90        # job sem renovação expira (ver riscos)
```

## Modelo pydantic (esboço, para `src/crabriks/config/agent.py`)

```python
class JobsIdentityConfig(BaseModel, frozen=True):
    service_principal: str                  # referência a secret, não o valor
    fallback_usuario: bool = False

class JobsConfig(BaseModel, frozen=True):
    identidade: JobsIdentityConfig
    agendamentos_permitidos: bool = True
    expiracao_padrao_dias: PositiveInt = 90

class DadosConfig(BaseModel, frozen=True):
    leitura: tuple[str, ...] = ()           # catalog.schema.table
    escrita: tuple[str, ...] = ()

class AgentConfig(BaseModel, frozen=True):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1]
    id: str = Field(pattern=r"^[a-z0-9-]+$")
    dominio: str
    owner: str
    descricao: str
    modelo: str
    prompts: dict[str, str]
    skills: str | None = None
    dados: DadosConfig = DadosConfig()
    mcp: tuple[str, ...] = ()
    jobs: JobsConfig | None = None
```

### Validações na carga (além do tipo)
- `id` é igual ao nome da pasta.
- `modelo` existe em `Settings.models`.
- Cada item de `mcp` existe em `Settings.mcp_servers`.
- Arquivos de `prompts` existem.
- Nomes de tabela têm 3 partes.
- `jobs.identidade.service_principal` resolve para um secret existente.
- SP não pode ser compartilhado entre domínios.

## O que sai do código atual
- `crabriks.custom_agents` (Lakebase) e `create_agent`: agentes criados pelo chat **não** são config versionada. Ficam como rascunho; nunca rodam em job (ver [nao-e-do-crabriks.md](nao-e-do-crabriks.md)).
- Configs por env (`CRABRIKS_MODELS`, `CRABRIKS_MCP_SERVERS`) continuam sendo **catálogo da plataforma**. O `agent.yaml` só referencia ids desse catálogo.
