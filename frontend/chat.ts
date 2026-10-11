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

const log = document.querySelector<HTMLElement>("#log");
const who = document.querySelector<HTMLElement>("#who");
const form = document.querySelector<HTMLFormElement>("#composer");
const message = document.querySelector<HTMLTextAreaElement>("#message");
const statusNode = document.querySelector<HTMLElement>("#status");
const modelSelect = document.querySelector<HTMLSelectElement>("#model");
const send = form?.querySelector<HTMLButtonElement>("button");

if (!log || !who || !form || !message || !statusNode || !modelSelect || !send) {
  throw new Error("chat page is missing a required element");
}

const transcript = log;
const identity = who;
const composer = form;
const input = message;
const statusLine = statusNode;
const modelPicker = modelSelect;
const sendButton = send;

let draft: HTMLElement | null = null;
let draftText = "";

function sessionId(): string {
  const fromUrl = new URLSearchParams(location.search).get("session");
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

function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  className: string,
  text?: string,
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
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
  draft = document.createElement("article");
  draft.className = "assistant draft";
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

function setBusy(busy: boolean): void {
  input.disabled = busy;
  sendButton.disabled = busy;
  modelPicker.disabled = busy;
}

function setStatus(text: string): void {
  statusLine.textContent = text;
}

async function loadIdentity(): Promise<void> {
  const response = await fetch("/api/me");
  if (!response.ok) {
    identity.textContent = "Not signed in";
    return;
  }
  const body = (await response.json()) as { user_id: string };
  identity.textContent = body.user_id;
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
  const body = (await response.json()) as { entries: Entry[] };
  renderTranscript(body.entries);
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
  const response = await fetch(`/api/sessions/${sessionId()}/turns`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ message: text, model: modelPicker.value || null }),
  });
  if (response.status === 409) {
    const body = (await response.json()) as { error?: string };
    setStatus(body.error ?? "A turn is already running for this session.");
    setBusy(false);
    return;
  }
  if (!response.ok) {
    setStatus("The turn could not be started.");
    setBusy(false);
    return;
  }
  transcript.querySelector(".empty")?.remove();
  transcript.append(renderUserTurn(text));
  let finished = false;
  try {
    finished = await readSse(response);
  } finally {
    if (!finished) {
      dropDraft();
      setStatus("The turn failed before a reply was completed.");
    }
    setBusy(false);
    input.focus();
  }
}

composer.addEventListener("submit", (event) => {
  event.preventDefault();
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  void sendMessage(text);
});

input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    composer.requestSubmit();
  }
});

modelPicker.addEventListener("change", () => {
  sessionStorage.setItem(MODEL_KEY, modelPicker.value);
});

void loadIdentity();
void loadModels();
void loadTranscript();
