/** Pure, side-effect-free transcript rendering: markdown and tool-activity rows. */

import { el, rawJsonDisclosure, svgEl, type ActivityState } from "./dom.js";
import { highlight } from "./highlight.js";
import { renderJobView, tryParseJobView } from "./jobs.js";

export type ToolState = ActivityState;

export function renderUserTurn(text: string): HTMLParagraphElement {
  return el("p", "bubble user", text);
}

export function renderAssistantTurn(source: string): HTMLElement {
  const node = el("article", "assistant");
  node.append(renderMarkdown(source));

  const actions = el("div", "assistant-actions");
  const copyBtn = el("button", "assistant-action-btn copy-btn");
  copyBtn.type = "button";
  copyBtn.title = "Copy markdown";
  copyBtn.setAttribute("aria-label", "Copy markdown");

  const copyIcon = svgEl("svg", {
    width: "14",
    height: "14",
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    "stroke-width": "2",
    "stroke-linecap": "round",
    "stroke-linejoin": "round",
    "aria-hidden": "true",
  });
  copyIcon.append(
    svgEl("rect", { x: "9", y: "9", width: "13", height: "13", rx: "2", ry: "2" }),
    svgEl("path", { d: "M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" }),
  );
  const copyLabel = el("span", "assistant-action-label", "");
  copyBtn.append(copyIcon, copyLabel);

  copyBtn.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(source);
      copyLabel.textContent = "Copied!";
      copyBtn.classList.add("copied");
      setTimeout(() => {
        copyLabel.textContent = "";
        copyBtn.classList.remove("copied");
      }, 2000);
    } catch {
      copyLabel.textContent = "Failed to copy";
      setTimeout(() => {
        copyLabel.textContent = "";
      }, 2000);
    }
  });

  actions.append(copyBtn);
  node.append(actions);
  return node;
}

export interface AgentLabel {
  agent_id: string;
  name?: string;
  emoji?: string;
  model?: string;
}

/** Names who answers the turn below it, and on which model (switching agents can switch models). */
export function renderAgentHeader(agent: AgentLabel): HTMLElement {
  const node = el("div", "agent-header");
  node.dataset.agentId = agent.agent_id;
  if (agent.emoji) node.append(el("span", "agent-header-emoji", agent.emoji));
  node.append(el("strong", "agent-header-name", `@${agent.name || agent.agent_id}`));
  if (agent.model) node.append(el("span", "agent-header-model", agent.model));
  return node;
}

/** A line for the reader, never sent to the model, e.g. "@x não encontrado". */
export function renderNotice(text: string): HTMLElement {
  const node = el("p", "agent-notice", text);
  node.setAttribute("role", "note");
  return node;
}

export interface ToolFrame {
  event: "tool_call" | "tool_result";
  name?: string;
  arguments?: string;
  content?: string;
}

const STATUS_LABEL: Record<ActivityState, string> = {
  running: "Running",
  ok: "OK",
  error: "Error",
  idle: "Idle",
  pending: "Approval Needed",
};

function genericArgumentsPreview(raw: string | undefined): HTMLElement | null {
  const data = parseObject(raw);
  if (!data || Object.keys(data).length === 0) return null;
  const wrap = el("details", "approval-params-disclosure");
  const summary = el("summary", "approval-params-summary", "Call parameters");
  const pre = el("pre", "approval-preview", JSON.stringify(data, null, 2));
  wrap.append(summary, pre);
  return wrap;
}

/**
 * Approve/Deny for a paused tool call. The card sits after the tool group so
 * it stays visible while that group is collapsed.
 */
export function renderInlineApproval(
  container: HTMLElement,
  approvalId: string,
  toolName: string,
  onResolved: (reply?: string) => void,
  toolArguments?: string,
  onStream?: (response: Response) => Promise<boolean | void>,
): HTMLElement {
  const running = runningToolNamed(container, toolName);
  if (running) {
    running.dataset.state = "pending";
    running.open = true;
    const chip = running.querySelector<HTMLElement>(".tool-status");
    if (chip) {
      chip.dataset.state = "pending";
      chip.textContent = STATUS_LABEL.pending;
    }
    const group = running.closest<HTMLDetailsElement>(".tool-group");
    if (group) syncGroupLabel(group);
  }

  const card = el("div", "approval-action-bar");
  card.dataset.approvalId = approvalId;
  const preview = writePreview(toolName, toolArguments);
  const msg = el(
    "span",
    "approval-msg",
    preview?.question ?? `Approval required to execute ${toolName}.`
  );
  const btns = el("div", "approval-buttons");
  const approveBtn = el("button", "btn-approve", "Approve");
  const denyBtn = el("button", "btn-deny", "Deny");

  async function resolve(decision: "approved" | "denied") {
    approveBtn.disabled = true;
    denyBtn.disabled = true;
    approveBtn.textContent = decision === "approved" ? "Approving…" : "Approve";
    denyBtn.textContent = decision === "denied" ? "Denying…" : "Deny";
    card.classList.add("resolving");
    if (running) {
      running.dataset.state = decision === "approved" ? "running" : "error";
      const chip = running.querySelector<HTMLElement>(".tool-status");
      if (chip) {
        chip.dataset.state = decision === "approved" ? "running" : "error";
        chip.textContent = decision === "approved" ? STATUS_LABEL.running : "Denying…";
      }
      const group = running.closest<HTMLDetailsElement>(".tool-group");
      if (group) syncGroupLabel(group);
    }
    msg.textContent = decision === "approved" ? `Executing approved ${toolName}…` : `Denying ${toolName}…`;
    try {
      const endpoint = decision === "approved" ? "approve" : "deny";
      const options: RequestInit = { method: "POST" };
      if (onStream) {
        options.headers = { Accept: "text/event-stream" };
      }
      const resp = await fetch(`/api/approvals/${approvalId}/${endpoint}`, options);
      if (!resp.ok) {
        msg.textContent = `Action failed: ${resp.statusText || "Request failed"}`;
        card.classList.remove("resolving");
        approveBtn.disabled = false;
        denyBtn.disabled = false;
        approveBtn.textContent = "Approve";
        denyBtn.textContent = "Deny";
        if (running) {
          running.dataset.state = "pending";
          const chip = running.querySelector<HTMLElement>(".tool-status");
          if (chip) {
            chip.dataset.state = "pending";
            chip.textContent = STATUS_LABEL.pending;
          }
          const group = running.closest<HTMLDetailsElement>(".tool-group");
          if (group) syncGroupLabel(group);
        }
        return;
      }
      btns.remove();
      card.classList.remove("resolving");
      const contentType = (typeof resp.headers?.get === "function" ? resp.headers.get("content-type") : "") ?? "";
      const isStreaming = contentType.includes("text/event-stream") && typeof onStream === "function";

      if (decision === "denied") {
        card.classList.add("resolved-error");
        msg.textContent = `✕ Denied ${toolName}`;
        if (running) {
          running.dataset.state = "error";
          const chip = running.querySelector<HTMLElement>(".tool-status");
          if (chip) {
            chip.dataset.state = "error";
            chip.textContent = "Denied";
          }
          const group = running.closest<HTMLDetailsElement>(".tool-group");
          if (group) syncGroupLabel(group);
        }
        if (isStreaming) {
          await onStream(resp);
        } else {
          const data = (await resp.json()) as { status: string; reply?: string };
          onResolved(data.reply);
        }
        return;
      }

      // decision === "approved"
      if (isStreaming) {
        card.classList.add("executing");
        msg.textContent = `✓ Approved · Running ${toolName}…`;
        if (running) {
          running.dataset.state = "running";
          const chip = running.querySelector<HTMLElement>(".tool-status");
          if (chip) {
            chip.dataset.state = "running";
            chip.textContent = STATUS_LABEL.running;
          }
          const group = running.closest<HTMLDetailsElement>(".tool-group");
          if (group) syncGroupLabel(group);
        }
        await onStream(resp);
        card.classList.remove("executing");
        card.classList.add("resolved-ok");
        msg.textContent = `✓ Approved ${toolName}`;
        if (running && running.dataset.state === "running") {
          completeToolRow(running, "ok", "");
        }
      } else {
        card.classList.add("resolved-ok");
        msg.textContent = `✓ Approved ${toolName}`;
        if (running) {
          running.dataset.state = "ok";
          const chip = running.querySelector<HTMLElement>(".tool-status");
          if (chip) {
            chip.dataset.state = "ok";
            chip.textContent = STATUS_LABEL.ok;
          }
          const group = running.closest<HTMLDetailsElement>(".tool-group");
          if (group) syncGroupLabel(group);
        }
        const data = (await resp.json()) as { status: string; reply?: string };
        onResolved(data.reply);
      }
    } catch {
      msg.textContent = "Network error while resolving approval.";
      card.classList.remove("resolving");
      approveBtn.disabled = false;
      denyBtn.disabled = false;
      approveBtn.textContent = "Approve";
      denyBtn.textContent = "Deny";
      if (running) {
        running.dataset.state = "pending";
        const chip = running.querySelector<HTMLElement>(".tool-status");
        if (chip) {
          chip.dataset.state = "pending";
          chip.textContent = STATUS_LABEL.pending;
        }
        const group = running.closest<HTMLDetailsElement>(".tool-group");
        if (group) syncGroupLabel(group);
      }
    }
  }

  approveBtn.onclick = () => void resolve("approved");
  denyBtn.onclick = () => void resolve("denied");

  btns.append(approveBtn, denyBtn);
  card.append(msg);
  if (preview) {
    card.append(preview.note, preview.body);
  } else if (toolArguments) {
    const argsPreview = genericArgumentsPreview(toolArguments);
    if (argsPreview) card.append(argsPreview);
  }
  card.append(btns);

  placeApprovalCard(container, running, card);
  return card;
}

const SHEET_ID = /^[A-Za-z0-9_-]{20,100}$/;
const SHEET_URL = /^https:\/\/docs\.google\.com\/spreadsheets\/d\/[A-Za-z0-9_-]{20,100}$/;

interface WritePreview {
  question: string;
  note: HTMLElement;
  body: HTMLElement;
}

function writePreview(toolName: string, raw: string | undefined): WritePreview | null {
  const input = parseObject(raw);
  if (!input) return null;
  if (toolName === "create_google_sheet") return sheetPreview(input, "create");
  if (toolName === "update_google_sheet") return sheetPreview(input, "update");
  return null;
}

function sheetPreview(
  input: Record<string, unknown>,
  action: "create" | "update",
): WritePreview | null {
  const sheet = sheetFields(input);
  if (!sheet) return null;
  const width = sheet.rows[0]?.length ?? 0;
  const note = el(
    "p",
    "approval-note",
    `${sheet.rows.length} rows × ${width} columns. These rows leave Databricks and then follow Google's sharing rules.`,
  );
  const body = el("div", "approval-sheet");
  if (action === "update" && sheet.spreadsheetId) {
    const link = el("a", "approval-link", "Open the destination spreadsheet");
    link.href = `https://docs.google.com/spreadsheets/d/${sheet.spreadsheetId}`;
    link.target = "_blank";
    link.rel = "noreferrer";
    body.append(link);
  }
  body.append(el("pre", "approval-preview", sheet.text));
  const question =
    action === "create"
      ? `Create the spreadsheet "${sheet.title}" in your Google Drive?`
      : `Overwrite ${sheet.rows.length} rows on tab "${sheet.tab}" starting at ${sheet.start}?`;
  return { question, note, body };
}

interface SheetFields {
  title: string;
  tab: string;
  start: string;
  spreadsheetId?: string;
  rows: unknown[][];
  text: string;
}

function sheetFields(input: Record<string, unknown>): SheetFields | null {
  const source = nestedSheet(input);
  if (!Array.isArray(source.rows) || source.rows.length === 0) return null;
  const rows = source.rows.filter((row): row is unknown[] => Array.isArray(row));
  if (rows.length !== source.rows.length) return null;
  const spreadsheetId = sheetId(source.spreadsheet_id);
  return {
    title: typeof source.title === "string" ? source.title : "Untitled",
    tab: typeof source.tab === "string" ? source.tab : "first tab",
    start: `${typeof source.first_column === "string" ? source.first_column : "A"}${
      typeof source.first_row === "number" ? source.first_row : 1
    }`,
    spreadsheetId,
    rows,
    text: rows.map((row) => row.map(cellText).join("\t")).join("\n"),
  };
}

function nestedSheet(input: Record<string, unknown>): Record<string, unknown> {
  const sheet = input.sheet;
  if (typeof sheet === "object" && sheet !== null) return sheet as Record<string, unknown>;
  const update = input.update;
  if (typeof update === "object" && update !== null) return update as Record<string, unknown>;
  return input;
}

function sheetId(value: unknown): string | undefined {
  return typeof value === "string" && SHEET_ID.test(value) ? value : undefined;
}

function cellText(value: unknown): string {
  if (value === null || value === undefined) return "";
  return String(value);
}

function parseObject(raw: string | undefined): Record<string, unknown> | null {
  if (!raw) return null;
  try {
    const data = JSON.parse(raw) as unknown;
    if (typeof data !== "object" || data === null || Array.isArray(data)) return null;
    return data as Record<string, unknown>;
  } catch {
    return null;
  }
}

function sheetResultLink(output: string): HTMLAnchorElement | null {
  const data = parseObject(output);
  if (!data || data.written !== true || typeof data.url !== "string" || !SHEET_URL.test(data.url)) {
    return null;
  }
  const link = el("a", "approval-link", "Open spreadsheet");
  link.href = data.url;
  link.target = "_blank";
  link.rel = "noreferrer";
  return link;
}

/**
 * One activity row per call: a `tool_call` opens it running, a following
 * `tool_result` completes the same row. Consecutive rows share one closed
 * group until something else is appended to the transcript.
 */
export function appendToolActivity(container: HTMLElement, frame: ToolFrame): HTMLElement {
  const running =
    lastRunningTool(container) ||
    (frame.event === "tool_result" && frame.name ? runningToolNamed(container, frame.name) : null);
  if (frame.event === "tool_result" && running) {
    completeToolRow(running, "ok", frame.content ?? "");
    return running;
  }
  const group = ensureToolGroup(container);
  const row = createToolRow(frame.name ?? "tool", frame.arguments);
  group.append(row);
  syncGroupLabel(group);
  if (frame.event === "tool_result") completeToolRow(row, "ok", frame.content ?? "");
  return row;
}

function ensureToolGroup(container: HTMLElement): HTMLDetailsElement {
  const last = container.lastElementChild;
  if (last instanceof HTMLDetailsElement && last.classList.contains("tool-group")) return last;
  const group = el("details", "tool-group");
  const summary = el("summary", "tool-group-toggle");
  const icon = el("span", "tool-group-icon");
  const label = el("span", "tool-group-label", "Expand tool calls");
  const count = el("span", "tool-group-count", "0 calls");
  const live = el("span", "tool-group-live", "");
  live.hidden = true;
  summary.append(icon, label, count, live);
  group.append(summary);
  group.addEventListener("toggle", () => syncGroupLabel(group));
  container.append(group);
  return group;
}

function syncGroupLabel(group: HTMLDetailsElement): void {
  const label = group.querySelector(".tool-group-label");
  const count = group.querySelector(".tool-group-count");
  const live = group.querySelector<HTMLElement>(".tool-group-live");
  const numRows = toolRowCount(group);
  const running = group.querySelector<HTMLDetailsElement>('.tool-row[data-state="running"]');
  const runningName = running?.querySelector(".tool-name")?.textContent;
  const pending = group.querySelector<HTMLDetailsElement>('.tool-row[data-state="pending"]');
  const pendingName = pending?.querySelector(".tool-name")?.textContent;

  if (pending) {
    group.dataset.state = "pending";
  } else if (running) {
    group.dataset.state = "running";
  } else {
    group.dataset.state = "ok";
  }

  if (label) label.textContent = group.open ? "Hide tool calls" : "Expand tool calls";
  if (count) count.textContent = `${numRows} ${numRows === 1 ? "call" : "calls"}`;
  if (live) {
    if (pendingName) {
      live.textContent = `· Approval required for ${pendingName}…`;
      live.hidden = false;
    } else if (runningName) {
      live.textContent = `· Running ${runningName}...`;
      live.hidden = false;
    } else {
      live.textContent = "";
      live.hidden = true;
    }
  }
}

function toolRowCount(group: HTMLElement): number {
  let count = 0;
  for (const child of group.children) {
    if (child.classList.contains("tool-row")) count += 1;
  }
  return count;
}

function runningToolNamed(container: HTMLElement, toolName: string): HTMLDetailsElement | null {
  const rows = container.querySelectorAll<HTMLDetailsElement>(
    '.tool-row[data-state="running"], .tool-row[data-state="pending"]',
  );
  for (let index = rows.length - 1; index >= 0; index -= 1) {
    if (rows[index].querySelector(".tool-name")?.textContent === toolName) return rows[index];
  }
  return null;
}

function placeApprovalCard(
  container: HTMLElement,
  running: HTMLDetailsElement | null,
  card: HTMLElement,
): void {
  const group = running?.closest(".tool-group");
  if (!group) {
    container.append(card);
    return;
  }
  let anchor: Element = group;
  let next = group.nextElementSibling;
  while (next?.classList.contains("approval-action-bar")) {
    anchor = next;
    next = next.nextElementSibling;
  }
  anchor.insertAdjacentElement("afterend", card);
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
  const row = el("details", "tool-row");
  row.dataset.state = "running";

  const head = el("summary", "tool-head");
  head.append(el("span", "tool-name", name));
  const chip = el("span", "tool-status", STATUS_LABEL.running);
  chip.dataset.state = "running";
  head.append(chip);

  const body = el("div", "tool-body");
  if (args) body.append(toolSection("Input", args, "tool-input"));

  row.append(head, body);
  return row;
}

function completeToolRow(row: HTMLDetailsElement, state: ActivityState, output: string): void {
  row.dataset.state = state;
  const chip = row.querySelector<HTMLElement>(".tool-status");
  if (chip) {
    chip.dataset.state = state;
    chip.textContent = STATUS_LABEL[state];
  }
  const group = row.closest<HTMLDetailsElement>(".tool-group");
  if (group) syncGroupLabel(group);
  if (!output) return;
  const existing = row.querySelector<HTMLElement>(".tool-output");
  if (existing) {
    existing.textContent = output;
    return;
  }
  row.querySelector(".tool-body")?.append(toolOutputSection(output));
}

function toolOutputSection(output: string): HTMLElement {
  const section = el("div", "tool-section");
  section.append(el("span", "tool-label", "Output"));

  const parsed = tryParseTabular(output);
  const job = parsed ? null : tryParseJobView(output);
  const analysis = analysisResult(output);
  const sheetLink = sheetResultLink(output);
  if (sheetLink) section.append(sheetLink);
  if (analysis) section.append(analysis);
  if (parsed) {
    section.append(renderTabularView(parsed, output));
  } else if (job) {
    section.append(renderJobView(job, output));
  } else {
    section.append(el("pre", "tool-io tool-output", output));
  }
  return section;
}

interface TabularData {
  columns: string[];
  rows: (unknown[] | Record<string, unknown>)[];
  row_count?: number;
}

function analysisResult(output: string): HTMLElement | null {
  const data = parseObject(output);
  if (!data) return null;
  const failed = data.result_state === "FAILED" || data.status === "TIMED_OUT_WAITING";
  if (typeof data.result_state !== "string" && !failed) return null;
  const box = el("div", "analysis-result");
  if (typeof data.result_state === "string") {
    box.append(el("span", "analysis-result-state", data.result_state));
  }
  if (typeof data.duration_ms === "number") {
    box.append(el("span", "analysis-duration", String(data.duration_ms)));
  }
  if (typeof data.logs === "string") box.append(el("pre", "analysis-logs", data.logs));
  if (failed) {
    const errorText =
      typeof data.error === "string"
        ? data.error
        : data.status === "TIMED_OUT_WAITING"
          ? "TIMED_OUT_WAITING"
          : "";
    if (errorText) box.append(el("p", "analysis-error", errorText));
    if (typeof data.run_page_url === "string") {
      const link = el("a", "analysis-run-link", "Open run");
      link.href = data.run_page_url;
      box.append(link);
    }
  }
  return box;
}

function tryParseTabular(text: string): TabularData | null {
  try {
    const data = JSON.parse(text) as unknown;
    if (typeof data !== "object" || data === null) return null;
    const obj = data as Record<string, unknown>;
    if (Array.isArray(obj.columns) && Array.isArray(obj.rows)) {
      return {
        columns: obj.columns.map(String),
        rows: obj.rows as (unknown[] | Record<string, unknown>)[],
        row_count: typeof obj.row_count === "number" ? obj.row_count : (obj.rows as unknown[]).length,
      };
    }
    return null;
  } catch {
    return null;
  }
}

function renderTabularView(data: TabularData, rawJson: string): HTMLElement {
  const wrap = el("div", "tabular-result");
  const count = data.row_count ?? data.rows.length;
  const meta = el("div", "tabular-meta");
  meta.append(el("span", "tabular-count", `${count} row${count === 1 ? "" : "s"}`));

  const tableWrap = el("div", "tabular-table-wrap");
  const table = document.createElement("table");
  table.className = "tabular-table";

  const thead = document.createElement("thead");
  const trHead = document.createElement("tr");
  for (const col of data.columns) {
    const th = document.createElement("th");
    th.textContent = col;
    trHead.append(th);
  }
  thead.append(trHead);
  table.append(thead);

  const tbody = document.createElement("tbody");
  for (const row of data.rows) {
    const tr = document.createElement("tr");
    if (Array.isArray(row)) {
      for (const val of row) {
        const td = document.createElement("td");
        td.textContent = val === null || val === undefined ? "NULL" : String(val);
        tr.append(td);
      }
    } else if (typeof row === "object" && row !== null) {
      for (const col of data.columns) {
        const td = document.createElement("td");
        const val = (row as Record<string, unknown>)[col];
        td.textContent = val === null || val === undefined ? "NULL" : String(val);
        tr.append(td);
      }
    }
    tbody.append(tr);
  }
  table.append(tbody);
  tableWrap.append(table);


  wrap.append(meta, tableWrap, rawJsonDisclosure(rawJson));
  return wrap;
}

function toolSection(label: string, text: string, className: string): HTMLElement {
  const section = el("div", "tool-section");
  section.append(el("span", "tool-label", label));
  section.append(el("pre", `tool-io ${className}`, text));
  return section;
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
  const wrap = el("div", "code-block");
  const head = el("div", "code-head");
  if (language) head.append(el("span", "code-lang", language));
  const button = el("button", "code-copy", "Copy");
  button.type = "button";
  button.addEventListener("click", () => void copyText(button, code));
  head.append(button);
  const pre = document.createElement("pre");
  const codeElement = document.createElement("code");
  for (const token of highlight(code, language)) {
    if (token.kind === "plain") codeElement.append(document.createTextNode(token.text));
    else codeElement.append(el("span", `tok tok-${token.kind}`, token.text));
  }
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
  if (token.startsWith("`")) return el("code", undefined, token.slice(1, -1));
  if (token.startsWith("[")) return linkNode(token);
  if (token.startsWith("**")) return el("strong", undefined, token.slice(2, -2));
  return el("em", undefined, token.slice(1, -1));
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

function isListItem(line: string): boolean {
  return UNORDERED_ITEM.test(line) || ORDERED_ITEM.test(line);
}

function isBlockStart(line: string): boolean {
  return HEADING.test(line) || FENCE.test(line) || isListItem(line) || BLOCKQUOTE.test(line);
}
