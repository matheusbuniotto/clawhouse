import { el } from "./dom.js";
import type { ScreenContext } from "./shell.js";
import {
  appendToolActivity,
  markRunningToolsError,
  renderAssistantTurn,
  renderUserTurn,
} from "./transcript.js";

const SESSION_KEY = "crabriks.session";
const MODEL_KEY = "crabriks.model";

interface Entry {
  role: "user" | "assistant" | "tool_call" | "tool_result";
  content: string;
  tool_name: string | null;
}

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
  const abortButton = el("button", "abort", "Stop");
  abortButton.id = "abort";
  abortButton.type = "button";
  abortButton.hidden = true;
  const sendButton = el("button", "send", "Send");
  sendButton.type = "submit";
  toolbar.append(modelLabel, modelPicker, abortButton, sendButton);

  const statusLine = el("p", "status");
  statusLine.id = "status";
  statusLine.setAttribute("role", "status");

  form.append(input, toolbar, statusLine);
  root.append(transcript, form);

  let draft: HTMLElement | null = null;
  let draftText = "";
  let controller: AbortController | null = null;

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

  function showEmpty(): void {
    transcript.replaceChildren(el("p", "empty", "This session is empty."));
  }

  function renderEntry(entry: Entry): void {
    if (entry.role === "user") {
      transcript.append(renderUserTurn(entry.content));
      return;
    }
    if (entry.role === "assistant") {
      transcript.append(renderAssistantTurn(entry.content));
      return;
    }
    const name = entry.tool_name ?? "tool";
    if (entry.role === "tool_call") {
      appendToolActivity(transcript, { event: "tool_call", name, arguments: entry.content });
      return;
    }
    appendToolActivity(transcript, { event: "tool_result", name, content: entry.content });
  }

  function renderTranscript(entries: Entry[]): void {
    dropDraft();
    transcript.replaceChildren();
    if (entries.length === 0) {
      showEmpty();
      return;
    }
    for (const entry of entries) renderEntry(entry);
    transcript.scrollTop = transcript.scrollHeight;
  }

  function ensureDraft(): HTMLElement {
    transcript.querySelector(".empty")?.remove();
    if (draft) return draft;
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
    input.disabled = busy;
    sendButton.disabled = busy;
    modelPicker.disabled = busy;
    abortButton.hidden = !busy;
  }

  function setStatus(text: string): void {
    statusLine.textContent = text;
  }

  async function loadModels(): Promise<void> {
    const response = await fetch("/api/models");
    if (!response.ok) return;
    const body = (await response.json()) as { models: ModelOption[] };
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

  async function loadTranscript(): Promise<void> {
    const response = await fetch(`/api/sessions/${sessionId()}/transcript`);
    if (!response.ok) {
      setStatus("The transcript could not be loaded.");
      return;
    }
    const body = (await response.json()) as { entries?: Entry[] };
    renderTranscript(body.entries ?? []);
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
    };
    if (frame.event === "token" && payload.text) {
      draftText += payload.text;
      ensureDraft().textContent = draftText;
      return;
    }
    if (frame.event === "tool_call") {
      appendToolActivity(transcript, {
        event: "tool_call",
        name: payload.name ?? "tool",
        arguments: payload.arguments ?? "",
      });
      return;
    }
    if (frame.event === "tool_result") {
      appendToolActivity(transcript, {
        event: "tool_result",
        name: payload.name ?? "tool",
        content: payload.content ?? "",
      });
      return;
    }
    if (frame.event === "done") {
      commitReply(payload.reply ?? "");
      setStatus("");
      return;
    }
    if (frame.event === "error") {
      const failure = payload.error ?? "The turn failed before a reply was completed.";
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
    setBusy(true);
    setStatus("");
    controller = new AbortController();
    const signal = controller.signal;
    let finished = false;
    try {
      const response = await fetch(`/api/sessions/${sessionId()}/turns`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ message: text, model: modelPicker.value || null }),
        signal,
      });
      if (response.status === 409) {
        const body = (await response.json()) as { error?: string };
        setStatus(body.error ?? "A turn is already running for this session.");
        return;
      }
      if (!response.ok) {
        setStatus("The turn could not be started.");
        return;
      }
      transcript.querySelector(".empty")?.remove();
      transcript.append(renderUserTurn(text));
      finished = await readSse(response);
    } catch {
      if (!signal.aborted) setStatus("The turn could not be started.");
    } finally {
      if (!finished && !signal.aborted) {
        dropDraft();
        setStatus("The turn failed before a reply was completed.");
      }
      controller = null;
      setBusy(false);
      input.focus();
    }
  }

  // Autocomplete popover state
  let popover: HTMLUListElement | null = null;
  let suggestions: { label: string; insert_text: string; detail: string; kind: string }[] = [];
  let selectedIndex = -1;
  let debounceTimer: ReturnType<typeof setTimeout> | null = null;
  let suggestionsAbort: AbortController | null = null;
  let activeTrigger: { type: "@" | "/"; query: string; start: number; end: number } | null = null;

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
      const li = el("li", `composer-popover-item${idx === selectedIndex ? " active" : ""}`);
      li.setAttribute("role", "option");
      li.setAttribute("aria-selected", idx === selectedIndex ? "true" : "false");

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
      const data = (await res.json()) as {
        suggestions: { label: string; insert_text: string; detail: string; kind: string }[];
      };
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
      suggestions = data.suggestions ?? [];
      selectedIndex = suggestions.length > 0 ? 0 : -1;
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

    if (debounceTimer) clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
      void fetchSuggestions(currentSeq, type, query, triggerStart, cursor);
    }, 250);
  }

  abortButton.addEventListener("click", () => {
    controller?.abort();
    controller = null;
    setBusy(false);
  });

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    closePopover();
    const text = input.value.trim();
    if (!text) return;
    input.value = "";
    grow();
    void sendMessage(text);
  });

  input.addEventListener("input", () => {
    grow();
    inspectTrigger();
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
        selectedIndex = (selectedIndex - 1 + suggestions.length) % suggestions.length;
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

  modelPicker.addEventListener("change", () => {
    sessionStorage.setItem(MODEL_KEY, modelPicker.value);
  });

  async function checkHatchDraft(): Promise<void> {
    try {
      const [hatchRes, sessionsRes] = await Promise.all([
        fetch("/api/hatch"),
        fetch("/api/sessions"),
      ]);
      if (!hatchRes.ok || !sessionsRes.ok) return;
      const hatchData = (await hatchRes.json()) as { hatched?: boolean };
      const sessionsData = (await sessionsRes.json()) as { sessions?: unknown[] };
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
  void loadTranscript();
  void checkHatchDraft();
}
