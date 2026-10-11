/** Pure, side-effect-free transcript rendering: markdown and tool-activity rows. */

export function renderUserTurn(text: string): HTMLParagraphElement {
  const node = document.createElement("p");
  node.className = "bubble user";
  node.textContent = text;
  return node;
}

export function renderAssistantTurn(source: string): HTMLElement {
  const node = document.createElement("article");
  node.className = "assistant";
  node.append(renderMarkdown(source));
  return node;
}

export type ToolState = "running" | "ok" | "error";

export interface ToolFrame {
  event: "tool_call" | "tool_result";
  name?: string;
  arguments?: string;
  content?: string;
}

const STATUS_LABEL: Record<ToolState, string> = {
  running: "Running",
  ok: "OK",
  error: "Error",
};

/**
 * One activity row per call: a `tool_call` opens it running, a following
 * `tool_result` completes the same row. Rows are `<details>` so input and
 * output stay collapsed until the reader expands them.
 */
export function appendToolActivity(container: HTMLElement, frame: ToolFrame): HTMLElement {
  const running = lastRunningTool(container);
  if (frame.event === "tool_result" && running) {
    completeToolRow(running, "ok", frame.content ?? "");
    return running;
  }
  const row = createToolRow(frame.name ?? "tool", frame.arguments);
  container.append(row);
  if (frame.event === "tool_result") completeToolRow(row, "ok", frame.content ?? "");
  return row;
}

/** Flip every still-running row to error, e.g. when the turn dies mid-call. */
export function markRunningToolsError(container: HTMLElement, message: string): void {
  let running = lastRunningTool(container);
  while (running) {
    completeToolRow(running, "error", message);
    running = lastRunningTool(container);
  }
}

function lastRunningTool(container: HTMLElement): HTMLDetailsElement | null {
  const rows = container.querySelectorAll<HTMLDetailsElement>('.tool-row[data-state="running"]');
  return rows.length ? rows[rows.length - 1] : null;
}

function createToolRow(name: string, args: string | undefined): HTMLDetailsElement {
  const row = document.createElement("details");
  row.className = "tool-row";
  row.dataset.state = "running";

  const head = document.createElement("summary");
  head.className = "tool-head";
  head.append(element("span", name, "tool-name"));
  const chip = element("span", STATUS_LABEL.running, "tool-status");
  chip.dataset.state = "running";
  head.append(chip);
  head.append(element("span", summarize(name, args), "tool-summary"));

  const body = document.createElement("div");
  body.className = "tool-body";
  if (args) body.append(toolSection("Input", args, "tool-input"));

  row.append(head, body);
  return row;
}

function completeToolRow(row: HTMLDetailsElement, state: ToolState, output: string): void {
  row.dataset.state = state;
  const chip = row.querySelector<HTMLElement>(".tool-status");
  if (chip) {
    chip.dataset.state = state;
    chip.textContent = STATUS_LABEL[state];
  }
  if (!output) return;
  const existing = row.querySelector<HTMLElement>(".tool-output");
  if (existing) {
    existing.textContent = output;
    return;
  }
  row.querySelector(".tool-body")?.append(toolSection("Output", output, "tool-output"));
}

function toolSection(label: string, text: string, className: string): HTMLElement {
  const section = document.createElement("div");
  section.className = "tool-section";
  section.append(element("span", label, "tool-label"));
  section.append(element("pre", text, `tool-io ${className}`));
  return section;
}

function summarize(name: string, args: string | undefined): string {
  const compact = (args ?? "").replace(/\s+/g, " ").trim();
  return compact ? `Called ${name} with ${compact}` : `Called ${name}`;
}

const HEADING = /^(#{1,6})\s+(.*)$/;
const UNORDERED_ITEM = /^\s*[-*+]\s+(.*)$/;
const ORDERED_ITEM = /^\s*\d+\.\s+(.*)$/;
const BLOCKQUOTE = /^\s*>\s?(.*)$/;
const FENCE = /^\s*```(.*)$/;
const TABLE_DIVIDER = /^\s*\|?\s*:?-{2,}:?(\s*\|\s*:?-{2,}:?)*\s*\|?\s*$/;
const INLINE = /(`[^`]+`)|(\[[^\]]+\]\([^)]+\))|(\*\*[^*]+\*\*)|(\*[^*]+\*)/g;
const SCHEME = /^[a-z][a-z0-9+.-]*:/i;
const SAFE_SCHEME = /^(https?:|mailto:)/i;

export function renderMarkdown(source: string): DocumentFragment {
  const fragment = document.createDocumentFragment();
  const lines = source.replace(/\r\n?/g, "\n").split("\n");
  let index = 0;
  while (index < lines.length) {
    const line = lines[index];
    if (line.trim() === "") {
      index += 1;
      continue;
    }
    const heading = HEADING.exec(line);
    if (heading) {
      const node = document.createElement(`h${heading[1].length}`);
      node.textContent = heading[2].trim();
      fragment.append(node);
      index += 1;
      continue;
    }
    const fence = FENCE.exec(line);
    if (fence) {
      index = appendCodeBlock(fragment, lines, index, fence[1].trim());
      continue;
    }
    if (isListItem(line)) {
      index = appendList(fragment, lines, index);
      continue;
    }
    if (BLOCKQUOTE.test(line)) {
      index = appendBlockquote(fragment, lines, index);
      continue;
    }
    if (isTableStart(lines, index)) {
      index = appendTable(fragment, lines, index);
      continue;
    }
    index = appendParagraph(fragment, lines, index);
  }
  return fragment;
}

function appendParagraph(fragment: DocumentFragment, lines: string[], start: number): number {
  const collected: string[] = [];
  let index = start;
  while (index < lines.length && lines[index].trim() !== "" && !isBlockStart(lines[index])) {
    collected.push(lines[index].trim());
    index += 1;
  }
  const paragraph = document.createElement("p");
  appendInline(paragraph, collected.join(" "));
  fragment.append(paragraph);
  return index;
}

function appendList(fragment: DocumentFragment, lines: string[], start: number): number {
  const ordered = ORDERED_ITEM.test(lines[start]);
  const pattern = ordered ? ORDERED_ITEM : UNORDERED_ITEM;
  const list = document.createElement(ordered ? "ol" : "ul");
  let index = start;
  while (index < lines.length) {
    const item = pattern.exec(lines[index]);
    if (!item) break;
    const node = document.createElement("li");
    appendInline(node, item[1].trim());
    list.append(node);
    index += 1;
  }
  fragment.append(list);
  return index;
}

function appendBlockquote(fragment: DocumentFragment, lines: string[], start: number): number {
  const collected: string[] = [];
  let index = start;
  while (index < lines.length) {
    const match = BLOCKQUOTE.exec(lines[index]);
    if (!match) break;
    collected.push(match[1].trim());
    index += 1;
  }
  const quote = document.createElement("blockquote");
  appendInline(quote, collected.join(" "));
  fragment.append(quote);
  return index;
}

function appendCodeBlock(
  fragment: DocumentFragment,
  lines: string[],
  start: number,
  language: string,
): number {
  const code: string[] = [];
  let index = start + 1;
  while (index < lines.length && !FENCE.test(lines[index])) {
    code.push(lines[index]);
    index += 1;
  }
  if (index < lines.length) index += 1;
  fragment.append(codeBlock(code.join("\n"), language));
  return index;
}

function codeBlock(code: string, language: string): HTMLElement {
  const wrap = document.createElement("div");
  wrap.className = "code-block";
  const head = document.createElement("div");
  head.className = "code-head";
  if (language) head.append(element("span", language, "code-lang"));
  const button = document.createElement("button");
  button.type = "button";
  button.className = "code-copy";
  button.textContent = "Copy";
  button.addEventListener("click", () => void copyText(button, code));
  head.append(button);
  const pre = document.createElement("pre");
  const codeElement = document.createElement("code");
  codeElement.textContent = code;
  pre.append(codeElement);
  wrap.append(head, pre);
  return wrap;
}

async function copyText(button: HTMLButtonElement, code: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(code);
    button.textContent = "Copied";
  } catch {
    button.textContent = "Copy failed";
  }
}

function isTableStart(lines: string[], index: number): boolean {
  return lines[index].includes("|") && TABLE_DIVIDER.test(lines[index + 1] ?? "");
}

function appendTable(fragment: DocumentFragment, lines: string[], start: number): number {
  const table = document.createElement("table");
  const thead = document.createElement("thead");
  const headerRow = document.createElement("tr");
  for (const cell of splitRow(lines[start])) headerRow.append(tableCell("th", cell));
  thead.append(headerRow);
  table.append(thead);

  const tbody = document.createElement("tbody");
  let index = start + 2;
  while (index < lines.length && lines[index].trim() !== "" && lines[index].includes("|")) {
    const row = document.createElement("tr");
    for (const cell of splitRow(lines[index])) row.append(tableCell("td", cell));
    tbody.append(row);
    index += 1;
  }
  table.append(tbody);
  fragment.append(table);
  return index;
}

function splitRow(line: string): string[] {
  const trimmed = line.trim().replace(/^\|/, "").replace(/\|$/, "");
  return trimmed.split("|").map((cell) => cell.trim());
}

function tableCell(tag: string, text: string): HTMLElement {
  const cell = document.createElement(tag);
  appendInline(cell, text);
  return cell;
}

function appendInline(parent: Node, text: string): void {
  let last = 0;
  for (const match of text.matchAll(INLINE)) {
    const index = match.index ?? 0;
    if (index > last) parent.appendChild(document.createTextNode(text.slice(last, index)));
    parent.appendChild(inlineNode(match[0]));
    last = index + match[0].length;
  }
  if (last < text.length) parent.appendChild(document.createTextNode(text.slice(last)));
}

function inlineNode(token: string): Node {
  if (token.startsWith("`")) return element("code", token.slice(1, -1));
  if (token.startsWith("[")) return linkNode(token);
  if (token.startsWith("**")) return element("strong", token.slice(2, -2));
  return element("em", token.slice(1, -1));
}

function linkNode(token: string): Node {
  const split = token.indexOf("](");
  const label = token.slice(1, split);
  const url = token.slice(split + 2, -1).trim();
  if (!isSafeUrl(url)) return document.createTextNode(label);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.textContent = label;
  return anchor;
}

function isSafeUrl(url: string): boolean {
  if (!url) return false;
  if (SAFE_SCHEME.test(url)) return true;
  return !SCHEME.test(url);
}

function element(tag: string, text: string, className?: string): HTMLElement {
  const node = document.createElement(tag);
  if (className) node.className = className;
  node.textContent = text;
  return node;
}

function isListItem(line: string): boolean {
  return UNORDERED_ITEM.test(line) || ORDERED_ITEM.test(line);
}

function isBlockStart(line: string): boolean {
  return HEADING.test(line) || FENCE.test(line) || isListItem(line) || BLOCKQUOTE.test(line);
}
