import type { Approval, Entry } from "@/lib/api";

export type ToolState = "running" | "ok" | "error" | "pending";

export type ToolItem = {
  kind: "tool";
  name: string;
  args: string;
  result?: string;
  state: ToolState;
};

export type QuestionItem = {
  kind: "question";
  id: string;
  question: string;
  options: string[];
  default: string | null;
  multi: boolean;
  chosen: string[] | null;
  error: string | null;
};

export type ApprovalCard = {
  kind: "approval";
  id: string;
  name: string;
  args: string;
  resolved: "approved" | "denied" | null;
  error: string | null;
};

export type Item =
  | { kind: "user"; text: string }
  | { kind: "assistant"; text: string; live?: boolean }
  | ToolItem
  | { kind: "agent"; name: string; emoji?: string; model?: string }
  | { kind: "notice"; text: string }
  | QuestionItem
  | ApprovalCard;

export type PendingQuestion = {
  id: string;
  question: string;
  options: string[];
  default?: string | null;
  multi?: boolean;
};

const ASK_USER = "ask_user";

function text(value: unknown): string {
  return typeof value === "string" ? value : "";
}

export function chosenFrom(result: string, options: string[]): string[] {
  const clicked = /^The user chose: (.*)$/s.exec(result);
  if (clicked) return clicked[1].split(", ").filter((label) => options.includes(label));
  const fallback = /picked the default option "(.*)"/.exec(result);
  return fallback && options.includes(fallback[1]) ? [fallback[1]] : [];
}

function questionFromArgs(args: string, result: string | null, id: string): QuestionItem | null {
  let data: { question?: unknown; options?: unknown; default?: unknown; multi?: unknown };
  try {
    data = JSON.parse(args) as typeof data;
  } catch {
    return null;
  }
  const options = Array.isArray(data.options) ? data.options.map(String) : [];
  const question = text(data.question);
  if (!question || options.length === 0) return null;
  return {
    kind: "question",
    id,
    question,
    options,
    default: typeof data.default === "string" ? data.default : null,
    multi: Boolean(data.multi),
    chosen: result === null ? null : chosenFrom(result, options),
    error: null,
  };
}

export function fromEntries(entries: Entry[]): Item[] {
  const out: Item[] = [];
  let openAsk: string | null = null;
  for (const entry of entries) {
    if (entry.role === "user") out.push({ kind: "user", text: entry.content });
    else if (entry.role === "assistant") out.push({ kind: "assistant", text: entry.content });
    else if (entry.role === "notice") out.push({ kind: "notice", text: entry.content });
    else if (entry.role === "tool_call" && entry.tool_name === ASK_USER) openAsk = entry.content;
    else if (entry.role === "tool_result" && entry.tool_name === ASK_USER) {
      const card = questionFromArgs(openAsk ?? entry.content, entry.content, "");
      if (card) out.push(card);
      openAsk = null;
    } else if (entry.role === "tool_call") {
      out.push({ kind: "tool", name: entry.tool_name ?? "tool", args: entry.content, state: "ok" });
    } else if (entry.role === "tool_result") {
      const index = [...out]
        .reverse()
        .findIndex((item) => item.kind === "tool" && item.result === undefined);
      const at = index < 0 ? -1 : out.length - 1 - index;
      if (at >= 0) {
        const tool = out[at] as ToolItem;
        out[at] = { ...tool, result: entry.content, state: "ok" };
      } else {
        out.push({
          kind: "tool",
          name: entry.tool_name ?? "tool",
          args: "",
          result: entry.content,
          state: "ok",
        });
      }
    }
  }
  return out;
}

function liveQuestion(question: PendingQuestion): QuestionItem {
  return {
    kind: "question",
    id: question.id,
    question: question.question,
    options: question.options,
    default: question.default ?? null,
    multi: Boolean(question.multi),
    chosen: null,
    error: null,
  };
}

function markToolPending(items: Item[], name: string): Item[] {
  let index = -1;
  items.forEach((item, i) => {
    if (item.kind === "tool" && item.name === name && item.result === undefined) index = i;
  });
  if (index < 0) return items;
  return items.map((item, i) =>
    i === index && item.kind === "tool" ? { ...item, state: "pending" } : item,
  );
}

export function assembleSession(
  entries: Entry[],
  questions: PendingQuestion[],
  pending: Approval[],
  sessionId: string,
): Item[] {
  let items = fromEntries(entries);
  for (const question of questions) {
    if (items.some((item) => item.kind === "question" && item.id === question.id)) continue;
    items.push(liveQuestion(question));
  }
  for (const approval of pending) {
    if (approval.session_id !== sessionId || approval.status !== "pending") continue;
    if (items.some((item) => item.kind === "approval" && item.id === approval.id)) continue;
    items = markToolPending(items, approval.tool_name);
    items.push({
      kind: "approval",
      id: approval.id,
      name: approval.tool_name,
      args: approval.arguments,
      resolved: null,
      error: null,
    });
  }
  return items;
}

function optionsOf(value: unknown): string[] {
  return Array.isArray(value) ? value.map(String) : [];
}

function completeTool(items: Item[], name: string, content: string): Item[] {
  let index = -1;
  items.forEach((item, i) => {
    if (item.kind === "tool" && item.state === "running" && (name === "" || item.name === name))
      index = i;
  });
  if (index < 0)
    return [
      ...items,
      { kind: "tool", name: name || "tool", args: "", result: content, state: "ok" },
    ];
  return items.map((item, i) =>
    i === index && item.kind === "tool" ? { ...item, result: content, state: "ok" } : item,
  );
}

function pendTool(items: Item[], name: string): Item[] {
  let index = -1;
  items.forEach((item, i) => {
    if (item.kind === "tool" && item.name === name && item.state === "running") index = i;
  });
  if (index < 0) return items;
  return items.map((item, i) =>
    i === index && item.kind === "tool" ? { ...item, state: "pending" } : item,
  );
}

export function applyFrame(items: Item[], event: string, data: Record<string, unknown>): Item[] {
  if ((event === "tool_call" || event === "tool_result") && text(data.name) === ASK_USER)
    return items;
  switch (event) {
    case "agent":
      return [
        ...items,
        {
          kind: "agent",
          name: text(data.name) || text(data.agent_id),
          emoji: text(data.emoji) || undefined,
          model: text(data.model) || undefined,
        },
      ];
    case "notice":
      return [...items, { kind: "notice", text: text(data.text) }];
    case "token": {
      const last = items.at(-1);
      if (last?.kind === "assistant" && last.live) {
        return [...items.slice(0, -1), { ...last, text: last.text + text(data.text) }];
      }
      return [...items, { kind: "assistant", text: text(data.text), live: true }];
    }
    case "tool_call":
      return [
        ...items,
        {
          kind: "tool",
          name: text(data.name) || "tool",
          args: text(data.arguments),
          state: "running",
        },
      ];
    case "tool_result":
      return completeTool(items, text(data.name), text(data.content));
    case "approval_required": {
      const name = text(data.name) || "tool";
      const id = text(data.approval_id);
      if (items.some((item) => item.kind === "approval" && item.id === id))
        return pendTool(items, name);
      return [
        ...pendTool(items, name),
        { kind: "approval", id, name, args: text(data.arguments), resolved: null, error: null },
      ];
    }
    case "question": {
      const id = text(data.question_id);
      if (!id || items.some((item) => item.kind === "question" && item.id === id)) return items;
      return [
        ...items,
        {
          kind: "question",
          id,
          question: text(data.question),
          options: optionsOf(data.options),
          default: typeof data.default === "string" ? data.default : null,
          multi: Boolean(data.multi),
          chosen: null,
          error: null,
        },
      ];
    }
    case "done":
      return items.map((item) =>
        item.kind === "assistant" && item.live ? { ...item, live: false } : item,
      );
    case "error":
      return [
        ...items.map((item) =>
          item.kind === "tool" && item.state === "running" ? { ...item, state: "error" } : item,
        ),
        { kind: "notice", text: text(data.error) || "The turn failed." },
      ];
    default:
      return items;
  }
}

export function markQuestionAnswered(items: Item[], id: string, chosen: string[]): Item[] {
  return items.map((item) =>
    item.kind === "question" && item.id === id ? { ...item, chosen, error: null } : item,
  );
}

export function markQuestionError(items: Item[], id: string, error: string): Item[] {
  return items.map((item) =>
    item.kind === "question" && item.id === id ? { ...item, chosen: null, error } : item,
  );
}

export function markApprovalResolved(
  items: Item[],
  id: string,
  resolved: "approved" | "denied",
): Item[] {
  return items.map((item) =>
    item.kind === "approval" && item.id === id ? { ...item, resolved, error: null } : item,
  );
}

export function markApprovalError(items: Item[], id: string, error: string): Item[] {
  return items.map((item) =>
    item.kind === "approval" && item.id === id ? { ...item, error } : item,
  );
}

export type Block = { kind: "group"; tools: ToolItem[] } | Exclude<Item, ToolItem>;

export function blocksOf(items: Item[]): Block[] {
  const out: Block[] = [];
  let tools: ToolItem[] = [];
  const flush = () => {
    if (tools.length === 0) return;
    out.push({ kind: "group", tools });
    tools = [];
  };
  for (const item of items) {
    if (item.kind === "tool") tools.push(item);
    else {
      flush();
      out.push(item);
    }
  }
  flush();
  return out;
}

export function countLabel(count: number): string {
  return count === 1 ? "1 call" : `${count} calls`;
}
