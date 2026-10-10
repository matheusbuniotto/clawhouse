const SESSION_KEY = "crabriks.session";

interface Entry {
  role: "user" | "assistant" | "tool_call" | "tool_result";
  content: string;
  tool_name: string | null;
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
const send = form?.querySelector<HTMLButtonElement>("button");

if (!log || !who || !form || !message || !statusNode || !send) {
  throw new Error("chat page is missing a required element");
}

const transcript = log;
const identity = who;
const composer = form;
const input = message;
const statusLine = statusNode;
const sendButton = send;

let draft: HTMLParagraphElement | null = null;

function sessionId(): string {
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
    transcript.append(el("p", "bubble user", entry.content));
    return;
  }
  if (entry.role === "assistant") {
    transcript.append(el("p", "bubble assistant", entry.content));
    return;
  }
  const label = entry.role === "tool_call" ? "call" : "result";
  const name = entry.tool_name ?? "tool";
  transcript.append(el("p", "tool", `${name} ${label} ${entry.content}`));
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

function ensureDraft(): HTMLParagraphElement {
  const empty = transcript.querySelector(".empty");
  empty?.remove();
  if (draft) return draft;
  draft = el("p", "bubble assistant draft");
  draft.dataset.draft = "true";
  transcript.append(draft);
  return draft;
}

function dropDraft(): void {
  draft?.remove();
  draft = null;
}

function commitReply(reply: string): void {
  const node = ensureDraft();
  node.textContent = reply;
  node.classList.remove("draft");
  delete node.dataset.draft;
  draft = null;
}

function setBusy(busy: boolean): void {
  input.disabled = busy;
  sendButton.disabled = busy;
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
    ensureDraft().textContent = `${ensureDraft().textContent ?? ""}${payload.text}`;
    return;
  }
  if (frame.event === "tool_call") {
    transcript.append(el("p", "tool", `${payload.name ?? "tool"} call ${payload.arguments ?? ""}`));
    return;
  }
  if (frame.event === "tool_result") {
    transcript.append(el("p", "tool", `${payload.name ?? "tool"} result ${payload.content ?? ""}`));
    return;
  }
  if (frame.event === "done") {
    commitReply(payload.reply ?? "");
    setStatus("");
    return;
  }
  if (frame.event === "error") {
    dropDraft();
    setStatus(payload.error ?? "The turn failed before a reply was completed.");
  }
}

async function readSse(response: Response): Promise<void> {
  const reader = response.body?.getReader();
  if (!reader) return;
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const chunk = await reader.read();
    if (chunk.done) break;
    buffer += decoder.decode(chunk.value, { stream: true });
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";
    for (const raw of frames) {
      const frame = parseFrame(raw);
      if (frame) onFrame(frame);
    }
  }
}

async function sendMessage(text: string): Promise<void> {
  setBusy(true);
  setStatus("");
  const response = await fetch(`/api/sessions/${sessionId()}/turns`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ message: text }),
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
  transcript.append(el("p", "bubble user", text));
  try {
    await readSse(response);
  } finally {
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

void loadIdentity();
void loadTranscript();
