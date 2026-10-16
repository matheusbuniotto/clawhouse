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
import { el, svgEl } from "./dom.js";
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
const WAITING_FOR_ANSWER = "Esperando sua resposta na pergunta acima.";

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
  const transcript = el("section", "log");
  transcript.id = "log";
  transcript.setAttribute("aria-live", "polite");

  const form = document.createElement("form");
  form.id = "composer";
  form.className = "composer";

  const input = document.createElement("textarea");
  input.id = "message";
  input.rows = 1;
  input.placeholder = "Message the agent";
  input.required = true;

  const toolbar = el("div", "composer-toolbar");
  const modelLabel = el("label", "sr", "Model");
  modelLabel.htmlFor = "model";
  const modelPicker = document.createElement("select");
  modelPicker.id = "model";
  modelPicker.className = "model-pill";

  // Context-window meter: a ring showing the input tokens sent to the model.
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
  meter.append(ring, meterLabel);

  const abortButton = el("button", "abort", "Stop");
  abortButton.id = "abort";
  abortButton.type = "button";
  abortButton.hidden = true;
  const sendButton = el("button", "send", "Send");
  sendButton.type = "submit";
  toolbar.append(modelLabel, modelPicker, meter, abortButton, sendButton);

  const statusLine = el("p", "status");
  statusLine.id = "status";
  statusLine.setAttribute("role", "status");

  form.append(input, toolbar, statusLine);
  root.append(transcript, form);

  let draft: HTMLElement | null = null;
  let blocked: string | null = null;
  let running = false;
  let liveTurn: string | null = null;
  let polling = false;
  let questionAsked = false;
  let draftText = "";
  let controller: AbortController | null = null;

  let contextTokens = 0;
  let contextWindow: number | null = null;

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

  function renderMeter(): void {
    // The ring fills against the model's context window; 300k is a sane gauge
    // when the window is unknown. Colour is absolute, per the product call.
    const denominator = contextWindow ?? 300_000;
    const ratio =
      denominator > 0 ? Math.min(1, contextTokens / denominator) : 0;
    meter.dataset.level = usageLevel(contextTokens);
    ringFill.setAttribute(
      "stroke-dashoffset",
      String(ringCircumference * (1 - ratio)),
    );
    meterLabel.textContent = formatTokens(contextTokens);
    const detail = contextWindow
      ? `${contextTokens.toLocaleString()} / ${contextWindow.toLocaleString()} input tokens`
      : `${contextTokens.toLocaleString()} input tokens; context window unknown`;
    meter.title = detail;
    meter.setAttribute("aria-label", `Context: ${detail}`);
  }

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

  function showEmpty(): void {
    transcript.replaceChildren(el("p", "empty", "This session is empty."));
  }

  // Emoji per handle, for headers rebuilt from a reloaded transcript.
  const agentEmoji = new Map<string, string>();
  let agentOptions: AgentOption[] = [];
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
    const text = input.value.trim();
    if (!text) return;
    input.value = "";
    clearDraft();
    grow();
    void sendMessage(text);
  });

  input.addEventListener("input", () => {
    grow();
    inspectTrigger();
    saveDraft();
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

    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      form.requestSubmit();
    }
  });

  document.addEventListener("click", (event) => {
    if (popover && !form.contains(event.target as Node)) {
      closePopover();
    }
  });

  modelPicker.addEventListener("change", () => {
    sessionStorage.setItem(MODEL_KEY, modelPicker.value);
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
  void loadAgents().then(loadTranscript);
  void checkHatchDraft();
}
