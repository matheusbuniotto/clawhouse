"""One serialized chat turn: prompt, tool dispatch, guardrails, and transcript persistence."""

import asyncio
import json
import logging
from collections.abc import (
    AsyncGenerator,
    AsyncIterable,
    AsyncIterator,
    Awaitable,
    Callable,
    Coroutine,
)
from contextlib import suppress
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from pydantic_ai import DeferredToolRequests, RunContext
from pydantic_ai.capabilities import AbstractCapability, AgentCapability, ProcessHistory
from pydantic_ai.messages import (
    AgentStreamEvent,
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    ModelMessage,
    ModelResponse,
    PartDeltaEvent,
    PartStartEvent,
    TextPart,
    TextPartDelta,
    ToolCallPart,
)
from pydantic_ai.models import Model
from pydantic_ai.tools import DeferredToolResults, ToolApproved, ToolDenied
from pydantic_ai.toolsets import AbstractToolset, AgentToolset, FunctionToolset
from pydantic_ai_harness.compaction import ContextUsageEvent, ReportContextUsage
from pydantic_ai_harness.guardrails import GuardrailResult, ToolCallInfo, ToolGuardrail

from clawhouse.agent.commands import Command, CommandContext, dispatch_command, parse_command
from clawhouse.agent.core import TurnDeps, clawhouse_agent, format_utc
from clawhouse.agent.history import foreign_tool_filter, to_model_messages
from clawhouse.agent.prompt import (
    BUILTIN_TOOLS,
    RuntimeMeta,
    SystemPrompt,
    ToolCard,
    build_system_prompt,
)
from clawhouse.agent.roster import (
    PLATFORM_AGENT,
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
from clawhouse.capabilities.databricks import DatabricksCapability
from clawhouse.capabilities.interaction import (
    ASK_USER,
    ASK_USER_DESCRIPTION,
    REPORT_PROGRESS,
    REPORT_PROGRESS_DESCRIPTION,
    InteractionCapability,
    Question,
    answer_text,
    parse_progress,
)
from clawhouse.capabilities.mcp import MCPCapability, MCPServerConfig, mcp_capability, scrub_token
from clawhouse.capabilities.mentions import resolve_mention_bundles, tiered_compaction
from clawhouse.capabilities.sheets import GOOGLE_SHEETS_TOOL_CARDS, GoogleSheetsCapability
from clawhouse.capabilities.skills import loaded_skill_text, skills_capability
from clawhouse.capabilities.workspace import (
    UnsafeAgentName,
    WorkspacePaths,
    resolve_agent_workspace,
)
from clawhouse.store.shapes import (
    ApprovalEntry,
    TranscriptEntry,
    TurnResult,
    TurnStatus,
    UserProfile,
)
from clawhouse.store.store import (
    ApprovalForbidden,
    ApprovalPending,
    RunInProgress,
    SessionForbidden,
    SessionStore,
)

logger = logging.getLogger("clawhouse.turn")

FAILED_TURN = "The turn failed before a reply was completed."
QUESTION_TTL = timedelta(hours=24)
QUESTION_EXPIRED = "Pergunta encerrada sem resposta depois de 24h."
BUSY_TURN = "A turn is already running for this session."


class InvalidSessionId(Exception):
    """Session ids are UUIDs."""


class _End:
    """Marks the end of the notice queue. Not a stream event."""


_END = _End()


@dataclass(frozen=True, slots=True)
class Token:
    text: str


@dataclass(frozen=True, slots=True)
class ToolCallNotice:
    name: str
    arguments: str
    tool_call_id: str


@dataclass(frozen=True, slots=True)
class ToolResultNotice:
    name: str
    content: str
    tool_call_id: str


@dataclass(frozen=True, slots=True)
class ApprovalNotice:
    approval_id: str
    name: str
    arguments: str
    tool_call_id: str


@dataclass(frozen=True, slots=True)
class QuestionNotice:
    """The run paused on `ask_user`: the card to show, answered by `question_id`."""

    question_id: str
    question: str
    options: tuple[str, ...]
    default: str | None
    multi: bool
    tool_call_id: str


@dataclass(frozen=True, slots=True)
class ProgressNotice:
    """The current state of a progress card. One card per `task_id`, updated in place."""

    task_id: str
    steps: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class Answer:
    """The labels the user clicked on a question card."""

    selected: tuple[str, ...]


Resolution = Literal["approved", "denied"] | Answer


@dataclass(frozen=True, slots=True)
class UsageNotice:
    """Input tokens of the last model request: the context as sent to the model."""

    input_tokens: int
    context_window: int | None


@dataclass(frozen=True, slots=True)
class AgentNotice:
    """Opens a turn: which agent answers it, and on which model."""

    agent_id: str
    name: str
    emoji: str
    model: str


@dataclass(frozen=True, slots=True)
class WarningNotice:
    """A line for the reader, not the model: e.g. an `@agent` that does not exist."""

    text: str


TurnNotice = (
    Token
    | ToolCallNotice
    | ToolResultNotice
    | ApprovalNotice
    | UsageNotice
    | AgentNotice
    | WarningNotice
    | QuestionNotice
    | ProgressNotice
)
Emit = Callable[[TurnNotice], Awaitable[None]]
_Queue = asyncio.Queue[TurnNotice | _End]
MCPToolsetFactory = Callable[[MCPServerConfig, str], AbstractToolset[object]]


@dataclass(frozen=True, slots=True)
class TurnContext:
    owner_id: str
    store: SessionStore
    model: Model
    now: Callable[[], datetime]
    emit: Emit | None = None
    workspace: WorkspacePaths | None = None
    workspace_root: Path | None = None
    mcp_servers: tuple[MCPServerConfig, ...] = ()
    user_token: str = ""
    mcp_toolset_factory: MCPToolsetFactory | None = None
    sensitive_tools: tuple[str, ...] = ()
    databricks_capability: DatabricksCapability | None = None
    default_agent: str | None = None
    # No one is watching (scheduled job): questions take their default instead of pausing.
    headless: bool = False


def canonical_session_id(value: str) -> str:
    try:
        return str(UUID(value))
    except ValueError as exc:
        raise InvalidSessionId(value) from exc


async def run_turn(session_id: str, user_message: str, *, ctx: TurnContext) -> TurnResult:
    """Run one turn. A second in-flight run on the same session raises `RunInProgress`."""
    result: TurnResult | None = None
    async for item in iter_turn(session_id, user_message, ctx=ctx):
        if isinstance(item, TurnResult):
            result = item
    if result is None:
        raise RuntimeError("turn produced no result")
    return result


async def resume_turn(
    session_id: str,
    approval_id: str,
    decision: Resolution,
    *,
    ctx: TurnContext,
) -> TurnResult:
    """Resume a turn paused for approval."""
    result: TurnResult | None = None
    async for item in iter_resume_turn(session_id, approval_id, decision, ctx=ctx):
        if isinstance(item, TurnResult):
            result = item
    if result is None:
        raise RuntimeError("resume turn produced no result")
    return result


@dataclass(frozen=True, slots=True)
class _Claimed:
    session_id: str
    user_message: str
    run_id: str
    ctx: TurnContext
    agent: ActiveAgent = PLATFORM_AGENT
    model: str | None = None


async def iter_turn(
    session_id: str,
    user_message: str,
    *,
    ctx: TurnContext,
) -> AsyncGenerator[TurnNotice | TurnResult, None]:
    """Yield stream notices, release the run lock, then yield the terminal result."""
    claimed = await _claim(canonical_session_id(session_id), user_message, ctx)
    queue: _Queue = asyncio.Queue()
    holder: list[TurnResult] = []
    task = _detach(claimed, _worker(claimed, queue, holder), holder)
    async for notice in _drain(queue):
        yield notice
    await asyncio.shield(task)
    if not holder:
        holder.append(await _error_result(claimed.session_id, claimed.ctx))
    res = holder[0]
    token = claimed.ctx.user_token
    if token and res.error and token in res.error:
        res = replace(res, error=scrub_token(res.error, token))
    yield res


async def iter_resume_turn(
    session_id: str,
    approval_id: str,
    decision: Resolution,
    *,
    ctx: TurnContext,
) -> AsyncGenerator[TurnNotice | TurnResult, None]:
    """Resume turn execution after human decision."""
    claimed = await _claim_resume(session_id, approval_id, decision, ctx)
    approval = await ctx.store.get_approval(approval_id)
    queue: _Queue = asyncio.Queue()
    holder: list[TurnResult] = []
    task = _detach(
        claimed, _worker_resume(claimed, approval, decision, queue=queue, holder=holder), holder
    )
    async for notice in _drain(queue):
        yield notice
    await asyncio.shield(task)
    if not holder:
        holder.append(await _error_result(claimed.session_id, claimed.ctx))
    res = holder[0]
    token = claimed.ctx.user_token
    if token and res.error and token in res.error:
        res = replace(res, error=scrub_token(res.error, token))
    yield res


async def _claim(session_id: str, user_message: str, ctx: TurnContext) -> _Claimed:
    await ctx.store.open_session(session_id, ctx.owner_id)
    expired = await _expire_questions(session_id, ctx)
    run_id = await ctx.store.claim_run(session_id)
    claimed = _Claimed(
        session_id=session_id,
        user_message=user_message,
        run_id=run_id,
        ctx=ctx,
    )
    for _ in range(expired):
        await _append(claimed, TranscriptEntry(role="notice", content=QUESTION_EXPIRED))
    return claimed


async def _expire_questions(session_id: str, ctx: TurnContext) -> int:
    """Close questions nobody answered in `QUESTION_TTL`, so the session is not stuck."""
    pending = await ctx.store.list_approvals(ctx.owner_id, status="pending")
    cutoff = ctx.now() - QUESTION_TTL
    stale = [
        entry
        for entry in pending
        if entry.session_id == session_id
        and entry.tool_name == ASK_USER
        and entry.created_at < cutoff
    ]
    for entry in stale:
        await ctx.store.resolve_approval(entry.id, "denied", "system:expired", ctx.now())
    return len(stale)


async def _claim_resume(
    session_id: str,
    approval_id: str,
    decision: Resolution,
    ctx: TurnContext,
) -> _Claimed:
    canonical = canonical_session_id(session_id)
    approval = await ctx.store.get_approval(approval_id)
    if approval.session_id != canonical:
        raise ApprovalForbidden(approval_id)
    await ctx.store.open_session(canonical, ctx.owner_id)
    status = "approved" if isinstance(decision, Answer) else decision
    await ctx.store.resolve_approval(approval_id, status, ctx.owner_id, ctx.now())
    run_id = await ctx.store.claim_run(canonical)
    return _Claimed(
        session_id=canonical,
        user_message="",
        run_id=run_id,
        ctx=ctx,
    )


async def _worker(claimed: _Claimed, queue: _Queue, holder: list[TurnResult]) -> None:
    try:
        holder.append(await _run_model(claimed, queue))
    except Exception as exc:  # noqa: BLE001 — a failed turn is an empty reply, never a partial one
        # Model failures can echo request headers. Log the type only.
        logger.error("turn failed: %s", type(exc).__name__)  # noqa: TRY400
        holder.append(await _error_result(claimed.session_id, claimed.ctx))
    finally:
        await queue.put(_END)


async def _worker_resume(
    claimed: _Claimed,
    approval: ApprovalEntry,
    decision: Resolution,
    *,
    queue: _Queue,
    holder: list[TurnResult],
) -> None:
    try:
        holder.append(await _run_model_resume(claimed, approval, decision, queue))
    except Exception as exc:  # noqa: BLE001
        logger.error("resume turn failed: %s", type(exc).__name__)  # noqa: TRY400
        holder.append(await _error_result(claimed.session_id, claimed.ctx))
    finally:
        await queue.put(_END)


async def _drain(queue: _Queue) -> AsyncIterator[TurnNotice]:
    while True:
        item = await queue.get()
        if isinstance(item, _End):
            return
        yield item


# Turns outlive the request that started them: a reload or a dropped connection must not
# cancel the run halfway (it would leave the run row `running` and the session stuck).
# Only `cancel_turn` stops one. Keyed by canonical session id.
_RUNNING: dict[str, asyncio.Task[None]] = {}


def _detach(
    claimed: _Claimed, work: Coroutine[Any, Any, None], holder: list[TurnResult]
) -> asyncio.Task[None]:
    async def run() -> None:
        try:
            await work
        except asyncio.CancelledError:
            logger.info("turn cancelled for session %s", claimed.session_id)
        finally:
            _RUNNING.pop(claimed.session_id, None)
            await claimed.ctx.store.finish_run(claimed.session_id, claimed.run_id, _status(holder))

    task = asyncio.create_task(run())
    _RUNNING[claimed.session_id] = task
    return task


async def cancel_turn(session_id: str) -> bool:
    """Stop the session's running turn (the Stop button). False when none is running here."""
    task = _RUNNING.get(canonical_session_id(session_id))
    if task is None or task.done():
        return False
    task.cancel()
    with suppress(asyncio.CancelledError):
        await asyncio.shield(task)
    return True


def _status(holder: list[TurnResult]) -> TurnStatus:
    if not holder:
        return "error"
    return holder[0].status


def _sensitive_tool_guard(names: frozenset[str]) -> ToolGuardrail[TurnDeps]:
    """Defer every listed tool through the harness-native approval flow."""

    def guard(call: ToolCallInfo) -> GuardrailResult:
        if call.name in names:
            return GuardrailResult.approve()
        return GuardrailResult.allow()

    return ToolGuardrail(guard=guard)


SAVE_PROFILE_NAME = "save_profile"
SAVE_PROFILE_DESCRIPTION = (
    "Save the assistant's name, signature emoji, and user directives to the user profile "
    "upon completing the birth ritual."
)
SAVE_PROFILE_TOOL_CARD = ToolCard(name=SAVE_PROFILE_NAME, description=SAVE_PROFILE_DESCRIPTION)

CREATE_AGENT_NAME = "create_agent"
CREATE_AGENT_DESCRIPTION = (
    "Create a new specialized custom agent with its OpenClaw-compatible workspace folder."
)
CREATE_AGENT_TOOL_CARD = ToolCard(name=CREATE_AGENT_NAME, description=CREATE_AGENT_DESCRIPTION)


def is_wake_up_message(text: str) -> bool:
    cleaned = text.strip().lower()
    if cleaned in ("wake up, my friend!", "wake up, my friend", "wake up my friend", "wake up"):
        return True
    return cleaned.startswith("wake up, my friend")


@dataclass
class HatchCapability(AbstractCapability[TurnDeps]):
    """Attached during the birth sequence ritual to persist caller's profile."""

    store: SessionStore
    owner_id: str

    def get_toolset(self) -> AgentToolset[TurnDeps] | None:
        store = self.store
        owner_id = self.owner_id

        async def save_profile(
            assistant_name: str,
            signature_emoji: str,
            user_directives: str,
        ) -> str:
            profile = UserProfile(
                user_id=owner_id,
                assistant_name=assistant_name,
                signature_emoji=signature_emoji,
                user_directives=user_directives,
                hatched=True,
            )
            await store.save_user_profile(profile)
            return (
                f"Saved profile for {owner_id}: assistant name '{assistant_name}', "
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


DATABRICKS_TOOL_CARDS = (
    ToolCard(name="dbsql_query", description="Execute a SQL query on a Databricks SQL Warehouse."),
    ToolCard(name="system_ai_query", description="Invoke Databricks AI functions or models."),
    ToolCard(name="uc_describe_table", description="Describe schema of a Unity Catalog table."),
    ToolCard(name="uc_list_catalogs", description="List available Unity Catalog catalogs."),
    ToolCard(name="uc_list_schemas", description="List schemas within a Unity Catalog catalog."),
    ToolCard(name="uc_list_tables", description="List tables within a Unity Catalog schema."),
    ToolCard(name="jobs_list", description="List Lakeflow jobs in the workspace."),
    ToolCard(name="jobs_get_run", description="Get the state of a Lakeflow job run."),
    ToolCard(
        name="jobs_get_run_output",
        description="Get execution output and logs of a Lakeflow job run.",
    ),
    ToolCard(
        name="jobs_run_now",
        description="Trigger a Lakeflow job run (needs approval); optional parameter overrides.",
    ),
    ToolCard(
        name="jobs_create",
        description="Create a Lakeflow job (SQL/Python/Agentic) with schedule (needs approval).",
    ),
    ToolCard(
        name="jobs_edit",
        description="Update Lakeflow job settings, schedule, or query (needs approval).",
    ),
    ToolCard(
        name="jobs_delete",
        description="Delete a Lakeflow job from the workspace (needs approval).",
    ),
    ToolCard(
        name="jobs_cancel_run",
        description="Cancel an active Lakeflow job run (needs approval).",
    ),
    ToolCard(
        name="jobs_wait_run",
        description="Wait/poll for a job run to finish and return final status and output.",
    ),
    ToolCard(
        name="system_ai_format_delivery",
        description="Format analytical reports for Slack or Sheets using Databricks AI.",
    ),
    ToolCard(
        name="delivery_send_webhook",
        description="Send formatted report to external webhook (needs approval).",
    ),
)


def _capabilities_for_turn(
    claimed: _Claimed,
    mcp: MCPCapability | None,
    *,
    birth_ritual: bool = False,
) -> list[AgentCapability[TurnDeps]] | None:
    capabilities: list[AgentCapability[TurnDeps]] = [
        AgentManagementCapability(
            store=claimed.ctx.store,
            owner_id=claimed.ctx.owner_id,
            workspace=claimed.ctx.workspace,
            workspace_root=claimed.ctx.workspace_root,
        )
    ]
    if birth_ritual:
        capabilities.append(HatchCapability(store=claimed.ctx.store, owner_id=claimed.ctx.owner_id))
    capabilities.append(GoogleSheetsCapability(user_token=claimed.ctx.user_token))
    capabilities.append(InteractionCapability(headless=claimed.ctx.headless))
    if claimed.ctx.databricks_capability is not None:
        cap = claimed.ctx.databricks_capability
        if not cap.user_token and claimed.ctx.user_token:
            cap.user_token = claimed.ctx.user_token
        capabilities.append(cap)
    if mcp is not None:
        capabilities.append(mcp)
    workspace = _agent_workspace(claimed)
    skills = skills_capability(workspace.skills if workspace else None)
    if skills is not None:
        capabilities.append(skills)
    if claimed.ctx.sensitive_tools:
        capabilities.append(_sensitive_tool_guard(frozenset(claimed.ctx.sensitive_tools)))
    # The history is shared between agents: drop tool parts this agent's toolset lacks.
    capabilities.append(ProcessHistory(foreign_tool_filter))
    # Compact the in-run history when it approaches the window, then report what was sent.
    capabilities.append(tiered_compaction(target_fraction=0.8))
    capabilities.append(ReportContextUsage())
    return capabilities


def _prompt_for(
    claimed: _Claimed,
    mcp: MCPCapability | None,
    *,
    profile: UserProfile | None = None,
    birth_ritual: bool = False,
) -> SystemPrompt:
    ctx = claimed.ctx
    tools_list = mcp.tools if mcp is not None else ()
    mcp_cards = tuple(ToolCard(name=t.safe_name, description=t.description) for t in tools_list)
    db_cards = DATABRICKS_TOOL_CARDS if ctx.databricks_capability is not None else ()
    base_tools = (
        *BUILTIN_TOOLS,
        CREATE_AGENT_TOOL_CARD,
        ToolCard(name=ASK_USER, description=ASK_USER_DESCRIPTION),
        ToolCard(name=REPORT_PROGRESS, description=REPORT_PROGRESS_DESCRIPTION),
        *GOOGLE_SHEETS_TOOL_CARDS,
    )
    builtin = (*base_tools, SAVE_PROFILE_TOOL_CARD) if birth_ritual else base_tools
    user_directives = profile.user_directives if profile else None
    workspace = _agent_workspace(claimed)
    custom = claimed.agent.custom
    if custom is not None:
        name, emoji = custom.name, custom.signature_emoji
        persona = f"{custom.description}\n\n{custom.system_prompt}".strip()
    else:
        name = profile.assistant_name if profile else None
        emoji = profile.signature_emoji if profile else None
        persona = None
    return build_system_prompt(
        tools=(*builtin, *db_cards, *mcp_cards),
        runtime=RuntimeMeta(session_id=claimed.session_id, time=format_utc(ctx.now())),
        bootstrap=_bootstrap(workspace, user_directives=user_directives),
        workspace=workspace,
        assistant_name=name,
        signature_emoji=emoji,
        birth_ritual=birth_ritual,
        agent_id=claimed.agent.agent_id,
        persona=persona,
    )


def _usage_notice(event: ContextUsageEvent) -> UsageNotice:
    """Native context reporting replaced the post-run scan of model messages."""
    return UsageNotice(
        input_tokens=event.used_tokens,
        context_window=event.window_tokens if event.resolved else None,
    )


async def _start_agent(claimed: _Claimed, queue: _Queue, agent: ActiveAgent) -> _Claimed:
    """Bind the turn to its agent and announce it before any other frame."""
    model_name = getattr(claimed.ctx.model, "model_name", "") or ""
    notice = AgentNotice(
        agent_id=agent.agent_id, name=agent.name, emoji=agent.emoji, model=str(model_name)
    )
    await _publish(claimed.ctx, queue, notice)
    return replace(claimed, agent=agent, model=notice.model or None)


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
    return await _invoke_agent(
        claimed,
        queue,
        profile=profile,
        birth_ritual=birth_ritual,
        user_prompt=user_prompt,
        history=to_model_messages(prior) or None,
    )


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


async def _run_model_resume(
    claimed: _Claimed,
    approval: ApprovalEntry,
    decision: Resolution,
    queue: _Queue,
) -> TurnResult:
    ctx = claimed.ctx
    prior = await ctx.store.transcript(claimed.session_id, ctx.owner_id)
    claimed = await _start_agent(claimed, queue, await _paused_agent(ctx, prior))
    profile = await ctx.store.get_user_profile(ctx.owner_id)
    birth_ritual = _birth_ritual_active(claimed, prior, profile)
    call_args = approval.arguments
    if ctx.user_token and "[REDACTED]" in call_args:
        call_args = call_args.replace("[REDACTED]", ctx.user_token)
    history = to_model_messages(prior)
    history.append(
        ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name=approval.tool_name,
                    args=call_args,
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


async def _paused_agent(ctx: TurnContext, prior: tuple[TranscriptEntry, ...]) -> ActiveAgent:
    """The agent that paused: the one the last user message addressed."""
    handle = next((e.agent_id for e in reversed(prior) if e.role == "user"), None)
    found = await find_agent(ctx.store, ctx.owner_id, handle)
    return found or await session_default(ctx.store, ctx.owner_id, ctx.default_agent)


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
        ctx.mcp_servers,
        ctx.user_token,
        toolset_factory=ctx.mcp_toolset_factory,
    )
    prompt = _prompt_for(claimed, mcp, profile=profile, birth_ritual=birth_ritual)
    usage: list[UsageNotice] = []
    result = await clawhouse_agent().run(
        user_prompt,
        message_history=history,
        deferred_tool_results=deferred_results,
        model=ctx.model,
        instructions=prompt.text,
        deps=TurnDeps(now=ctx.now),
        event_stream_handler=_persist_and_emit(
            claimed, queue, skip_tool_call_id=skip_tool_call_id, usage=usage
        ),
        capabilities=_capabilities_for_turn(claimed, mcp, birth_ritual=birth_ritual),
    )
    if usage:
        await _publish(ctx, queue, usage[0])
    if isinstance(result.output, DeferredToolRequests):
        return await _handle_deferred_approvals(claimed, queue, result.output)
    raw_reply = result.output if isinstance(result.output, str) else str(result.output)
    return await _ok_result(claimed, raw_reply)


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


def _deferred_results(
    approval: ApprovalEntry,
    decision: Resolution,
) -> DeferredToolResults:
    if isinstance(decision, Answer):
        return DeferredToolResults(calls={approval.tool_call_id: answer_text(decision.selected)})
    if decision == "approved":
        return DeferredToolResults(approvals={approval.tool_call_id: ToolApproved()})
    return DeferredToolResults(
        approvals={approval.tool_call_id: ToolDenied(message="The user denied the tool call.")}
    )


async def _handle_deferred_approvals(
    claimed: _Claimed,
    queue: _Queue,
    output: DeferredToolRequests,
) -> TurnResult:
    ctx = claimed.ctx
    ids: list[str] = []
    for call in output.approvals:
        ids.append(await _pause_for_approval(claimed, queue, call))
    for call in output.calls:
        if call.tool_name == ASK_USER:
            ids.append(await _pause_for_question(claimed, queue, call))
    first_id = ids[0] if ids else None
    transcript = await ctx.store.transcript(claimed.session_id, ctx.owner_id)
    return TurnResult(
        session_id=claimed.session_id,
        status="pending_approval",
        reply="",
        error=None,
        transcript=transcript,
        approval_id=first_id,
    )


async def _pause_record(claimed: _Claimed, call: ToolCallPart) -> tuple[str, str]:
    ctx = claimed.ctx
    raw_args = call.args_as_json_str()
    scrubbed = scrub_token(raw_args, ctx.user_token) if ctx.user_token else raw_args
    entry = await ctx.store.create_approval(
        session_id=claimed.session_id,
        run_id=claimed.run_id,
        tool_name=call.tool_name,
        tool_call_id=call.tool_call_id,
        arguments=scrubbed,
    )
    return entry.id, scrubbed


async def _pause_for_approval(claimed: _Claimed, queue: _Queue, call: ToolCallPart) -> str:
    approval_id, arguments = await _pause_record(claimed, call)
    notice = ApprovalNotice(
        approval_id=approval_id,
        name=call.tool_name,
        arguments=arguments,
        tool_call_id=call.tool_call_id,
    )
    await _publish(claimed.ctx, queue, notice)
    return approval_id


async def _pause_for_question(claimed: _Claimed, queue: _Queue, call: ToolCallPart) -> str:
    """A question pauses like an approval: same row, same lock on the session."""
    question_id, arguments = await _pause_record(claimed, call)
    asked = Question.from_arguments(arguments)
    notice = QuestionNotice(
        question_id=question_id,
        question=asked.question,
        options=asked.options,
        default=asked.default,
        multi=asked.multi,
        tool_call_id=call.tool_call_id,
    )
    await _publish(claimed.ctx, queue, notice)
    return question_id


def _bootstrap(
    workspace: WorkspacePaths | None,
    user_directives: str | None = None,
) -> BootstrapContext | None:
    if workspace is None:
        if user_directives:
            return load_bootstrap_directives(user_directives)
        return None
    return load_bootstrap(workspace, user_directives=user_directives)


def _agent_workspace(claimed: _Claimed) -> WorkspacePaths | None:
    """The folder of the agent answering: a custom agent's sits next to the platform one."""
    base = claimed.ctx.workspace
    custom = claimed.agent.custom
    if base is None or custom is None:
        return base
    try:
        return resolve_agent_workspace(base.directory.parents[2], custom.name)
    except UnsafeAgentName:
        return None


async def _append_user(claimed: _Claimed) -> None:
    await _append(claimed, TranscriptEntry(role="user", content=claimed.user_message))


def _scrub_entry(entry: TranscriptEntry, token: str) -> TranscriptEntry:
    if not token:
        return entry
    has_token = token in entry.content or (entry.tool_name is not None and token in entry.tool_name)
    if not has_token:
        return entry
    return replace(
        entry,
        content=scrub_token(entry.content, token),
        tool_name=scrub_token(entry.tool_name, token) if entry.tool_name else None,
    )


async def _append(claimed: _Claimed, entry: TranscriptEntry) -> None:
    if entry.agent_id is None:
        entry = replace(entry, agent_id=claimed.agent.agent_id)
    if entry.model is None and entry.role != "user":
        entry = replace(entry, model=claimed.model)
    scrubbed = _scrub_entry(entry, claimed.ctx.user_token)
    await claimed.ctx.store.append_entry(claimed.session_id, claimed.run_id, scrubbed)


def _scrub_tool_notice(notice: TurnNotice, token: str) -> TurnNotice:
    if isinstance(notice, ToolCallNotice):
        return ToolCallNotice(
            name=notice.name,
            arguments=scrub_token(notice.arguments, token),
            tool_call_id=notice.tool_call_id,
        )
    if isinstance(notice, ToolResultNotice):
        return ToolResultNotice(
            name=notice.name,
            content=scrub_token(notice.content, token),
            tool_call_id=notice.tool_call_id,
        )
    if isinstance(notice, ApprovalNotice):
        return ApprovalNotice(
            approval_id=notice.approval_id,
            name=notice.name,
            arguments=scrub_token(notice.arguments, token),
            tool_call_id=notice.tool_call_id,
        )
    return notice


def _scrub_notice(notice: TurnNotice, token: str) -> TurnNotice:
    if not token:
        return notice
    if isinstance(notice, Token):
        return Token(scrub_token(notice.text, token))
    return _scrub_tool_notice(notice, token)


def _persist_and_emit(
    claimed: _Claimed,
    queue: _Queue,
    *,
    skip_tool_call_id: str | None = None,
    usage: list[UsageNotice] | None = None,
):
    async def handle(
        run_ctx: RunContext[TurnDeps],
        events: AsyncIterable[AgentStreamEvent],
    ) -> None:
        del run_ctx
        token = claimed.ctx.user_token
        async for event in events:
            if isinstance(event, ContextUsageEvent):
                if usage is not None:
                    usage[:] = [_usage_notice(event)]
                continue
            notice = notice_from(event)
            if notice is None:
                continue
            if (
                skip_tool_call_id
                and isinstance(notice, ToolCallNotice)
                and notice.tool_call_id == skip_tool_call_id
            ):
                continue
            scrubbed = _scrub_notice(notice, token)
            await _record(claimed, scrubbed)
            shown = _as_progress(scrubbed)
            if shown is not None:
                await _publish(claimed.ctx, queue, shown)

    return handle


def _as_progress(notice: TurnNotice) -> TurnNotice | None:
    """`report_progress` streams as its card, not as tool rows; the rows stay in the store."""
    if not isinstance(notice, ToolCallNotice | ToolResultNotice) or notice.name != REPORT_PROGRESS:
        return notice
    if isinstance(notice, ToolResultNotice):
        return None
    parsed = parse_progress(notice.arguments)
    if parsed is None:
        return None
    task_id, steps = parsed
    return ProgressNotice(task_id=task_id, steps=tuple((s.label, s.status) for s in steps))


async def _record(claimed: _Claimed, notice: TurnNotice) -> None:
    entry = entry_from(notice)
    if entry is None:
        return
    await _append(claimed, entry)


async def _publish(ctx: TurnContext, queue: _Queue, notice: TurnNotice) -> None:
    scrubbed = _scrub_notice(notice, ctx.user_token)
    await queue.put(scrubbed)
    if ctx.emit is not None:
        await ctx.emit(scrubbed)


async def _error_result(
    session_id: str,
    ctx: TurnContext,
    error: str = FAILED_TURN,
) -> TurnResult:
    transcript = await ctx.store.transcript(session_id, ctx.owner_id)
    scrubbed = scrub_token(error, ctx.user_token) if ctx.user_token else error
    return TurnResult(
        session_id=session_id,
        status="error",
        reply="",
        error=scrubbed,
        transcript=transcript,
    )


def notice_from(event: object) -> TurnNotice | None:
    if isinstance(event, FunctionToolCallEvent):
        return ToolCallNotice(
            name=event.part.tool_name,
            arguments=event.part.args_as_json_str(),
            tool_call_id=event.part.tool_call_id,
        )
    if isinstance(event, FunctionToolResultEvent):
        return ToolResultNotice(
            name=event.part.tool_name or "",
            content=_as_text(event.part.content),
            tool_call_id=event.tool_call_id,
        )
    text = _text_delta(event)
    if text:
        return Token(text)
    return None


def entry_from(notice: TurnNotice) -> TranscriptEntry | None:
    if isinstance(notice, ToolCallNotice):
        return TranscriptEntry(
            role="tool_call",
            content=notice.arguments,
            tool_name=notice.name,
            tool_call_id=notice.tool_call_id,
        )
    if isinstance(notice, ToolResultNotice):
        return TranscriptEntry(
            role="tool_result",
            content=notice.content,
            tool_name=notice.name,
            tool_call_id=notice.tool_call_id,
        )
    return None


def _text_delta(event: object) -> str | None:
    if isinstance(event, PartStartEvent) and isinstance(event.part, TextPart):
        return event.part.content or None
    if isinstance(event, PartDeltaEvent) and isinstance(event.delta, TextPartDelta):
        return event.delta.content_delta or None
    return None


def _as_text(content: object) -> str:
    if isinstance(content, str):
        return content
    loaded = loaded_skill_text(content)
    if loaded is not None:
        return loaded
    if isinstance(content, dict | list | tuple):
        return json.dumps(content, default=str)
    return str(content)


__all__ = [
    "BUSY_TURN",
    "FAILED_TURN",
    "AgentNotice",
    "Answer",
    "ApprovalForbidden",
    "ApprovalNotice",
    "ApprovalPending",
    "HatchCapability",
    "InvalidSessionId",
    "ProgressNotice",
    "QuestionNotice",
    "RunInProgress",
    "SessionForbidden",
    "Token",
    "ToolCallNotice",
    "ToolResultNotice",
    "TurnContext",
    "TurnNotice",
    "UsageNotice",
    "WarningNotice",
    "is_wake_up_message",
    "iter_resume_turn",
    "iter_turn",
    "resume_turn",
    "run_turn",
]
