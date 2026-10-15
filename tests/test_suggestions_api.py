"""Tests for custom agents and composer suggestions API."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic_ai.models.function import FunctionModel

from clawhouse.api.app import create_app
from clawhouse.capabilities.workspace import resolve_agent_workspace
from clawhouse.settings import Settings
from clawhouse.store.store import MemorySessionStore

OWNER = "ada@example.com"
NOW = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)
HEADERS = {
    "x-forwarded-email": OWNER,
    "x-forwarded-access-token": "test-token-ada",
}


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        dev_user=None,
        dev_token=None,
        serving_endpoint=None,
        workspace_host=None,
        agent_root=tmp_path,
    )


@pytest.fixture
def test_app(tmp_path: Path):
    store = MemorySessionStore()

    async def _dummy_stream(_msgs: object, _info: object) -> AsyncIterator[str]:
        if False:
            yield ""

    return create_app(
        store=store,
        settings=_settings(tmp_path),
        model_for=lambda _c, _m: FunctionModel(stream_function=_dummy_stream),  # type: ignore[arg-type]
    )


@pytest.mark.asyncio
async def test_composer_suggestions_slash_prefix(test_app, tmp_path: Path) -> None:
    # Setup a skill in workspace
    workspace = resolve_agent_workspace(tmp_path, "main")
    skill_dir = workspace.skills / "code-review"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text("Review code.", encoding="utf-8")

    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test", headers=HEADERS
    ) as client:
        resp = await client.get("/api/composer/suggestions?prefix=/")
        assert resp.status_code == 200
        data = resp.json()
        assert "commands" in data
        assert "skills" in data
        assert "suggestions" in data
        command_ids = [cmd["id"] for cmd in data["commands"]]
        assert "/compact" in command_ids
        assert "/clear" in command_ids
        assert "/help" in command_ids
        skill_ids = [skill["id"] for skill in data["skills"]]
        assert "/skill:code-review" in skill_ids
        flat_labels = [s["label"] for s in data["suggestions"]]
        assert "/skill:code-review" in flat_labels
        assert "/compact" in flat_labels

        # Also verify frontend type/query param alias
        alias_resp = await client.get("/api/composer/suggestions?type=/&query=sk")
        assert alias_resp.status_code == 200
        alias_data = alias_resp.json()
        assert any(s["insert_text"] == "/skill:code-review" for s in alias_data["suggestions"])


@pytest.mark.asyncio
async def test_composer_suggestions_at_prefix(test_app) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test", headers=HEADERS
    ) as client:
        resp = await client.get("/api/composer/suggestions?prefix=@")
        assert resp.status_code == 200
        data = resp.json()
        assert "agents" in data
        assert "files" in data
        assert "tables" in data
        assert "suggestions" in data
        agent_names = [a["name"] for a in data["agents"]]
        assert "main" in agent_names
        flat_labels = [s["label"] for s in data["suggestions"]]
        assert "main" in flat_labels


@pytest.mark.asyncio
async def test_custom_agents_lifecycle_and_inclusion_in_suggestions(
    test_app, tmp_path: Path
) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test", headers=HEADERS
    ) as client:
        # 1. Create a custom agent with optional context
        create_resp = await client.post(
            "/api/agents",
            json={
                "name": "sql_analyst",
                "description": "SQL and Data Specialist",
                "system_prompt": "You specialize in writing and optimizing SQL queries.",
                "signature_emoji": "📊",
                "context": "Customer and analytics table definitions.",
            },
        )
        assert create_resp.status_code == 201
        created = create_resp.json()
        assert created["name"] == "sql_analyst"
        assert created["signature_emoji"] == "📊"
        agent_id = created["id"]

        # Check physical workspace folder was provisioned
        agent_dir = tmp_path / "claw" / "agents" / "sql_analyst"
        assert agent_dir.is_dir()
        assert (agent_dir / "workspace").is_dir()
        assert (agent_dir / "AGENTS.md").is_file()
        assert (agent_dir / "IDENTITY.md").is_file()
        assert (agent_dir / "CONTEXT.md").read_text(encoding="utf-8") == (
            "Customer and analytics table definitions."
        )

        # 2. List agents
        list_resp = await client.get("/api/agents")
        assert list_resp.status_code == 200
        agents = list_resp.json()
        agent_names = [a["name"] for a in agents]
        assert "main" in agent_names
        assert "sql_analyst" in agent_names

        # 3. Check @ suggestions include the custom agent
        sug_resp = await client.get("/api/composer/suggestions?prefix=@")
        assert sug_resp.status_code == 200
        sug_data = sug_resp.json()
        sug_agents = [a["name"] for a in sug_data["agents"]]
        assert "sql_analyst" in sug_agents

        # 4. Delete the custom agent
        del_resp = await client.delete(f"/api/agents/{agent_id}")
        assert del_resp.status_code == 204

        # 5. Confirm deletion from store and workspace
        list_resp_2 = await client.get("/api/agents")
        agent_names_2 = [a["name"] for a in list_resp_2.json()]
        assert "sql_analyst" not in agent_names_2
        assert not agent_dir.exists()
