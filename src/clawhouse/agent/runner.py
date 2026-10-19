"""Model execution, capability assembly per agent, and prompt assembly."""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace

from pydantic_ai import DeferredToolRequests
from pydantic_ai.capabilities import AbstractCapability, AgentCapability, ProcessHistory
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.tools import DeferredToolResults
from pydantic_ai.toolsets import AgentToolset, FunctionToolset
from pydantic_ai_harness.compaction import ReportContextUsage

from clawhouse.agent.commands import Command, CommandContext, dispatch_command, parse_command
from clawhouse.agent.core import TurnDeps, clawhouse_agent, format_utc
from clawhouse.agent.events import (
    _append,
    _append_user,
    _persist_and_emit,
    _publish,
)
from clawhouse.agent.history import (
    drop_unreturned_tool_calls,
    foreign_tool_filter,
    load_session_history,
)
from clawhouse.agent.notices import (
    AgentNotice,
    Resolution,
    TurnResult,
    WarningNotice,
    _Claimed,
    _Queue,
)
from clawhouse.agent.pauses import (
    _deferred_results,
    _handle_deferred_approvals,
    _sensitive_tool_guard,
)
from clawhouse.agent.prompt import RuntimeMeta, SystemPrompt, build_system_prompt
from clawhouse.agent.roster import (
    ActiveAgent,
    choose_agent,
    find_agent,
    missing_agent_warning,
    session_default,
)
from clawhouse.capabilities.agent_tools import AgentManagementCapability
from clawhouse.capabilities.bootstrap import (
    BootstrapContext,
    load_bootstrap,
    load_bootstrap_directives,
)
from clawhouse.capabilities.interaction import InteractionCapability
from clawhouse.capabilities.mcp import MCPCapability, mcp_capability, scrub_token
from clawhouse.capabilities.mentions import (
    MemoryCapability,
    format_memory_block,
    resolve_mention_bundles,
    tiered_compaction,
)
from clawhouse.capabilities.sheets import GoogleSheetsCapability
from clawhouse.capabilities.skills import skills_capability
from clawhouse.capabilities.workspace import (
    UnsafeAgentName,
    WorkspacePaths,
    resolve_agent_workspace,
)
from clawhouse.store.shapes import ApprovalEntry, TranscriptEntry, UserProfile
from clawhouse.store.store import SessionStore
from clawhouse.telemetry import record_turn_agent

logger = logging.getLogger("clawhouse.turn")
_load_session_history = load_session_history


def is_wake_up_message(text: str) -> bool:
    c = text.strip().lower()
    return c.startswith("wake up, my friend") or c in ("wake up my friend", "wake up")


@dataclass
class HatchCapability(AbstractCapability[TurnDeps]):
    """Attached during the birth sequence ritual to persist caller's profile."""

    store: SessionStore
    owner_id: str

    def get_toolset(self) -> AgentToolset[TurnDeps] | None:
        async def save_profile(
            assistant_name: str,
            signature_emoji: str,
            user_directives: str,
        ) -> str:
            profile = UserProfile(
                user_id=self.owner_id,
                assistant_name=assistant_name,
                signature_emoji=signature_emoji,
                user_directives=user_directives,
                hatched=True,
            )
            await self.store.save_user_profile(profile)
            return (
                f"Saved profile for {self.owner_id}: assistant name '{assistant_name}', "
                f"signature emoji '{signature_emoji}'."
            )

        return FunctionToolset([save_profile])


def _birth_ritual_active(
    claimed: _Claimed,
    prior: tuple[TranscriptEntry, ...],
    profile: UserProfile | None,
) -> bool:
    if profile is not None and profile.hatched:
        return False
    if is_wake_up_message(claimed.user_message):
        return True
    return any(entry.role == "user" and is_wake_up_message(entry.content) for entry in prior)


def _agent_workspace(claimed: _Claimed) -> WorkspacePaths | None:
    """The folder of the agent answering: a custom agent's sits next to the platform one."""
    base, custom = claimed.ctx.workspace, claimed.agent.custom
    if base is None or custom is None:
        return base
    try:
        return resolve_agent_workspace(base.directory.parents[2], custom.name)
    except UnsafeAgentName:
        return None


def _bootstrap(
    workspace: WorkspacePaths | None,
    user_directives: str | None = None,
) -> BootstrapContext | None:
    if workspace is None:
        return load_bootstrap_directives(user_directives) if user_directives else None
    return load_bootstrap(workspace, user_directives=user_directives)


def _capabilities_for_turn(
    claimed: _Claimed,
    mcp: MCPCapability | None,
    *,
    birth_ritual: bool = False,
) -> list[AgentCapability[TurnDeps]] | None:
    workspace = _agent_workspace(claimed)
    skills = skills_capability(workspace.skills if workspace else None)
    db_cap = claimed.ctx.databricks_capability
    if db_cap is not None:
        db_cap = replace(
            db_cap,
            user_token=claimed.ctx.user_token or db_cap.user_token,
            store=claimed.ctx.store,
            session_id=claimed.session_id,
            owner_id=claimed.ctx.owner_id,
            model=claimed.ctx.model,
            workspace=workspace,
        )

    return [
        AgentManagementCapability(
            store=claimed.ctx.store,
            owner_id=claimed.ctx.owner_id,
            workspace=claimed.ctx.workspace,
            workspace_root=claimed.ctx.workspace_root,
        ),
        *(
            [HatchCapability(store=claimed.ctx.store, owner_id=claimed.ctx.owner_id)]
            if birth_ritual
            else []
        ),
        GoogleSheetsCapability(user_token=claimed.ctx.user_token),
        InteractionCapability(headless=claimed.ctx.headless),
        *([db_cap] if db_cap is not None else []),
        *([mcp] if mcp is not None else []),
        *([skills] if skills is not None else []),
        MemoryCapability(claimed.ctx.store, claimed.ctx.owner_id),
        _sensitive_tool_guard(
            frozenset(claimed.ctx.sensitive_tools), fired_job=claimed.ctx.fired_job
        ),
        ProcessHistory(foreign_tool_filter),
        tiered_compaction(target_fraction=0.8),
        ReportContextUsage(),
    ]


def _prompt_for(
    claimed: _Claimed,
    mcp: MCPCapability | None = None,
    *,
    profile: UserProfile | None = None,
    birth_ritual: bool = False,
) -> SystemPrompt:
    del mcp
    ctx = claimed.ctx
    workspace = _agent_workspace(claimed)
    custom = claimed.agent.custom
    persona = (
        f"{custom.description}\n\n{custom.system_prompt}".strip() if custom is not None else None
    )
    name = custom.name if custom else (profile.assistant_name if profile else None)
    emoji = custom.signature_emoji if custom else (profile.signature_emoji if profile else None)
    return build_system_prompt(
        runtime=RuntimeMeta(session_id=claimed.session_id, time=format_utc(ctx.now())),
        bootstrap=_bootstrap(
            workspace, user_directives=profile.user_directives if profile else None
        ),
        workspace=workspace,
        assistant_name=name,
        signature_emoji=emoji,
        birth_ritual=birth_ritual,
        agent_id=claimed.agent.agent_id,
        persona=persona,
    )


async def _start_agent(claimed: _Claimed, queue: _Queue, agent: ActiveAgent) -> _Claimed:
    record_turn_agent(agent.agent_id)
    model_name = getattr(claimed.ctx.model, "model_name", "") or ""
    notice = AgentNotice(
        agent_id=agent.agent_id, name=agent.name, emoji=agent.emoji, model=str(model_name)
    )
    await _publish(claimed.ctx, queue, notice)
    return replace(claimed, agent=agent, model=notice.model or None)


async def _warn(claimed: _Claimed, queue: _Queue, text: str) -> None:
    await _append(claimed, TranscriptEntry(role="notice", content=text))
    await _publish(claimed.ctx, queue, WarningNotice(text))


async def _run_command(claimed: _Claimed, command: Command) -> TurnResult:
    await _append_user(claimed)
    outcome = await dispatch_command(
        command,
        ctx=CommandContext(
            store=claimed.ctx.store,
            session_id=claimed.session_id,
            owner_id=claimed.ctx.owner_id,
            model=claimed.ctx.model,
            now=claimed.ctx.now(),
        ),
    )
    if outcome.replacement is not None:
        await claimed.ctx.store.clear_transcript(claimed.session_id, claimed.ctx.owner_id)
        for entry in outcome.replacement:
            await _append(claimed, entry)
    return await _ok_result(claimed, outcome.reply)


async def _paused_agent(
    store: SessionStore,
    owner_id: str,
    default_agent: str | None,
    prior: tuple[TranscriptEntry, ...],
) -> ActiveAgent:
    handle = next((e.agent_id for e in reversed(prior) if e.role == "user"), None)
    found = await find_agent(store, owner_id, handle)
    return found or await session_default(store, owner_id, default_agent)


async def _run_model_resume(
    claimed: _Claimed,
    approval: ApprovalEntry,
    decision: Resolution,
    queue: _Queue,
) -> TurnResult:
    ctx = claimed.ctx
    prior = await ctx.store.transcript(claimed.session_id, ctx.owner_id)
    claimed = await _start_agent(
        claimed, queue, await _paused_agent(ctx.store, ctx.owner_id, ctx.default_agent, prior)
    )
    profile = await ctx.store.get_user_profile(ctx.owner_id)
    birth_ritual = _birth_ritual_active(claimed, prior, profile)
    history = await _load_session_history(ctx.store, claimed.session_id, ctx.owner_id, prior=prior)
    if not any(
        isinstance(p, ToolCallPart) and p.tool_call_id == approval.tool_call_id
        for m in history
        for p in getattr(m, "parts", [])
    ):
        history.append(
            ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name=approval.tool_name,
                        args=approval.arguments,
                        tool_call_id=approval.tool_call_id,
                    )
                ]
            )
        )
    return await _invoke_agent(
        claimed,
        queue,
        profile=profile,
        birth_ritual=birth_ritual,
        history=history,
        deferred_results=_deferred_results(approval, decision),
        skip_tool_call_id=approval.tool_call_id,
    )


async def _run_model(claimed: _Claimed, queue: _Queue) -> TurnResult:
    ctx = claimed.ctx
    command = parse_command(claimed.user_message)
    if command is not None:
        agent = await session_default(ctx.store, ctx.owner_id, ctx.default_agent)
        return await _run_command(await _start_agent(claimed, queue, agent), command)
    choice = await choose_agent(
        claimed.user_message,
        store=ctx.store,
        owner_id=ctx.owner_id,
        default_handle=ctx.default_agent,
    )
    claimed = await _start_agent(claimed, queue, choice.agent)
    prior = await ctx.store.transcript(claimed.session_id, ctx.owner_id)
    profile = await ctx.store.get_user_profile(ctx.owner_id)
    birth_ritual = _birth_ritual_active(claimed, prior, profile)
    history = drop_unreturned_tool_calls(
        await _load_session_history(ctx.store, claimed.session_id, ctx.owner_id, prior=prior)
    )
    await _append_user(claimed)
    if choice.missing is not None:
        await _warn(claimed, queue, missing_agent_warning(choice.missing))
    bundle = await resolve_mention_bundles(
        claimed.user_message,
        workspace=_agent_workspace(claimed),
        databricks_cap=ctx.databricks_capability,
    )
    user_prompt = claimed.user_message
    if bundle.injected_context:
        user_prompt = f"{claimed.user_message}\n\n[Injected Context]\n{bundle.injected_context}"
    memories = await claimed.ctx.store.rank_memories(claimed.ctx.owner_id, claimed.user_message)
    memory_block = format_memory_block(memories)
    if memory_block:
        user_prompt = f"{user_prompt}\n\n[Memory]\n{memory_block}"
    return await _invoke_agent(
        claimed,
        queue,
        profile=profile,
        birth_ritual=birth_ritual,
        user_prompt=user_prompt,
        history=history or None,
    )


async def _ok_result(claimed: _Claimed, reply: str) -> TurnResult:
    token = claimed.ctx.user_token
    scrubbed = scrub_token(reply, token) if token else reply
    await _append(claimed, TranscriptEntry(role="assistant", content=scrubbed))
    transcript = await claimed.ctx.store.transcript(claimed.session_id, claimed.ctx.owner_id)
    return TurnResult(
        session_id=claimed.session_id,
        status="ok",
        reply=scrubbed,
        error=None,
        transcript=transcript,
    )


async def _invoke_agent(  # noqa: PLR0913
    claimed: _Claimed,
    queue: _Queue,
    *,
    profile: UserProfile | None,
    birth_ritual: bool,
    user_prompt: str | None = None,
    history: list[ModelMessage] | None = None,
    deferred_results: DeferredToolResults | None = None,
    skip_tool_call_id: str | None = None,
) -> TurnResult:
    ctx = claimed.ctx
    mcp = await mcp_capability(
        ctx.mcp_servers, ctx.user_token, toolset_factory=ctx.mcp_toolset_factory
    )
    prompt = _prompt_for(claimed, mcp, profile=profile, birth_ritual=birth_ritual)
    usage = []
    result = await clawhouse_agent().run(
        user_prompt,
        message_history=history,
        deferred_tool_results=deferred_results,
        model=ctx.model,
        instructions=prompt.text,
        deps=TurnDeps(now=ctx.now, user_token=ctx.user_token),
        event_stream_handler=_persist_and_emit(
            claimed, queue, skip_tool_call_id=skip_tool_call_id, usage=usage
        ),
        capabilities=_capabilities_for_turn(claimed, mcp, birth_ritual=birth_ritual),
    )
    if usage:
        await _publish(ctx, queue, usage[0])
    await claimed.ctx.store.save_messages(claimed.session_id, result.all_messages_json())
    if isinstance(result.output, DeferredToolRequests):
        return await _handle_deferred_approvals(claimed, queue, result.output)
    raw_reply = result.output if isinstance(result.output, str) else str(result.output)
    return await _ok_result(claimed, raw_reply)
