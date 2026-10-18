"""Agent creation capability and tools for custom workspace agents."""

from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import uuid4

from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.toolsets import AgentToolset, FunctionToolset

from clawhouse.agent.core import TurnDeps
from clawhouse.capabilities.workspace import (
    UnsafeAgentName,
    WorkspacePaths,
    provision_agent_workspace,
)
from clawhouse.store.shapes import CustomAgent
from clawhouse.store.store import SessionStore


@dataclass(frozen=True, slots=True)
class CreatedAgentResult:
    """Typed result boundary for agent creation."""

    id: str
    name: str
    description: str
    signature_emoji: str
    workspace_directory: str | None = None
    error: str | None = None


def resolve_workspace_root(
    workspace: WorkspacePaths | None,
    explicit_root: Path | None = None,
) -> Path | None:
    """Resolve the repository or workspace root without fragile direct assumption."""
    if explicit_root is not None:
        return explicit_root
    if workspace is not None and len(workspace.directory.parents) >= 3:
        return workspace.directory.parents[2]
    return None


async def _check_existing(
    store: SessionStore, owner_id: str, name: str
) -> CreatedAgentResult | None:
    existing_agents = await store.list_custom_agents(owner_id)
    existing = next((a for a in existing_agents if a.name.lower() == name.lower()), None)
    if existing is None:
        return None
    return CreatedAgentResult(
        id=existing.id,
        name=existing.name,
        description=existing.description,
        signature_emoji=existing.signature_emoji,
        error=f"Agent '{existing.name}' already exists for this user.",
    )


def _provision_dir(  # noqa: PLR0913
    root: Path | None,
    name: str,
    system_prompt: str,
    *,
    emoji: str,
    soul: str | None,
    context: str | None,
) -> tuple[str | None, str | None]:
    if root is None:
        return None, None
    try:
        paths = provision_agent_workspace(
            root=root,
            agent_name=name,
            agents_text=system_prompt,
            identity_name=name,
            signature_emoji=emoji,
            soul_text=soul,
            context_text=context,
        )
        return paths.directory.as_posix(), None
    except UnsafeAgentName:
        return None, f"Invalid agent name '{name}': must be a safe path segment."


@dataclass
class AgentManagementCapability(AbstractCapability[TurnDeps]):
    """Capability exposing in-chat agent creation and folder provisioning."""

    store: SessionStore
    owner_id: str
    workspace: WorkspacePaths | None = None
    workspace_root: Path | None = None

    def get_toolset(self) -> AgentToolset[TurnDeps] | None:
        store = self.store
        owner_id = self.owner_id
        workspace = self.workspace
        root = resolve_workspace_root(workspace, self.workspace_root)

        async def create_agent(  # noqa: PLR0913
            name: str,
            description: str,
            system_prompt: str,
            *,
            signature_emoji: str = "🤖",
            soul: str | None = None,
            context: str | None = None,
        ) -> dict[str, object]:
            """Create a new custom agent and provision its workspace."""
            if existing := await _check_existing(store, owner_id, name):
                return asdict(existing)

            dir_path, err = _provision_dir(
                root, name, system_prompt, emoji=signature_emoji, soul=soul, context=context
            )
            if err is not None:
                return asdict(CreatedAgentResult("", name, description, signature_emoji, error=err))

            agent = CustomAgent(
                id=str(uuid4()),
                owner_id=owner_id,
                name=name,
                description=description,
                system_prompt=system_prompt,
                signature_emoji=signature_emoji,
            )
            created = await store.create_custom_agent(agent)
            return asdict(
                CreatedAgentResult(
                    id=created.id,
                    name=created.name,
                    description=created.description,
                    signature_emoji=created.signature_emoji,
                    workspace_directory=dir_path,
                )
            )

        return FunctionToolset([create_agent])
