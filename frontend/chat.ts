import {
  ASK_USER,
  REPORT_PROGRESS,
  parseProgress,
  upsertProgressCard,
  renderAnsweredQuestion,
  renderQuestionCard,
  type AnswerResult,
  type ProgressStep,
  type QuestionCard,
} from "./cards.js";
import {
  SESSION_RENAMED,
  UNTITLED,
  clearSession,
  editTitle,
  el,
  renameSession,
  svgEl,
  type SessionRenamed,
} from "./dom.js";
import {
  agentSuggestions,
  mergeSuggestions,
  slashSuggestions,
  type AgentOption,
  type Suggestion,
} from "./mentions.js";
import type { ScreenContext } from "./shell.js";
import {
  appendToolActivity,
  markRunningToolsError,
  renderAgentHeader,
  renderAssistantTurn,
  renderInlineApproval,
  renderNotice,
  renderUserTurn,
} from "./transcript.js";

const SESSION_KEY = "clawhouse.session";
const MODEL_KEY = "clawhouse.model";
const VARIANT_KEY = "clawhouse.chat_variant";
const WAITING_FOR_ANSWER = "Esperando sua resposta na pergunta acima.";

export type ChatVariant = "classic" | "studio" | "capsule";

interface FormattedModel {
  id: string;
  name: string;
  provider: string;
  tag: string;
  icon: string;
}

function formatModelOption(id: string, label: string): FormattedModel {
  const idLower = id.toLowerCase();
  const labelLower = label.toLowerCase();
  let provider = "Databricks";
  let icon = "⚡";
  if (idLower.includes("gpt") || idLower.includes("openai")) {
    provider = "OpenAI";
    icon = "❇️";
  } else if (idLower.includes("claude") || idLower.includes("anthropic")) {
    provider = "Anthropic";
    icon = "✴️";
  } else if (idLower.includes("meta") || idLower.includes("llama")) {
    provider = "Meta";
    icon = "🦙";
  } else if (idLower.includes("dbrx") || labelLower.includes("dbrx")) {
    provider = "Databricks";
    icon = "🧱";
  } else if (idLower.includes("mistral")) {
    provider = "Mistral";
    icon = "🌪️";
  }

  let name = label;
  if (name.startsWith("Databricks · ")) name = name.slice("Databricks · ".length);
  if (name.startsWith("databricks-")) name = name.slice("databricks-".length);
  name = name.replace(/-instruct$/i, "").replace(/-chat$/i, "");
  name = name.replace(/meta-llama-/i, "Llama-");
  name = name.replace(/(\d+)-(\d+)/g, "$1.$2");
  if (/gpt-?4o/i.test(label) || /gpt-?4o/i.test(id)) {
    name = "GPT-4o";
  } else if (/gpt-?4/i.test(label) || /gpt-?4/i.test(id)) {
    name = "GPT-4";
  } else {
    name = name
      .split("-")
      .map((p) => {
        const lower = p.toLowerCase();
        if (
          lower === "3" ||
          lower === "1" ||
          lower === "2" ||
          lower === "70b" ||
          lower === "8b" ||
          lower === "405b"
        ) {
          return p.toUpperCase();
        }
        return p.charAt(0).toUpperCase() + p.slice(1);
      })
      .join(" ");
  }

  let tag = "Default";
  if (
    idLower.includes("fast") ||
    idLower.includes("mini") ||
    idLower.includes("flash") ||
    idLower.includes("8b")
  ) {
    tag = "Fast";
  } else if (
    idLower.includes("reasoning") ||
    idLower.includes("think") ||
    idLower.includes("r1") ||
    idLower.includes("70b")
  ) {
    tag = "Reasoning";
  }

  return { id, name, provider, tag, icon };
}

interface Entry {
  role: "user" | "assistant" | "tool_call" | "tool_result" | "notice";
  content: string;
  tool_name: string | null;
  agent_id?: string | null;
  model?: string | null;
}

interface TranscriptBody {
  entries?: Entry[];
  run_state?: string;
}

const WAITING_FOR_APPROVAL = "Ação aguardando aprovação acima.";
const STILL_RUNNING = "O agente ainda está trabalhando nesta sessão…";
const POLL_MS = 1500;

interface ModelOption {
  id: string;
  label: string;
  default: boolean;
}

interface SseFrame {
  event: string;
  data: string;
}

export function mount(root: HTMLElement, ctx: ScreenContext): void {
  const header = el("header", "chat-header");
  header.id = "chat-header";
  const titleLabel = el("h1", "chat-title", UNTITLED);
  const renameButton = el("button", "chat-action", "Rename");
  renameButton.id = "chat-rename";
  renameButton.type = "button";
  const clearButton = el("button", "chat-action chat-action-danger", "Clear transcript");
  clearButton.id = "chat-clear";
  clearButton.type = "button";
  const headerActions = el("div", "chat-header-actions");

  // Variant Switcher Pill Group
  const variantSwitcher = el("div", "chat-variant-switcher");
  variantSwitcher.setAttribute("role", "radiogroup");
  variantSwitcher.setAttribute("aria-label", "Composer layout variant");

  const variantBtnClassic = el("button", "variant-pill active", "1. OpenClaw Classic");
  variantBtnClassic.type = "button";
  variantBtnClassic.dataset.variant = "classic";
  variantBtnClassic.title = "Variant 1: OpenClaw Classic Unified Card (2026.9.3 / 2026.9.4)";

  const variantBtnStudio = el("button", "variant-pill", "2. Studio HUD");
  variantBtnStudio.type = "button";
  variantBtnStudio.dataset.variant = "studio";
  variantBtnStudio.title = "Variant 2: Studio Pro HUD (2026.9.2 Two-Pane & MCP Studio)";

  const variantBtnCapsule = el("button", "variant-pill", "3. Agent Capsule");
  variantBtnCapsule.type = "button";
  variantBtnCapsule.dataset.variant = "capsule";
  variantBtnCapsule.title = "Variant 3: Agent Capsule & Floating Dock (2026.9.5 Automation & Drafts)";

  const variantBtnCompare = el("button", "variant-pill variant-compare-btn", "✨ Compare 3");
  variantBtnCompare.type = "button";
  variantBtnCompare.title = "Compare all 3 variants side-by-side with live simulator";

  variantSwitcher.append(variantBtnClassic, variantBtnStudio, variantBtnCapsule, variantBtnCompare);
  headerActions.append(variantSwitcher, renameButton, clearButton);
  header.append(titleLabel, headerActions);

  const transcript = el("section", "log");
  transcript.id = "log";
  transcript.setAttribute("aria-live", "polite");

  const form = document.createElement("form");
  form.id = "composer";
  form.className = "composer";
  form.dataset.variant = "classic";

  // Variant 2: Studio Upper Deck (Agent Roster & Horizon Meter)
  const studioDeck = el("div", "studio-deck");
  const studioAgentStrip = el("div", "studio-agent-strip");
  const studioActiveAgentBadge = el("span", "studio-active-agent", "● 🦀 main (Lead)");
  const studioDelegateLabel = el("span", "studio-delegate-label", "Delegate:");
  const studioDelegateChips = el("div", "studio-delegate-chips");
  studioAgentStrip.append(studioActiveAgentBadge, studioDelegateLabel, studioDelegateChips);

  const studioCtxStrip = el("div", "studio-ctx-strip");
  studioCtxStrip.title = "Context Horizon Meter — Click for details";
  const studioCtxTrack = el("div", "studio-ctx-track");
  const studioCtxFill = el("div", "studio-ctx-fill");
  studioCtxTrack.append(studioCtxFill);
  const studioCtxLabel = el("span", "studio-ctx-label", "0 / 128k (0%)");
  studioCtxStrip.append(studioCtxTrack, studioCtxLabel);
  studioDeck.append(studioAgentStrip, studioCtxStrip);

  // Variant 3: Capsule Top Ribbon (Active Persona & Draft Status)
  const capsuleRibbon = el("div", "capsule-ribbon");
  const capsuleAgentBadge = el("div", "capsule-agent-badge");
  const capsulePulse = el("span", "capsule-pulse-dot");
  const capsuleAgentLabel = el("span", "capsule-agent-name", "🦀 main");
  const capsulePersonaTag = el("span", "capsule-persona-tag", "Active Agent");
  capsuleAgentBadge.append(capsulePulse, capsuleAgentLabel, capsulePersonaTag);

  const capsuleDraftBadge = el("div", "capsule-draft-badge");
  const capsuleDraftDot = el("span", "capsule-draft-dot");
  const capsuleDraftText = el("span", "capsule-draft-text", "Ready");
  capsuleDraftBadge.append(capsuleDraftDot, capsuleDraftText);
  capsuleRibbon.append(capsuleAgentBadge, capsuleDraftBadge);

  const input = document.createElement("textarea");
  input.id = "message";
  input.rows = 1;
  input.placeholder = "Message 🦀 main (or type @ to delegate)...";
  input.required = true;

  const toolbar = el("div", "composer-toolbar");

  // Left Toolbar: Action button (+), Agent Selector Pill, Typing Status, Studio Commands
  const toolbarLeft = el("div", "composer-toolbar-left");

  const attachBtn = el("button", "composer-action-btn", "+");
  attachBtn.type = "button";
  attachBtn.title = "Add attachments, SQL tables, or tools";
  attachBtn.setAttribute("aria-label", "Attachments and tools");

  const agentBadge = el("span", "agent-badge");
  agentBadge.id = "agent-badge";
  agentBadge.title = "Active agent";
  const agentEmojiSpan = el("span", "agent-badge-emoji", "🦀");
  const agentNameSpan = el("span", "agent-badge-label", "main");
  agentBadge.append(agentEmojiSpan, agentNameSpan);

  const typingStatusPill = el("span", "typing-status-pill");
  const typingPulse = el("span", "typing-pulse-dot");
  const typingStatusText = el("span", "typing-status-text", "Typing · not sent");
  typingStatusPill.append(typingPulse, typingStatusText);
  typingStatusPill.hidden = true;

  const studioCmdBtn = el("button", "studio-cmd-pill", "/ Commands");
  studioCmdBtn.type = "button";
  studioCmdBtn.title = "Open slash command menu";

  const studioToolChip = el("span", "studio-tool-chip", "🛠 6 Tools");
  studioToolChip.title = "Active capabilities: Lakeflow, Lakebase, SQL Warehouse";

  toolbarLeft.append(attachBtn, agentBadge, typingStatusPill, studioCmdBtn, studioToolChip);

  // Right Toolbar: Custom Model Selector, Context Meter with popover, Abort, Send
  const toolbarRight = el("div", "composer-toolbar-right");

  const modelSelectorWrapper = el("div", "model-selector-wrapper");
  const modelLabel = el("label", "sr", "Model");
  modelLabel.htmlFor = "model";
  const modelPicker = document.createElement("select");
  modelPicker.id = "model";
  modelPicker.className = "model-pill";

  const modelCustomTrigger = el("button", "model-custom-trigger");
  modelCustomTrigger.id = "model-custom-trigger";
  modelCustomTrigger.type = "button";
  modelCustomTrigger.setAttribute("aria-haspopup", "listbox");
  modelCustomTrigger.setAttribute("aria-expanded", "false");
  modelCustomTrigger.title = "Choose model endpoint";
  const modelTriggerIcon = el("span", "model-trigger-icon", "⚡");
  const modelTriggerName = el("span", "model-trigger-name", "Model");
  const modelTriggerChevron = el("span", "model-trigger-chevron", "▾");
  modelCustomTrigger.append(modelTriggerIcon, modelTriggerName, modelTriggerChevron);

  const modelCustomPopover = el("div", "model-custom-popover");
  modelCustomPopover.id = "model-custom-popover";
  modelCustomPopover.hidden = true;
  modelCustomPopover.setAttribute("role", "listbox");

  modelSelectorWrapper.append(modelLabel, modelPicker, modelCustomTrigger, modelCustomPopover);

  // Context-window meter: a ring showing the input tokens sent to the model + popover.
  const meter = el("div", "ctx-meter");
  meter.id = "ctx-meter";
  meter.dataset.level = "ok";
  const ringCircumference = 2 * Math.PI * 15.5;
  const ringFill = svgEl("circle", {
    class: "ctx-fill",
    cx: "18",
    cy: "18",
    r: "15.5",
    "stroke-dasharray": String(ringCircumference),
    "stroke-dashoffset": String(ringCircumference),
  });
  const ring = svgEl("svg", {
    class: "ctx-ring",
    viewBox: "0 0 36 36",
    "aria-hidden": "true",
  });
  ring.append(
    svgEl("circle", { class: "ctx-track", cx: "18", cy: "18", r: "15.5" }),
    ringFill,
  );
  const meterLabel = el("span", "ctx-label", "0");

  // Horizon mini bar (integrated like Studio B)
  const horizonBar = el("div", "ctx-horizon-bar");
  const horizonFill = el("div", "ctx-horizon-fill");
  horizonBar.append(horizonFill);

  const meterCapacity = el("span", "ctx-capacity", "");
  const meterPct = el("span", "ctx-pct", "");
  const meterDivider = el("span", "ctx-divider", "·");
  const meterCostPill = el("span", "ctx-cost-pill", "$0.00");
  const meterChevron = el("span", "ctx-chevron", "▾");

  const ctxPopover = el("div", "ctx-popover");
  ctxPopover.id = "ctx-popover";
  ctxPopover.hidden = true;
  meter.append(
    ring,
    horizonBar,
    meterLabel,
    meterCapacity,
    meterPct,
    meterDivider,
    meterCostPill,
    meterChevron,
    ctxPopover,
  );

  const abortButton = el("button", "abort", "Stop");
  abortButton.id = "abort";
  abortButton.type = "button";
  abortButton.hidden = true;

  const sendButton = el("button", "send");
  sendButton.type = "submit";
  const sendIcon = svgEl("svg", {
    width: "16",
    height: "16",
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    "stroke-width": "2.5",
    "stroke-linecap": "round",
    "stroke-linejoin": "round",
    "aria-hidden": "true",
  });
  sendIcon.append(
    svgEl("line", { x1: "12", y1: "19", x2: "12", y2: "5" }),
    svgEl("polyline", { points: "5 12 12 5 19 12" }),
  );
  const sendLabel = el("span", "send-label", "Send");
  const sendShortcut = el("span", "send-shortcut", "⌘↵");
  sendButton.append(sendIcon, sendLabel, sendShortcut);

  toolbarRight.append(modelSelectorWrapper, meter, abortButton, sendButton);
  toolbar.append(toolbarLeft, toolbarRight);

  const statusLine = el("p", "status");
  statusLine.id = "status";
  statusLine.setAttribute("role", "status");

  form.append(studioDeck, capsuleRibbon, input, toolbar, statusLine);
  root.append(header, transcript, form);

  let draft: HTMLElement | null = null;
  let blocked: string | null = null;
  let running = false;
  let liveTurn: string | null = null;
  let polling = false;
  let questionAsked = false;
  let draftText = "";
  let controller: AbortController | null = null;

  let contextTokens = 0;
  let outputTokens = 0;
  let contextWindow: number | null = null;

  function getModelPricing(modelId: string): { inputPerMillion: number; outputPerMillion: number; label: string } {
    const m = modelId.toLowerCase();
    if (m.includes("llama-3-3-70b") || m.includes("llama-3.3-70b")) {
      return { inputPerMillion: 0.40, outputPerMillion: 1.00, label: "Llama 3.3 70B ($0.40/1M)" };
    }
    if (m.includes("llama-3-1-8b") || m.includes("llama-3.1-8b") || m.includes("8b")) {
      return { inputPerMillion: 0.05, outputPerMillion: 0.15, label: "Llama 3.1 8B ($0.05/1M)" };
    }
    if (m.includes("llama-3-1-405b") || m.includes("llama-3.1-405b") || m.includes("405b")) {
      return { inputPerMillion: 1.50, outputPerMillion: 3.00, label: "Llama 3.1 405B ($1.50/1M)" };
    }
    if (m.includes("dbrx")) {
      return { inputPerMillion: 0.75, outputPerMillion: 2.25, label: "DBRX ($0.75/1M)" };
    }
    if (m.includes("claude-3-5-sonnet") || m.includes("claude-3-7-sonnet") || m.includes("sonnet")) {
      return { inputPerMillion: 3.00, outputPerMillion: 15.00, label: "Claude 3.5 Sonnet ($3.00/1M)" };
    }
    if (m.includes("claude-3-5-haiku") || m.includes("haiku")) {
      return { inputPerMillion: 0.80, outputPerMillion: 4.00, label: "Claude 3.5 Haiku ($0.80/1M)" };
    }
    if (m.includes("gpt-4o-mini")) {
      return { inputPerMillion: 0.15, outputPerMillion: 0.60, label: "GPT-4o-mini ($0.15/1M)" };
    }
    if (m.includes("gpt-4o") || m.includes("gpt-4")) {
      return { inputPerMillion: 2.50, outputPerMillion: 10.00, label: "GPT-4o ($2.50/1M)" };
    }
    return { inputPerMillion: 0.50, outputPerMillion: 1.50, label: "Databricks Standard ($0.50/1M)" };
  }

  function calculateCost(modelId: string, inTokens: number, outTokens: number): { inCost: number; outCost: number; totalCost: number; rateLabel: string } {
    const pricing = getModelPricing(modelId);
    const inCost = (inTokens / 1_000_000) * pricing.inputPerMillion;
    const outCost = (outTokens / 1_000_000) * pricing.outputPerMillion;
    return {
      inCost,
      outCost,
      totalCost: inCost + outCost,
      rateLabel: pricing.label,
    };
  }

  function formatCost(dollars: number): string {
    if (dollars <= 0) return "$0.00";
    if (dollars < 0.001) return "<$0.001";
    if (dollars < 0.01) return `$${dollars.toFixed(3)}`;
    return `$${dollars.toFixed(2)}`;
  }

  function formatTokens(value: number): string {
    if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}m`;
    if (value >= 1_000) return `${Math.round(value / 1000)}k`;
    return String(value);
  }

  // Absolute pressure thresholds for the sent-context size.
  function usageLevel(tokens: number): string {
    if (tokens >= 300_000) return "danger";
    if (tokens >= 250_000) return "orange";
    if (tokens >= 150_000) return "warn";
    return "ok";
  }

  function renderCtxPopover(denominator: number, ratio: number, level: string): void {
    ctxPopover.replaceChildren();
    const pricing = calculateCost(modelPicker.value || "", contextTokens, outputTokens);

    const title = el("div", "ctx-popover-title", "Token & Cost Ledger");

    const horizonBar = el("div", "ctx-popover-horizon");
    const horizonFill = el("div", "ctx-popover-horizon-fill");
    horizonFill.style.width = `${Math.min(100, Math.round(ratio * 100))}%`;
    horizonFill.dataset.level = level;
    horizonBar.append(horizonFill);

    const rowTokens = el("div", "ctx-popover-row");
    rowTokens.append(el("span", "", "Tokens Used"), el("strong", "", contextTokens.toLocaleString()));
    const rowMax = el("div", "ctx-popover-row");
    rowMax.append(el("span", "", "Window Limit"), el("strong", "", `${denominator.toLocaleString()} tokens`));
    const rowPct = el("div", "ctx-popover-row");
    rowPct.append(el("span", "", "Capacity Used"), el("strong", "", `${(ratio * 100).toFixed(1)}%`));
    const rowRemaining = el("div", "ctx-popover-row");
    rowRemaining.append(
      el("span", "", "Remaining"),
      el("strong", "", `${Math.max(0, denominator - contextTokens).toLocaleString()} tokens`),
    );

    const rowCost = el("div", "ctx-popover-row ctx-popover-cost-row");
    rowCost.append(
      el("span", "", "Est. Turn Cost"),
      el("strong", "ctx-cost-highlight", formatCost(pricing.totalCost)),
    );

    const rowTier = el("div", "ctx-popover-row ctx-popover-tier");
    rowTier.append(el("span", "", "Pricing Tier"), el("span", "model-badge-tag", pricing.rateLabel));

    const rowHealth = el("div", "ctx-popover-row");
    rowHealth.append(el("span", "", "Health Gauge"), el("strong", `status-${level}`, level.toUpperCase()));
    ctxPopover.append(title, horizonBar, rowTokens, rowMax, rowPct, rowRemaining, rowCost, rowTier, rowHealth);
  }

  function renderMeter(): void {
    const denominator = contextWindow ?? 128_000;
    const ratio =
      denominator > 0 ? Math.min(1, contextTokens / denominator) : 0;
    const level = usageLevel(contextTokens);
    const pct = Math.round(ratio * 100);
    const pricing = calculateCost(modelPicker.value || "", contextTokens, outputTokens);

    meter.dataset.level = level;
    ringFill.setAttribute(
      "stroke-dashoffset",
      String(ringCircumference * (1 - ratio)),
    );
    meterLabel.textContent = formatTokens(contextTokens);

    horizonFill.style.width = `${Math.min(100, pct)}%`;
    horizonFill.dataset.level = level;
    meterCapacity.textContent = `/ ${formatTokens(denominator)}`;
    meterPct.textContent = `(${pct}%)`;
    meterCostPill.textContent = formatCost(pricing.totalCost);

    const detail = contextWindow
      ? `${contextTokens.toLocaleString()} / ${contextWindow.toLocaleString()} tokens (${pct}%) · ${formatCost(pricing.totalCost)}`
      : `${contextTokens.toLocaleString()} tokens · ${formatCost(pricing.totalCost)}`;
    meter.title = `Context & Cost: ${detail} — Click for full ledger`;
    meter.setAttribute("aria-label", `Context: ${detail}`);

    // Synchronize Variant 2: Studio Horizon Meter
    studioCtxFill.style.width = `${Math.min(100, pct)}%`;
    studioCtxFill.dataset.level = level;
    studioCtxLabel.textContent = `${formatTokens(contextTokens)} / ${formatTokens(denominator)} (${pct}%) · ${formatCost(pricing.totalCost)}`;

    renderCtxPopover(denominator, ratio, level);
  }

  // Emoji per handle, for headers rebuilt from a reloaded transcript.
  const agentEmoji = new Map<string, string>();
  let agentOptions: AgentOption[] = [];

  let currentVariant: ChatVariant = "classic";
  const storedVariant = (sessionStorage.getItem(VARIANT_KEY) ||
    localStorage.getItem(VARIANT_KEY)) as ChatVariant | null;
  if (storedVariant && ["classic", "studio", "capsule"].includes(storedVariant)) {
    currentVariant = storedVariant;
  }

  let currentAgentName = ctx.url.searchParams.get("agent") || "main";
  let currentAgentEmoji = "🦀";

  function updatePlaceholder(): void {
    const emoji =
      agentEmoji.get(currentAgentName) ||
      (currentAgentName === "main" ? "🦀" : "🤖");
    currentAgentEmoji = emoji;
    if (currentVariant === "classic") {
      input.placeholder = `Message ${emoji} ${currentAgentName} (or type @ to delegate)...`;
    } else if (currentVariant === "studio") {
      input.placeholder = `Message @${currentAgentName} or type / for commands...`;
    } else {
      input.placeholder = `Prompt ${emoji} ${currentAgentName}...`;
    }
    agentEmojiSpan.textContent = emoji;
    agentNameSpan.textContent = currentAgentName;
    capsuleAgentLabel.textContent = `${emoji} ${currentAgentName}`;
    studioActiveAgentBadge.textContent = `● ${emoji} ${currentAgentName} (Lead)`;
  }

  function applyVariant(variant: ChatVariant): void {
    currentVariant = variant;
    form.dataset.variant = variant;
    localStorage.setItem(VARIANT_KEY, variant);
    sessionStorage.setItem(VARIANT_KEY, variant);
    for (const btn of [variantBtnClassic, variantBtnStudio, variantBtnCapsule]) {
      const match = btn.dataset.variant === variant;
      btn.classList.toggle("active", match);
      btn.setAttribute("aria-checked", String(match));
    }
    updatePlaceholder();
  }

  variantBtnClassic.addEventListener("click", () => applyVariant("classic"));
  variantBtnStudio.addEventListener("click", () => applyVariant("studio"));
  variantBtnCapsule.addEventListener("click", () => applyVariant("capsule"));
  variantBtnCompare.addEventListener("click", () => openPrototypeModal());

  function updateDraftStatus(): void {
    const val = input.value.trim();
    const hasText = val.length > 0;
    typingStatusPill.hidden = !hasText;
    if (hasText) {
      const wordCount = val.split(/\s+/).filter(Boolean).length;
      capsuleDraftBadge.classList.add("has-draft");
      capsuleDraftText.textContent = `Typing · not sent (${wordCount} words)`;
    } else {
      capsuleDraftBadge.classList.remove("has-draft");
      capsuleDraftText.textContent = "Ready";
    }
  }

  function selectAgent(name: string, emoji?: string): void {
    currentAgentName = name;
    if (emoji) agentEmoji.set(name, emoji);
    updatePlaceholder();
    renderAgentOptions();
    input.focus();
  }

  function renderAgentOptions(): void {
    studioDelegateChips.replaceChildren();

    const fullList =
      agentOptions.length > 0
        ? agentOptions
        : [
            {
              name: "main",
              signature_emoji: "🦀",
              description: "Default workspace orchestrator",
            },
          ];

    for (const ag of fullList) {
      const isSelected = ag.name === currentAgentName;
      if (!isSelected) {
        const chip = el("button", "delegate-chip", `+ @${ag.name}`);
        chip.type = "button";
        chip.title = `Delegate turn to @${ag.name}`;
        chip.addEventListener("click", () => {
          const prefix = input.value.trim().length > 0 ? " " : "";
          input.value = `${input.value}${prefix}@${ag.name} `;
          grow();
          input.focus();
          inspectTrigger();
        });
        studioDelegateChips.append(chip);
      }
    }
  }

  function renderModelOptions(models: ModelOption[]): void {
    modelCustomPopover.replaceChildren();
    const title = el("div", "model-popover-header", "Available Model Endpoints");
    modelCustomPopover.append(title);

    const activeId =
      modelPicker.value ||
      (models.find((m) => m.default)?.id ?? models[0]?.id);

    for (const opt of models) {
      const fmt = formatModelOption(opt.id, opt.label);
      const isSelected = opt.id === activeId;
      if (isSelected) {
        modelTriggerIcon.textContent = fmt.icon;
        modelTriggerName.textContent = fmt.name;
        modelTriggerName.title = opt.label;
      }

      const item = el(
        "button",
        `model-popover-item ${isSelected ? "selected" : ""}`,
      );
      item.type = "button";
      item.dataset.modelId = opt.id;

      const left = el("div", "model-popover-info");
      const label = el("strong", "model-item-name", `${fmt.icon} ${fmt.name}`);
      left.append(label);

      const meta = el("div", "model-popover-meta");
      meta.append(el("span", "model-badge-tag", fmt.provider));
      if (fmt.tag !== "Default") {
        meta.append(
          el("span", `model-badge-tag tag-${fmt.tag.toLowerCase()}`, fmt.tag),
        );
      }
      if (opt.default) {
        meta.append(el("span", "model-badge-tag", "Default"));
      }
      if (isSelected) {
        meta.append(el("span", "model-badge-tag tag-fast", "✓"));
      }

      item.append(left, meta);
      item.addEventListener("click", () => {
        modelPicker.value = opt.id;
        sessionStorage.setItem(MODEL_KEY, opt.id);
        modelTriggerIcon.textContent = fmt.icon;
        modelTriggerName.textContent = fmt.name;
        modelCustomPopover.hidden = true;
        modelCustomTrigger.setAttribute("aria-expanded", "false");
        modelPicker.dispatchEvent(new Event("change", { bubbles: true }));
        renderModelOptions(models);
      });

      modelCustomPopover.append(item);
    }
  }

  function closeAllCustomPopovers(): void {
    modelCustomPopover.hidden = true;
    modelCustomTrigger.setAttribute("aria-expanded", "false");
    ctxPopover.hidden = true;
  }

  modelCustomTrigger.addEventListener("click", (e) => {
    e.stopPropagation();
    const next = modelCustomPopover.hidden;
    closeAllCustomPopovers();
    modelCustomPopover.hidden = !next;
    modelCustomTrigger.setAttribute("aria-expanded", String(!next));
  });

  meter.addEventListener("click", (e) => {
    e.stopPropagation();
    const next = ctxPopover.hidden;
    closeAllCustomPopovers();
    ctxPopover.hidden = !next;
  });

  studioCtxStrip.addEventListener("click", (e) => {
    e.stopPropagation();
    const next = ctxPopover.hidden;
    closeAllCustomPopovers();
    ctxPopover.hidden = !next;
  });

  function openPrototypeModal(): void {
    let modal = document.querySelector("#prototype-modal") as HTMLElement | null;
    if (modal) modal.remove();

    modal = el("div", "prototype-modal-backdrop");
    modal.id = "prototype-modal";

    const dialog = el("div", "prototype-modal-dialog");

    const mHeader = el("div", "prototype-modal-header");
    const mTitle = el(
      "h2",
      "prototype-modal-title",
      "Clawhouse Chat Interface Prototypes (OpenClaw References)",
    );
    const mClose = el("button", "prototype-modal-close", "✕");
    mClose.type = "button";
    mClose.setAttribute("aria-label", "Close prototype modal");
    mClose.addEventListener("click", () => modal?.remove());
    mHeader.append(mTitle, mClose);

    const mBody = el("div", "prototype-modal-body");

    // Simulator Bar
    const simBar = el("div", "prototype-sim-bar");
    const simTokensGroup = el("div", "prototype-sim-group");
    simTokensGroup.append(el("label", "", "Simulate Context:"));
    const simSlider = document.createElement("input");
    simSlider.type = "range";
    simSlider.className = "prototype-sim-slider";
    simSlider.min = "0";
    simSlider.max = "320000";
    simSlider.step = "5000";
    simSlider.value = String(contextTokens || 12000);

    const simValueLabel = el(
      "strong",
      "",
      `${formatTokens(Number(simSlider.value))} tokens (${usageLevel(Number(simSlider.value))})`,
    );
    simTokensGroup.append(simSlider, simValueLabel);

    const simAgentGroup = el("div", "prototype-sim-group");
    simAgentGroup.append(el("label", "", "Test Agent:"));
    for (const testAgent of [
      { name: "main", emoji: "🦀" },
      { name: "analyst", emoji: "📊" },
      { name: "sql-expert", emoji: "💾" },
    ]) {
      const aBtn = el(
        "button",
        "prototype-sim-btn",
        `${testAgent.emoji} @${testAgent.name}`,
      );
      aBtn.type = "button";
      aBtn.addEventListener("click", () => {
        selectAgent(testAgent.name, testAgent.emoji);
        updateModalPreview();
      });
      simAgentGroup.append(aBtn);
    }

    simBar.append(simTokensGroup, simAgentGroup);

    // Grid of 3 Variants
    const grid = el("div", "prototype-grid");

    // Card 1: OpenClaw Classic
    const card1 = el(
      "div",
      `prototype-card ${currentVariant === "classic" ? "active-variant" : ""}`,
    );
    const card1Head = el("div", "prototype-card-head");
    card1Head.append(
      el("h3", "prototype-card-title", "1. OpenClaw Classic Card"),
      el("span", "prototype-card-badge", "Flagship 2026.9.3 / 2026.9.4"),
    );
    const card1Desc = el(
      "p",
      "prototype-card-desc",
      "Direct port of OpenClaw's primary unified composer card: inset rounded container, seamless borderless prompt, inside toolbar with agent & model pills, typing status badge, and signature circular send button.",
    );
    const card1Features = el("ul", "prototype-card-features");
    card1Features.append(
      el("li", "", "Unified 18px rounded card with borderless textarea"),
      el(
        "li",
        "",
        "Inside toolbar: Attachment +, Active Persona pill, Model popover",
      ),
      el("li", "", "Typing · not sent draft state with amber pulsing dot"),
      el("li", "", "Signature 34px circular accent Send button (↑)"),
    );
    const card1Select = el(
      "button",
      "prototype-select-btn",
      currentVariant === "classic" ? "Currently Active" : "Activate Variant 1",
    );
    card1Select.type = "button";
    card1Select.addEventListener("click", () => {
      applyVariant("classic");
      modal?.remove();
    });
    card1.append(card1Head, card1Desc, card1Features, card1Select);

    // Card 2: Studio Pro HUD
    const card2 = el(
      "div",
      `prototype-card ${currentVariant === "studio" ? "active-variant" : ""}`,
    );
    const card2Head = el("div", "prototype-card-head");
    card2Head.append(
      el("h3", "prototype-card-title", "2. Studio Pro HUD"),
      el("span", "prototype-card-badge", "Two-Pane & MCP 2026.9.2"),
    );
    const card2Desc = el(
      "p",
      "prototype-card-desc",
      "Cockpit layout engineered for data teams: upper deck with Agent Roster and quick delegate chips (+ @analyst), horizontal Context Horizon Meter, and lower command bay with slash palette.",
    );
    const card2Features = el("ul", "prototype-card-features");
    card2Features.append(
      el(
        "li",
        "",
        "Upper Deck: Active Agent badge + 1-click delegate chips (+ @analyst, + @sql)",
      ),
      el(
        "li",
        "",
        "Horizontal Context Horizon Meter with percentage & color gauge",
      ),
      el(
        "li",
        "",
        "Lower Bay: / Slash commands trigger, Tools counter, Databricks serving endpoint",
      ),
      el("li", "", "Fast, distraction-free prompt editor"),
    );
    const card2Select = el(
      "button",
      "prototype-select-btn",
      currentVariant === "studio" ? "Currently Active" : "Activate Variant 2",
    );
    card2Select.type = "button";
    card2Select.addEventListener("click", () => {
      applyVariant("studio");
      modal?.remove();
    });
    card2.append(card2Head, card2Desc, card2Features, card2Select);

    // Card 3: Agent Capsule & Floating Dock
    const card3 = el(
      "div",
      `prototype-card ${currentVariant === "capsule" ? "active-variant" : ""}`,
    );
    const card3Head = el("div", "prototype-card-head");
    card3Head.append(
      el("h3", "prototype-card-title", "3. Agent Capsule & Dock"),
      el("span", "prototype-card-badge", "Automation 2026.9.5"),
    );
    const card3Desc = el(
      "p",
      "prototype-card-desc",
      "Modern floating capsule with glass backdrop blur: top persona ribbon with live word counter, segmented docked pills for agent, model, and context headroom, plus elevated Send ⌘↵ pill.",
    );
    const card3Features = el("ul", "prototype-card-features");
    card3Features.append(
      el("li", "", "Floating capsule with 24px radius & backdrop-filter blur"),
      el(
        "li",
        "",
        "Top Ribbon: Pulse persona indicator + Live draft word count tracker",
      ),
      el(
        "li",
        "",
        "Docked Segmented Pills: [🦀 main ▾] [⚡ Llama 3.3 ▾] [🟢 Context free]",
      ),
      el("li", "", "Elevated Pill Send button with ⌘↵ shortcut hint"),
    );
    const card3Select = el(
      "button",
      "prototype-select-btn",
      currentVariant === "capsule" ? "Currently Active" : "Activate Variant 3",
    );
    card3Select.type = "button";
    card3Select.addEventListener("click", () => {
      applyVariant("capsule");
      modal?.remove();
    });
    card3.append(card3Head, card3Desc, card3Features, card3Select);

    grid.append(card1, card2, card3);
    mBody.append(simBar, grid);
    dialog.append(mHeader, mBody);
    modal.append(dialog);

    function updateModalPreview(): void {
      const val = Number(simSlider.value);
      const lvl = usageLevel(val);
      simValueLabel.textContent = `${formatTokens(val)} tokens (${lvl})`;
      contextTokens = val;
      renderMeter();
    }

    simSlider.addEventListener("input", updateModalPreview);

    modal.addEventListener("click", (e) => {
      if (e.target === modal) modal.remove();
    });

    document.body.append(modal);
  }

  applyVariant(currentVariant);
  renderMeter();

  function sessionId(): string {
    const fromUrl = ctx.url.searchParams.get("session");
    if (fromUrl) {
      sessionStorage.setItem(SESSION_KEY, fromUrl);
      return fromUrl;
    }
    const existing = sessionStorage.getItem(SESSION_KEY);
    if (existing) return existing;
    const created = crypto.randomUUID();
    sessionStorage.setItem(SESSION_KEY, created);
    return created;
  }

  const scrollBottomBtn = el("button", "scroll-bottom-btn");
  scrollBottomBtn.id = "scroll-bottom";
  scrollBottomBtn.type = "button";
  scrollBottomBtn.title = "Scroll to bottom";
  scrollBottomBtn.setAttribute("aria-label", "Scroll to bottom");
  scrollBottomBtn.hidden = true;
  const downArrow = svgEl("svg", {
    width: "16",
    height: "16",
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    "stroke-width": "2",
    "stroke-linecap": "round",
    "stroke-linejoin": "round",
    "aria-hidden": "true",
  });
  downArrow.append(
    svgEl("line", { x1: "12", y1: "5", x2: "12", y2: "19" }),
    svgEl("polyline", { points: "19 12 12 19 5 12" }),
  );
  scrollBottomBtn.append(downArrow);
  root.append(scrollBottomBtn);

  let userScrolledUp = false;

  function checkScrollPosition(): void {
    const distanceFromBottom =
      transcript.scrollHeight - transcript.scrollTop - transcript.clientHeight;
    if (distanceFromBottom > 80) {
      userScrolledUp = true;
      scrollBottomBtn.hidden = false;
    } else if (distanceFromBottom <= 40) {
      userScrolledUp = false;
      scrollBottomBtn.hidden = true;
    }
  }

  transcript.addEventListener("scroll", () => {
    checkScrollPosition();
  });

  scrollBottomBtn.addEventListener("click", () => {
    transcript.scrollTop = transcript.scrollHeight;
    userScrolledUp = false;
    scrollBottomBtn.hidden = true;
  });

  function scrollToBottom(force = false): void {
    if (force || !userScrolledUp) {
      transcript.scrollTop = transcript.scrollHeight;
    }
  }

  const DRAFT_PREFIX = "clawhouse.draft.";

  function draftKey(sId: string): string {
    return `${DRAFT_PREFIX}${sId}`;
  }

  function restoreDraft(): void {
    const saved = sessionStorage.getItem(draftKey(sessionId()));
    if (saved) {
      input.value = saved;
      grow();
    }
  }

  function saveDraft(): void {
    const val = input.value;
    if (val.length > 0) {
      sessionStorage.setItem(draftKey(sessionId()), val);
    } else {
      sessionStorage.removeItem(draftKey(sessionId()));
    }
  }

  function clearDraft(): void {
    sessionStorage.removeItem(draftKey(sessionId()));
  }

  restoreDraft();

  let sessionTitle = "";

  function showTitle(title: string): void {
    sessionTitle = title;
    titleLabel.textContent = title || UNTITLED;
  }

  async function loadTitle(): Promise<void> {
    try {
      const response = await fetch(`/api/sessions/${sessionId()}`);
      if (!response.ok) return;
      const body = (await response.json()) as { title?: string };
      showTitle(body.title ?? "");
    } catch {
      // The header keeps its last title.
    }
  }

  function startRename(): void {
    if (titleLabel.hidden) return;
    editTitle(
      titleLabel,
      sessionTitle,
      async (title) => {
        const saved = await renameSession(sessionId(), title);
        if (saved !== null) sessionTitle = saved;
        return saved;
      },
      "chat-title-input",
    );
  }

  async function clearTranscript(): Promise<void> {
    if (!confirm("Clear this session's transcript? The session stays.")) return;
    if (!(await clearSession(sessionId()))) {
      setStatus("The transcript could not be cleared.");
      return;
    }
    transcript.replaceChildren(renderNotice("Transcript cleared."));
    void loadTitle();
  }

  renameButton.addEventListener("click", startRename);
  titleLabel.addEventListener("click", startRename);
  clearButton.addEventListener("click", () => void clearTranscript());
  window.addEventListener(SESSION_RENAMED, (event) => {
    const detail = (event as CustomEvent<SessionRenamed>).detail;
    if (header.isConnected && detail.id === sessionId()) showTitle(detail.title);
  });

  function showEmpty(): void {
    transcript.replaceChildren(el("p", "empty", "This session is empty."));
  }

  let headerOwed = false;

  function headerFor(entry: Entry): void {
    if (entry.role === "user" || !headerOwed) return;
    headerOwed = false;
    const id = entry.agent_id || "main";
    transcript.append(
      renderAgentHeader({
        agent_id: id,
        emoji: agentEmoji.get(id),
        model: entry.model ?? undefined,
      }),
    );
  }

  /** Returns how many entries it consumed: a question is its call plus its result. */
  function renderQuestionEntries(entries: Entry[], index: number): number {
    const call = entries[index];
    const result = entries[index + 1];
    if (
      !result ||
      result.role !== "tool_result" ||
      result.tool_name !== ASK_USER
    ) {
      return 1; // Still pending: the live card comes from /questions.
    }
    headerFor(call);
    const card = renderAnsweredQuestion(call.content, result.content);
    if (card) transcript.append(card);
    return 2;
  }

  function renderEntry(entry: Entry): void {
    if (entry.role === "notice") {
      // Same order as live: the turn's header first, then its notice.
      headerFor(entry);
      transcript.append(renderNotice(entry.content));
      return;
    }
    headerFor(entry);
    if (entry.role === "user") {
      headerOwed = true;
      transcript.append(renderUserTurn(entry.content));
      return;
    }
    if (entry.role === "assistant") {
      transcript.append(renderAssistantTurn(entry.content));
      return;
    }
    const name = entry.tool_name ?? "tool";
    if (entry.role === "tool_call") {
      appendToolActivity(transcript, {
        event: "tool_call",
        name,
        arguments: entry.content,
      });
      return;
    }
    appendToolActivity(transcript, {
      event: "tool_result",
      name,
      content: entry.content,
    });
  }

  function renderTranscript(entries: Entry[]): void {
    // A message sent before the first load landed stays on screen, after the history.
    const live = liveTurn ? [...transcript.childNodes] : [];
    if (liveTurn) {
      const start = entries
        .map((e) => e.role === "user" && e.content === liveTurn)
        .lastIndexOf(true);
      if (start >= 0) entries = entries.slice(0, start);
    } else {
      dropDraft();
    }
    transcript.replaceChildren();
    headerOwed = false;
    if (entries.length === 0 && live.length === 0) {
      showEmpty();
      return;
    }
    for (let index = 0; index < entries.length;) {
      const entry = entries[index];
      if (entry.tool_name === REPORT_PROGRESS) {
        // The last state wins; the card keeps the spot of the first report.
        const state =
          entry.role === "tool_call" ? parseProgress(entry.content) : null;
        if (state) {
          headerFor(entry);
          upsertProgressCard(transcript, state);
        }
        index += 1;
        continue;
      }
      if (entry.role === "tool_call" && entry.tool_name === ASK_USER) {
        index += renderQuestionEntries(entries, index);
        continue;
      }
      renderEntry(entry);
      index += 1;
    }
    transcript.append(...live);
    scrollToBottom(true);
  }

  function showThinking(): HTMLElement {
    transcript.querySelector(".empty")?.remove();
    if (draft) return draft;
    draft = el("article", "assistant draft thinking");
    draft.dataset.draft = "true";
    draft.setAttribute("aria-busy", "true");

    const label = el("span", "thinking-indicator", "Thinking");
    const dots = el("span", "thinking-dots");
    dots.append(el("span"), el("span"), el("span"));
    label.append(dots);
    draft.append(label);

    transcript.append(draft);
    scrollToBottom();
    draftText = "";
    return draft;
  }

  function ensureDraft(): HTMLElement {
    transcript.querySelector(".empty")?.remove();
    if (draft) {
      if (draft.classList.contains("thinking")) {
        draft.classList.remove("thinking");
        draft.removeAttribute("aria-busy");
        draft.replaceChildren();
      }
      return draft;
    }
    draft = el("article", "assistant draft");
    draft.dataset.draft = "true";
    transcript.append(draft);
    draftText = "";
    return draft;
  }

  function dropDraft(): void {
    draft?.remove();
    draft = null;
    draftText = "";
  }

  function commitReply(reply: string): void {
    const text = reply || draftText;
    dropDraft();
    transcript.append(renderAssistantTurn(text));
  }

  function grow(): void {
    input.style.height = "auto";
    input.style.height = `${input.scrollHeight}px`;
  }

  function setBusy(busy: boolean): void {
    running = busy;
    input.disabled = busy || blocked !== null;
    sendButton.disabled = busy || blocked !== null;
    modelPicker.disabled = busy;
    abortButton.hidden = !busy;
  }

  function setStatus(text: string): void {
    statusLine.textContent = text;
  }

  /** A pending question or approval holds the session: no new message until it is resolved. */
  function setBlocked(reason: string | null): void {
    blocked = reason;
    input.disabled = running || reason !== null;
    sendButton.disabled = running || reason !== null;
    form.dataset.blocked = reason === null ? "" : "true";
    setStatus(reason ?? "");
  }

  async function loadModels(): Promise<void> {
    const response = await fetch("/api/models");
    if (!response.ok) return;
    const body = (await response.json()) as { models?: ModelOption[] };
    if (!body || !Array.isArray(body.models)) return;
    const saved = sessionStorage.getItem(MODEL_KEY);
    modelPicker.replaceChildren();
    for (const option of body.models) {
      const node = document.createElement("option");
      node.value = option.id;
      node.textContent = option.label;
      modelPicker.append(node);
    }
    const wanted =
      saved && body.models.some((option) => option.id === saved)
        ? saved
        : body.models.find((option) => option.default)?.id;
    if (wanted) modelPicker.value = wanted;
    renderModelOptions(body.models);
  }

  async function loadAgents(): Promise<void> {
    try {
      const response = await fetch("/api/agents");
      if (!response.ok) return;
      const agents = (await response.json()) as AgentOption[];
      if (!Array.isArray(agents)) return;
      agentOptions = agents;
      for (const agent of agents) {
        if (agent.signature_emoji)
          agentEmoji.set(agent.name, agent.signature_emoji);
      }
      renderAgentOptions();
      updatePlaceholder();
    } catch {
      // Headers fall back to the bare handle.
    }
  }

  async function loadTranscript(): Promise<void> {
    const response = await fetch(`/api/sessions/${sessionId()}/transcript`);
    if (!response.ok) {
      setStatus("The transcript could not be loaded.");
      return;
    }
    const body = (await response.json()) as TranscriptBody;
    renderTranscript(body.entries ?? []);
    if (liveTurn) return;
    if (body.run_state === "running") {
      followRunningTurn();
      return;
    }
    await loadPendingQuestions();
    await loadPendingApprovals();
  }

  /** After a reload mid-turn: keep the composer closed and poll until the turn settles. */
  function followRunningTurn(): void {
    if (polling) return;
    polling = true;
    setBusy(true);
    showThinking();
    setStatus(STILL_RUNNING);
    const tick = async (): Promise<void> => {
      if (!polling) return;
      try {
        const response = await fetch(`/api/sessions/${sessionId()}/transcript`);
        if (response.ok) {
          const body = (await response.json()) as TranscriptBody;
          if (body.run_state !== "running") {
            polling = false;
            renderTranscript(body.entries ?? []);
            setBusy(false);
            setStatus("");
            await loadPendingQuestions();
            await loadPendingApprovals();
            return;
          }
          renderTranscript(body.entries ?? []);
          showThinking();
        }
      } catch {
        // Try again on the next tick.
      }
      setTimeout(() => void tick(), POLL_MS);
    };
    setTimeout(() => void tick(), POLL_MS);
  }

  async function loadPendingApprovals(): Promise<void> {
    try {
      const response = await fetch("/api/approvals");
      if (!response.ok) return;
      const body = (await response.json()) as {
        pending?: { session_id: string }[];
      };
      const mine = (body.pending ?? []).filter(
        (a) => a.session_id === sessionId(),
      );
      if (mine.length > 0 && blocked === null) setBlocked(WAITING_FOR_APPROVAL);
    } catch {
      // The approvals screen still lists it.
    }
  }

  async function loadPendingQuestions(): Promise<void> {
    try {
      const response = await fetch(`/api/sessions/${sessionId()}/questions`);
      if (!response.ok) return;
      const pending = (await response.json()) as QuestionCard[];
      if (!Array.isArray(pending) || pending.length === 0) return;
      transcript.querySelector(".empty")?.remove();
      for (const question of pending) showQuestion(question);
      setBlocked(WAITING_FOR_ANSWER);
    } catch {
      // The transcript is still usable without the live card.
    }
  }

  function showQuestion(question: QuestionCard): void {
    if (draft?.classList.contains("thinking")) dropDraft();
    transcript.append(renderQuestionCard(question, onAnswered));
    scrollToBottom();
  }

  function onAnswered(result: AnswerResult): void {
    if (result.reply) transcript.append(renderAssistantTurn(result.reply));
    for (const question of result.pending) showQuestion(question);
    setBlocked(result.pending.length > 0 ? WAITING_FOR_ANSWER : null);
    scrollToBottom();
  }

  function parseFrame(raw: string): SseFrame | null {
    let event = "message";
    const data: string[] = [];
    for (const line of raw.split("\n")) {
      if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:")) data.push(line.slice(5).trim());
    }
    if (data.length === 0) return null;
    return { event, data: data.join("\n") };
  }

  function onFrame(frame: SseFrame): void {
    const payload = JSON.parse(frame.data) as {
      text?: string;
      name?: string;
      arguments?: string;
      content?: string;
      reply?: string;
      error?: string;
      status?: string;
      approval_id?: string;
      input_tokens?: number;
      output_tokens?: number;
      context_window?: number | null;
      agent_id?: string;
      emoji?: string;
      model?: string;
      question_id?: string;
      question?: string;
      options?: string[];
      default?: string | null;
      multi?: boolean;
      task_id?: string;
      steps?: ProgressStep[];
    };
    if (frame.event === "progress" && payload.task_id) {
      upsertProgressCard(
        transcript,
        { task_id: payload.task_id, steps: payload.steps ?? [] },
        draft,
      );
      return;
    }
    if (frame.event === "question" && payload.question_id) {
      showQuestion({
        id: payload.question_id,
        question: payload.question ?? "",
        options: payload.options ?? [],
        default: payload.default ?? null,
        multi: payload.multi ?? false,
      });
      questionAsked = true;
      setBlocked(WAITING_FOR_ANSWER);
      return;
    }
    // Questions render as cards, not tool rows.
    if (
      (frame.event === "tool_call" || frame.event === "tool_result") &&
      (payload.name === ASK_USER || payload.name === REPORT_PROGRESS)
    ) {
      return;
    }
    if (frame.event === "notice" && payload.text) {
      const note = renderNotice(payload.text);
      if (draft) transcript.insertBefore(note, draft);
      else transcript.append(note);
      return;
    }
    if (frame.event === "agent" && payload.agent_id) {
      const header = renderAgentHeader({
        agent_id: payload.agent_id,
        name: payload.name,
        emoji: payload.emoji,
        model: payload.model,
      });
      if (draft) transcript.insertBefore(header, draft);
      else transcript.append(header);
      return;
    }
    if (frame.event === "token" && payload.text) {
      draftText += payload.text;
      ensureDraft().textContent = draftText;
      scrollToBottom();
      return;
    }
    if (frame.event === "tool_call") {
      if (draft?.classList.contains("thinking")) {
        dropDraft();
      }
      appendToolActivity(transcript, {
        event: "tool_call",
        name: payload.name ?? "tool",
        arguments: payload.arguments ?? "",
      });
      scrollToBottom();
      return;
    }
    if (frame.event === "approval_required") {
      if (draft?.classList.contains("thinking")) {
        dropDraft();
      }
      renderInlineApproval(
        transcript,
        payload.approval_id ?? "",
        payload.name ?? "tool",
        (reply) => {
          if (reply) {
            transcript.append(renderAssistantTurn(reply));
            scrollToBottom();
          }
          setBlocked(null);
        },
        payload.arguments,
      );
      scrollToBottom();
      return;
    }
    if (frame.event === "tool_result") {
      appendToolActivity(transcript, {
        event: "tool_result",
        name: payload.name ?? "tool",
        content: payload.content ?? "",
      });
      if (!draft) showThinking();
      scrollToBottom();
      return;
    }
    if (frame.event === "usage") {
      contextTokens = payload.input_tokens ?? 0;
      if (payload.output_tokens !== undefined) {
        outputTokens = payload.output_tokens;
      }
      contextWindow = payload.context_window ?? null;
      renderMeter();
      return;
    }
    if (frame.event === "done") {
      commitReply(payload.reply ?? "");
      if (payload.status === "pending_approval" && questionAsked) {
        setBlocked(WAITING_FOR_ANSWER);
      } else if (payload.status === "pending_approval") {
        setBlocked(WAITING_FOR_APPROVAL);
      } else {
        setStatus("");
      }
      return;
    }
    if (frame.event === "error") {
      const failure =
        payload.error ?? "The turn failed before a reply was completed.";
      markRunningToolsError(transcript, failure);
      dropDraft();
      setStatus(failure);
    }
  }

  async function readSse(response: Response): Promise<boolean> {
    const reader = response.body?.getReader();
    if (!reader) return false;
    const decoder = new TextDecoder();
    let buffer = "";
    let finished = false;
    for (;;) {
      const chunk = await reader.read();
      if (chunk.done) break;
      buffer += decoder.decode(chunk.value, { stream: true });
      const frames = buffer.split("\n\n");
      buffer = frames.pop() ?? "";
      for (const raw of frames) {
        const frame = parseFrame(raw);
        if (!frame) continue;
        onFrame(frame);
        if (frame.event === "done" || frame.event === "error") finished = true;
      }
    }
    return finished;
  }

  async function sendMessage(text: string): Promise<void> {
    if (blocked !== null) {
      setStatus(blocked);
      return;
    }
    questionAsked = false;
    liveTurn = text;
    setBusy(true);
    setStatus("");
    controller = new AbortController();
    const signal = controller.signal;
    let finished = false;

    // Immediately render user message and thinking indicator for responsive chat feel
    transcript.querySelector(".empty")?.remove();
    const bubble = renderUserTurn(text);
    transcript.append(bubble);
    showThinking();
    scrollToBottom(true);

    try {
      const agent = ctx.url.searchParams.get("agent") || null;
      const response = await fetch(`/api/sessions/${sessionId()}/turns`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          message: text,
          model: modelPicker.value || null,
          agent,
        }),
        signal,
      });
      if (response.status === 409) {
        // Nothing was saved: take the message back so it is not lost.
        bubble.remove();
        if (!input.value) input.value = text;
        dropDraft();
        const body = (await response.json()) as { error?: string };
        setStatus(body.error ?? "A turn is already running for this session.");
        finished = true; // Reported above; not a broken stream.
        return;
      }
      if (!response.ok) {
        dropDraft();
        setStatus("The turn could not be started.");
        finished = true; // Reported above; not a broken stream.
        return;
      }
      finished = await readSse(response);
    } catch {
      dropDraft();
      if (!signal.aborted) setStatus("The turn could not be started.");
    } finally {
      if (!finished && !signal.aborted) {
        dropDraft();
        setStatus("The turn failed before a reply was completed.");
      }
      controller = null;
      liveTurn = null;
      setBusy(false);
      if (!sessionTitle) void loadTitle();
      if (blocked !== null) setStatus(blocked);
      else input.focus();
    }
  }

  // Autocomplete popover state
  let popover: HTMLUListElement | null = null;
  let suggestions: Suggestion[] = [];
  let localSuggestions: Suggestion[] = [];
  let selectedIndex = -1;
  let debounceTimer: ReturnType<typeof setTimeout> | null = null;
  let suggestionsAbort: AbortController | null = null;
  let activeTrigger: {
    type: "@" | "/";
    query: string;
    start: number;
    end: number;
  } | null = null;

  function closePopover(): void {
    if (debounceTimer) clearTimeout(debounceTimer);
    if (suggestionsAbort) suggestionsAbort.abort();
    debounceTimer = null;
    suggestionsAbort = null;
    if (popover) {
      popover.remove();
      popover = null;
    }
    suggestions = [];
    selectedIndex = -1;
    activeTrigger = null;
  }

  function renderPopover(): void {
    if (!popover) {
      popover = el("ul", "composer-popover");
      popover.setAttribute("role", "listbox");
      form.append(popover);
    }
    popover.replaceChildren();
    if (suggestions.length === 0) {
      closePopover();
      return;
    }
    suggestions.forEach((item, idx) => {
      const li = el(
        "li",
        `composer-popover-item${idx === selectedIndex ? " active" : ""}`,
      );
      li.setAttribute("role", "option");
      li.setAttribute(
        "aria-selected",
        idx === selectedIndex ? "true" : "false",
      );

      const label = el("span", "popover-item-label", item.label);
      const detail = el("span", "popover-item-detail", item.detail);
      const kind = el("span", "popover-item-kind", item.kind);
      li.append(label, detail, kind);

      li.addEventListener("mousedown", (e) => {
        e.preventDefault();
        applySuggestion(item);
      });
      popover?.append(li);
    });
  }

  function applySuggestion(item: { insert_text: string }): void {
    if (!activeTrigger) return;
    const value = input.value;
    const before = value.slice(0, activeTrigger.start);
    const after = value.slice(activeTrigger.end);
    input.value = before + item.insert_text + " " + after;
    const newCursor = activeTrigger.start + item.insert_text.length + 1;
    input.setSelectionRange(newCursor, newCursor);
    closePopover();
    input.focus();
    grow();
  }

  let requestSeq = 0;

  async function fetchSuggestions(
    seq: number,
    type: "@" | "/",
    query: string,
    start: number,
    end: number,
  ): Promise<void> {
    if (suggestionsAbort) suggestionsAbort.abort();
    suggestionsAbort = new AbortController();
    try {
      const res = await fetch(
        `/api/composer/suggestions?type=${encodeURIComponent(type)}&query=${encodeURIComponent(query)}`,
        { signal: suggestionsAbort.signal },
      );
      if (!res.ok) return;
      // Guard against stale response using request sequence and active trigger bounds
      if (
        seq !== requestSeq ||
        !activeTrigger ||
        activeTrigger.type !== type ||
        activeTrigger.query !== query ||
        activeTrigger.start !== start ||
        activeTrigger.end !== end
      ) {
        return;
      }
      const data = (await res.json()) as { suggestions?: Suggestion[] };
      // Re-check sequence and trigger after asynchronous JSON parsing
      if (
        seq !== requestSeq ||
        !activeTrigger ||
        activeTrigger.type !== type ||
        activeTrigger.query !== query ||
        activeTrigger.start !== start ||
        activeTrigger.end !== end
      ) {
        return;
      }
      const remote = data.suggestions ?? [];
      suggestions =
        type === "@" || type === "/"
          ? mergeSuggestions(localSuggestions, remote)
          : remote;
      if (selectedIndex < 0 || selectedIndex >= suggestions.length) {
        selectedIndex = suggestions.length > 0 ? 0 : -1;
      }
      renderPopover();
    } catch {
      // aborted or network error
    }
  }

  function inspectTrigger(): void {
    const cursor = input.selectionStart;
    const textBefore = input.value.slice(0, cursor);
    const match = /(?:^|\s)([@\/])([^\s]*)$/.exec(textBefore);

    if (!match) {
      closePopover();
      return;
    }

    const type = match[1] as "@" | "/";
    const query = match[2];
    const triggerStart = cursor - query.length - 1;
    activeTrigger = { type, query, start: triggerStart, end: cursor };

    // Immediately cancel in-flight request, clear previous suggestions and popover
    requestSeq += 1;
    const currentSeq = requestSeq;
    if (suggestionsAbort) {
      suggestionsAbort.abort();
      suggestionsAbort = null;
    }
    suggestions = [];
    selectedIndex = -1;
    if (popover) {
      popover.remove();
      popover = null;
    }
    // Agents and default slash commands are local: show at once, server fills in extra items.
    localSuggestions =
      type === "@"
        ? agentSuggestions(agentOptions, query)
        : type === "/"
          ? slashSuggestions(query)
          : [];
    if (localSuggestions.length > 0) {
      suggestions = [...localSuggestions];
      selectedIndex = 0;
      renderPopover();
    }

    if (debounceTimer) clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
      void fetchSuggestions(currentSeq, type, query, triggerStart, cursor);
    }, 250);
  }

  abortButton.addEventListener("click", () => {
    // The turn runs on the server past this request: ask it to stop, then let go.
    void fetch(`/api/sessions/${sessionId()}/cancel`, { method: "POST" }).catch(
      () => {},
    );
    controller?.abort();
    controller = null;
    polling = false;
    setBusy(false);
  });

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    closePopover();
    closeAllCustomPopovers();
    const text = input.value.trim();
    if (!text) return;
    input.value = "";
    clearDraft();
    updateDraftStatus();
    grow();
    void sendMessage(text);
  });

  input.addEventListener("input", () => {
    grow();
    inspectTrigger();
    saveDraft();
    updateDraftStatus();
  });

  input.addEventListener("keydown", (event) => {
    if (popover && suggestions.length > 0) {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        selectedIndex = (selectedIndex + 1) % suggestions.length;
        renderPopover();
        return;
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        selectedIndex =
          (selectedIndex - 1 + suggestions.length) % suggestions.length;
        renderPopover();
        return;
      }
      if (event.key === "Enter" || event.key === "Tab") {
        if (selectedIndex >= 0 && selectedIndex < suggestions.length) {
          event.preventDefault();
          applySuggestion(suggestions[selectedIndex]);
          return;
        }
      }
      if (event.key === "Escape") {
        event.preventDefault();
        closePopover();
        return;
      }
    }

    if (event.key === "Escape") {
      closeAllCustomPopovers();
    }

    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      form.requestSubmit();
    }
  });

  document.addEventListener("click", (event) => {
    if (popover && !form.contains(event.target as Node)) {
      closePopover();
    }
    const target = event.target as Node;
    if (!modelSelectorWrapper.contains(target)) {
      modelCustomPopover.hidden = true;
      modelCustomTrigger.setAttribute("aria-expanded", "false");
    }
    if (
      !meter.contains(target) &&
      !studioCtxStrip.contains(target)
    ) {
      ctxPopover.hidden = true;
    }
  });

  modelPicker.addEventListener("change", () => {
    sessionStorage.setItem(MODEL_KEY, modelPicker.value);
    const selectedOption = modelPicker.options[modelPicker.selectedIndex];
    if (selectedOption) {
      const fmt = formatModelOption(modelPicker.value, selectedOption.textContent || "");
      modelTriggerIcon.textContent = fmt.icon;
      modelTriggerName.textContent = fmt.name;
    }
    // The new model's window is unknown until its first turn reports usage.
    contextWindow = null;
    renderMeter();
  });

  async function checkHatchDraft(): Promise<void> {
    try {
      const [hatchRes, sessionsRes] = await Promise.all([
        fetch("/api/hatch"),
        fetch("/api/sessions"),
      ]);
      if (!hatchRes.ok || !sessionsRes.ok) return;
      const hatchData = (await hatchRes.json()) as { hatched?: boolean };
      const sessionsData = (await sessionsRes.json()) as {
        sessions?: unknown[];
      };
      const hasSessions = (sessionsData.sessions?.length ?? 0) > 0;
      if (!hatchData.hatched && !hasSessions && !input.value) {
        input.value = "Wake up, my friend!";
        grow();
      }
    } catch {
      // ignore network errors
    }
  }

  void loadModels();
  void loadTitle();
  void loadAgents().then(loadTranscript);
  void checkHatchDraft();
}
