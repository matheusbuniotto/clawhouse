"""Agent creation capability and tools for custom workspace agents."""

from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import uuid4

from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.toolsets import AgentToolset, FunctionToolset

from crabriks.agent.core import TurnDeps
from crabriks.capabilities.workspace import (
    UnsafeAgentName,
    WorkspacePaths,
    provision_agent_workspace,
)
from crabriks.store.shapes import CustomAgent
from crabriks.store.store import SessionStore


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
            # UNWANT-01: Check for existing agent name to prevent duplicates
            existing_agents = await store.list_custom_agents(owner_id)
            if any(a.name.lower() == name.lower() for a in existing_agents):
                res = CreatedAgentResult(
                    id="",
                    name=name,
                    description=description,
                    signature_emoji=signature_emoji,
                    error=f"Agent '{name}' already exists for this user.",
                )
                return asdict(res)

            provisioned_dir: str | None = None
            if root is not None:
                try:
                    paths = provision_agent_workspace(
                        root=root,
                        agent_name=name,
                        agents_text=system_prompt,
                        identity_name=name,
                        signature_emoji=signature_emoji,
                        soul_text=soul,
                        context_text=context,
                    )
                    provisioned_dir = paths.directory.as_posix()
                except UnsafeAgentName:
                    res = CreatedAgentResult(
                        id="",
                        name=name,
                        description=description,
                        signature_emoji=signature_emoji,
                        error=f"Invalid agent name '{name}': must be a safe path segment.",
                    )
                    return asdict(res)

            agent_id = str(uuid4())
            agent = CustomAgent(
                id=agent_id,
                owner_id=owner_id,
                name=name,
                description=description,
                system_prompt=system_prompt,
                signature_emoji=signature_emoji,
            )
            created = await store.create_custom_agent(agent)
            res = CreatedAgentResult(
                id=created.id,
                name=created.name,
                description=created.description,
                signature_emoji=created.signature_emoji,
                workspace_directory=provisioned_dir,
            )
            return asdict(res)

        return FunctionToolset([create_agent])
