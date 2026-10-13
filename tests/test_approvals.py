import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic_ai import RunContext
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.toolsets import AbstractToolset, ToolsetTool
from pydantic_core import SchemaValidator, core_schema

from crabriks.app import create_app
from crabriks.identity import Caller
from crabriks.mcp import MCPServerConfig
from crabriks.model import MissingAccessToken
from crabriks.settings import Settings, sensitive_tools_from_env
from crabriks.shapes import TranscriptEntry
from crabriks.store import (
    ApprovalAlreadyResolved,
    ApprovalNotFound,
    ApprovalPending,
    MemorySessionStore,
)
from crabriks.turn import ApprovalNotice, TurnContext, resume_turn, run_turn
from crabriks.workspace import resolve_agent_workspace

OWNER = "ada@example.com"
OTHER = "grace@example.com"
NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
SESSION_ID = "55555555-5555-4555-8555-555555555555"

HEADERS = {
    "x-forwarded-email": "ada@example.com",
    "x-forwarded-access-token": "auth_header_ada",
}
OTHER_HEADERS = {
    "x-forwarded-email": "grace@example.com",
    "x-forwarded-access-token": "auth_header_grace",
}


class _QueryToolset(AbstractToolset[object]):
    """One argument-bearing tool, so an approval can carry a secret in its arguments."""

    @property
    def id(self) -> str:
        return "notes"

    async def get_tools(self, ctx: RunContext[object]) -> dict[str, ToolsetTool[object]]:
        del ctx
        name = "lookup"
        definition = ToolDefinition(
            name=name,
            description="Look up a note.",
            parameters_json_schema={"type": "object"},
        )
        return {
            name: ToolsetTool(
                toolset=self,
                tool_def=definition,
                max_retries=1,
                args_validator=SchemaValidator(core_schema.dict_schema()),
            )
        }

    async def call_tool(
        self,
        name: str,
        tool_args: dict[str, object],
        ctx: RunContext[object],
        tool: ToolsetTool[object],
    ) -> str:
        del name, tool_args, ctx, tool
        return "ok"

    async def list_tools(self) -> list[object]:
        return [type("Tool", (), {"name": "lookup", "description": "Look up a note."})()]


def _reply(text: str):
    async def stream(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str]:
        del messages, info
        yield text

    return stream


def _app(
    store: MemorySessionStore,
    model: object,
    sensitive_tools: tuple[str, ...] = (),
) -> object:
    settings = Settings(
        dev_user=None,
        dev_token=None,
        serving_endpoint=None,
        workspace_host=None,
        sensitive_tools=sensitive_tools,
    )

    def model_for(caller: Caller, model_id: str | None) -> object:
        del model_id
        if not caller.access_token:
            raise MissingAccessToken
        return model

    return create_app(settings=settings, model_for=model_for, store=store)  # type: ignore[arg-type]


def _client(app: object) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")  # type: ignore[arg-type]


async def test_approvals_lifecycle_in_memory_store() -> None:
    store = MemorySessionStore()
    session = await store.create_session(OWNER)
    run_id = await store.claim_run(session.id)

    # Initially no pending approvals
    assert await store.has_pending_approval(session.id) is False

    # Create pending approval
    approval = await store.create_approval(
        session_id=session.id,
        run_id=run_id,
        tool_name="delete_database",
        tool_call_id="call-del-1",
        arguments='{"name": "production"}',
    )
    assert approval.status == "pending"
    assert approval.tool_name == "delete_database"
    assert approval.arguments == '{"name": "production"}'
    assert approval.session_id == session.id
    assert approval.run_id == run_id
    assert approval.resolved_at is None
    assert approval.resolved_by is None

    # Now pending approval exists
    assert await store.has_pending_approval(session.id) is True

    # Finish current run as pending_approval
    await store.finish_run(session.id, run_id, "pending_approval")

    # Trying to claim a new run while approval is pending raises ApprovalPending
    with pytest.raises(ApprovalPending):
        await store.claim_run(session.id)

    # List approvals for owner
    listed = await store.list_approvals(OWNER)
    assert len(listed) == 1
    assert listed[0].id == approval.id
    assert listed[0].status == "pending"

    # Other owner sees nothing
    assert await store.list_approvals(OTHER) == ()

    # Get approval
    fetched = await store.get_approval(approval.id)
    assert fetched.id == approval.id

    # Resolve approval
    resolved = await store.resolve_approval(
        approval_id=approval.id,
        status="approved",
        resolver_id=OWNER,
        resolved_at=NOW,
    )
    assert resolved.status == "approved"
    assert resolved.resolved_by == OWNER
    assert resolved.resolved_at == NOW

    # Now no pending approvals remain
    assert await store.has_pending_approval(session.id) is False

    # Second resolve fails
    with pytest.raises(ApprovalAlreadyResolved):
        await store.resolve_approval(
            approval_id=approval.id,
            status="denied",
            resolver_id=OWNER,
            resolved_at=NOW,
        )

    # Claiming run now succeeds
    new_run_id = await store.claim_run(session.id)
    assert new_run_id != run_id


async def test_get_nonexistent_approval_raises_not_found() -> None:
    store = MemorySessionStore()
    with pytest.raises(ApprovalNotFound):
        await store.get_approval("00000000-0000-0000-0000-000000000000")


async def test_sensitive_tool_call_pauses_turn_and_creates_pending_approval() -> None:
    store = MemorySessionStore()
    emitted: list[object] = []

    async def call_sensitive(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        del messages, info
        yield {
            0: DeltaToolCall(
                name="clock",
                json_args="{}",
                tool_call_id="call-clk",
            )
        }

    async def capture(notice: object) -> None:
        emitted.append(notice)

    ctx = TurnContext(
        owner_id=OWNER,
        store=store,
        model=FunctionModel(stream_function=call_sensitive),
        now=lambda: NOW,
        sensitive_tools=("clock",),
        emit=capture,  # type: ignore[arg-type]
    )

    result = await run_turn(SESSION_ID, "what time is it?", ctx=ctx)

    assert result.status == "pending_approval"
    assert result.approval_id is not None
    assert result.reply == ""
    assert result.error is None
    assert len(result.transcript) == 2
    assert result.transcript[0] == TranscriptEntry(role="user", content="what time is it?")
    assert result.transcript[1] == TranscriptEntry(
        role="tool_call",
        content="{}",
        tool_name="clock",
        tool_call_id="call-clk",
    )

    # Check store pending approval
    approval = await store.get_approval(result.approval_id)
    assert approval.status == "pending"
    assert approval.tool_name == "clock"
    assert approval.tool_call_id == "call-clk"
    assert await store.has_pending_approval(SESSION_ID) is True

    # Check notice emitted
    approval_notices = [n for n in emitted if isinstance(n, ApprovalNotice)]
    assert len(approval_notices) == 1
    assert approval_notices[0].approval_id == result.approval_id
    assert approval_notices[0].name == "clock"

    # Attempting to start another turn on the session raises ApprovalPending (NO BYPASS!)
    with pytest.raises(ApprovalPending):
        await run_turn(SESSION_ID, "another message", ctx=ctx)

    # Now resume with approval
    async def reply_after_clock(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str]:
        del messages, info
        yield "The time is 2026-10-10T12:00:00Z"

    resume_ctx = TurnContext(
        owner_id=OWNER,
        store=store,
        model=FunctionModel(stream_function=reply_after_clock),
        now=lambda: NOW,
        sensitive_tools=("clock",),
    )

    resumed = await resume_turn(SESSION_ID, result.approval_id, "approved", ctx=resume_ctx)
    assert resumed.status == "ok"
    assert resumed.reply == "The time is 2026-10-10T12:00:00Z"
    roles = [e.role for e in resumed.transcript]
    assert roles == ["user", "tool_call", "tool_result", "assistant"]
    assert resumed.transcript[2].role == "tool_result"
    assert resumed.transcript[2].content == "2026-10-10T12:00:00Z"
    assert await store.has_pending_approval(SESSION_ID) is False


async def test_deny_resumes_run_without_executing_tool() -> None:
    store = MemorySessionStore()

    async def call_sensitive(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        del messages, info
        yield {
            0: DeltaToolCall(
                name="clock",
                json_args="{}",
                tool_call_id="call-clk",
            )
        }

    ctx = TurnContext(
        owner_id=OWNER,
        store=store,
        model=FunctionModel(stream_function=call_sensitive),
        now=lambda: NOW,
        sensitive_tools=("clock",),
    )

    paused = await run_turn(SESSION_ID, "what time is it?", ctx=ctx)
    assert paused.status == "pending_approval"
    approval_id = paused.approval_id
    assert approval_id is not None

    # Resume with denial
    async def reply_after_deny(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str]:
        # Verify model sees the denial message
        tool_returns = [
            getattr(p, "content", "")
            for m in messages
            for p in m.parts
            if getattr(p, "part_kind", "") == "tool-return"
        ]
        assert len(tool_returns) == 1
        assert "denied" in tool_returns[0].lower()
        yield "Understood, I will not execute the clock tool."

    resume_ctx = TurnContext(
        owner_id=OWNER,
        store=store,
        model=FunctionModel(stream_function=reply_after_deny),
        now=lambda: NOW,
        sensitive_tools=("clock",),
    )

    resumed = await resume_turn(SESSION_ID, approval_id, "denied", ctx=resume_ctx)
    assert resumed.status == "ok"
    assert resumed.reply == "Understood, I will not execute the clock tool."
    roles = [e.role for e in resumed.transcript]
    assert roles == ["user", "tool_call", "tool_result", "assistant"]
    assert "denied" in resumed.transcript[2].content.lower()

    # Store approval is marked denied
    app = await store.get_approval(approval_id)
    assert app.status == "denied"
    assert await store.has_pending_approval(SESSION_ID) is False


async def test_secrets_scrubbed_from_approval_arguments() -> None:
    store = MemorySessionStore()
    user_token = "cred_" + "payload_value"

    async def call_sensitive(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        del messages, info
        yield {
            0: DeltaToolCall(
                name="notes__lookup",
                json_args=f'{{"query": "{user_token}"}}',
                tool_call_id="call-skill",
            )
        }

    def factory(server: MCPServerConfig, token: str) -> AbstractToolset[object]:
        del server, token
        return _QueryToolset()

    emitted: list[object] = []

    async def capture(notice: object) -> None:
        emitted.append(notice)

    ctx = TurnContext(
        owner_id=OWNER,
        store=store,
        model=FunctionModel(stream_function=call_sensitive),
        now=lambda: NOW,
        sensitive_tools=("notes__lookup",),
        user_token=user_token,
        mcp_servers=(MCPServerConfig(name="notes", url="https://notes.example/mcp"),),
        mcp_toolset_factory=factory,
        emit=capture,  # type: ignore[arg-type]
    )

    result = await run_turn(SESSION_ID, "run sensitive tool", ctx=ctx)
    assert result.status == "pending_approval"
    approval_id = result.approval_id
    assert approval_id is not None
    approval = await store.get_approval(approval_id)
    assert user_token not in approval.arguments
    assert "[REDACTED]" in approval.arguments
    assert user_token not in "".join(entry.content for entry in result.transcript)
    assert user_token not in "".join(str(notice) for notice in emitted)

    # Verify resume restores user token in ToolCallPart
    seen_tool_call_args: list[object] = []

    async def reply_after_approval(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str]:
        del info
        for m in messages:
            for p in getattr(m, "parts", []):
                if getattr(p, "part_kind", "") == "tool-call":
                    seen_tool_call_args.append(getattr(p, "args", ""))
        yield "skill executed"

    resume_ctx = TurnContext(
        owner_id=OWNER,
        store=store,
        model=FunctionModel(stream_function=reply_after_approval),
        now=lambda: NOW,
        sensitive_tools=("notes__lookup",),
        user_token=user_token,
        mcp_servers=(MCPServerConfig(name="notes", url="https://notes.example/mcp"),),
        mcp_toolset_factory=factory,
    )
    resumed = await resume_turn(SESSION_ID, approval_id, "approved", ctx=resume_ctx)
    assert resumed.status == "ok"
    assert len(seen_tool_call_args) == 1
    assert user_token in str(seen_tool_call_args[0])
    assert "[REDACTED]" not in str(seen_tool_call_args[0])


async def test_approvals_page_requires_signed_in_user() -> None:
    app = _app(MemorySessionStore(), FunctionModel(stream_function=_reply("ok")))
    async with _client(app) as client:
        missing = await client.get("/approvals")
        page = await client.get("/approvals", headers=HEADERS)

    assert missing.status_code == 401
    assert page.status_code == 200
    assert "Crabriks" in page.text
    assert 'src="/boot.js"' in page.text
    assert 'id="rail"' in page.text


async def test_approvals_api_lifecycle_and_guardrails() -> None:
    store = MemorySessionStore()

    async def call_sensitive(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        del messages, info
        yield {
            0: DeltaToolCall(
                name="clock",
                json_args="{}",
                tool_call_id="call-clk",
            )
        }

    app = _app(store, FunctionModel(stream_function=call_sensitive), sensitive_tools=("clock",))

    async with _client(app) as client:
        # Trigger sensitive turn
        turn_resp = await client.post(
            f"/api/sessions/{SESSION_ID}/turns",
            headers=HEADERS,
            json={"message": "check time"},
        )
        assert turn_resp.status_code == 200
        # Check SSE stream contents
        assert "approval_required" in turn_resp.text
        assert "pending_approval" in turn_resp.text

        # List approvals
        list_resp = await client.get("/api/approvals", headers=HEADERS)
        assert list_resp.status_code == 200
        data = list_resp.json()
        assert len(data["pending"]) == 1
        assert len(data["history"]) == 0
        approval_id = data["pending"][0]["id"]
        assert data["pending"][0]["tool_name"] == "clock"

        # Other caller sees nothing
        other_list = await client.get("/api/approvals", headers=OTHER_HEADERS)
        assert other_list.status_code == 200
        assert other_list.json()["pending"] == []

        # Attempt to bypass by sending another turn -> 409
        bypass_resp = await client.post(
            f"/api/sessions/{SESSION_ID}/turns",
            headers=HEADERS,
            json={"message": "skip approval"},
        )
        assert bypass_resp.status_code == 409
        assert "pending approval" in bypass_resp.json()["error"].lower()

        # Foreign user cannot approve
        forbidden_resp = await client.post(
            f"/api/approvals/{approval_id}/approve",
            headers=OTHER_HEADERS,
        )
        assert forbidden_resp.status_code == 403

        # Now approve with owner
        async def reply_after_approval(
            messages: list[ModelMessage], info: AgentInfo
        ) -> AsyncIterator[str]:
            del messages, info
            yield "Resumed and completed!"

        # Swap model to stream reply
        app.state.model_for = lambda _c, _m: FunctionModel(  # type: ignore[attr-defined]
            stream_function=reply_after_approval
        )

        approve_resp = await client.post(
            f"/api/approvals/{approval_id}/approve",
            headers=HEADERS,
        )
        assert approve_resp.status_code == 200
        body = approve_resp.json()
        assert body["status"] == "ok"
        assert body["reply"] == "Resumed and completed!"
        assert body["approval"]["status"] == "approved"

        # List approvals now shows in history
        list_after = await client.get("/api/approvals", headers=HEADERS)
        data_after = list_after.json()
        assert len(data_after["pending"]) == 0
        assert len(data_after["history"]) == 1
        assert data_after["history"][0]["status"] == "approved"

        # Trying to approve already resolved approval returns 409
        repeat_resp = await client.post(
            f"/api/approvals/{approval_id}/approve",
            headers=HEADERS,
        )
        assert repeat_resp.status_code == 409


def test_malformed_sensitive_tools_env_fails_closed() -> None:
    with pytest.raises(json.JSONDecodeError):
        sensitive_tools_from_env({"CRABRIKS_SENSITIVE_TOOLS": '["unclosed_string'})

    with pytest.raises(ValueError):
        sensitive_tools_from_env({"CRABRIKS_SENSITIVE_TOOLS": '{"invalid": "not_a_list"}'})

    with pytest.raises(ValueError):
        sensitive_tools_from_env({"CRABRIKS_SENSITIVE_TOOLS": "[1, {}]"})


def test_documented_sensitive_tools_values_parse() -> None:
    assert sensitive_tools_from_env(
        {"CRABRIKS_SENSITIVE_TOOLS": "bash,delete_file,drop_table"}
    ) == ("bash", "delete_file", "drop_table")
    assert sensitive_tools_from_env({"CRABRIKS_SENSITIVE_TOOLS": '["bash", "drop_table"]'}) == (
        "bash",
        "drop_table",
    )
    assert sensitive_tools_from_env({}) == ()


async def test_non_sensitive_tool_runs_without_an_approval_row() -> None:
    store = MemorySessionStore()

    async def call_clock(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        del info
        returned = any(
            getattr(part, "part_kind", "") == "tool-return" for m in messages for part in m.parts
        )
        if not returned:
            yield {0: DeltaToolCall(name="clock", json_args="{}", tool_call_id="call-clk")}
            return
        yield "done"

    result = await run_turn(
        SESSION_ID,
        "what time is it?",
        ctx=TurnContext(
            owner_id=OWNER,
            store=store,
            model=FunctionModel(stream_function=call_clock),
            now=lambda: NOW,
        ),
    )

    assert result.status == "ok"
    assert result.transcript[2].content == "2026-10-10T12:00:00Z"
    assert await store.list_approvals(OWNER) == ()


async def test_sensitive_skill_load_pauses_through_the_shared_hook(tmp_path: Path) -> None:
    paths = resolve_agent_workspace(tmp_path, "main")
    skill = paths.skills / "sql"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: sql\ndescription: Run a warehouse query.\n---\n# SQL\nBody.\n",
        encoding="utf-8",
    )
    store = MemorySessionStore()

    async def load_skill(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        del info
        returned = any(
            getattr(part, "part_kind", "") == "tool-return" for m in messages for part in m.parts
        )
        if returned:
            yield "loaded without a pause"
            return
        yield {
            0: DeltaToolCall(
                name="load_capability",
                json_args='{"id": "sql"}',
                tool_call_id="call-sql",
            )
        }

    result = await run_turn(
        SESSION_ID,
        "load sql",
        ctx=TurnContext(
            owner_id=OWNER,
            store=store,
            model=FunctionModel(stream_function=load_skill),
            now=lambda: NOW,
            workspace=paths,
            sensitive_tools=("load_capability",),
        ),
    )

    assert result.status == "pending_approval"
    assert result.approval_id is not None
    pending = await store.list_approvals(OWNER)
    assert [(row.tool_name, row.status) for row in pending] == [("load_capability", "pending")]
    assert [entry.role for entry in result.transcript] == ["user", "tool_call"]
