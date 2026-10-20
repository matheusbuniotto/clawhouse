import { useState } from "react";
import { Check, ChevronRight, Loader2, Wrench, X } from "lucide-react";
import {
  blocksOf,
  countLabel,
  type ApprovalCard,
  type Item,
  type QuestionItem,
  type ToolItem,
} from "@/lib/chat-activity";

export function ActivityList({
  items,
  onAnswer,
  onResolve,
}: {
  items: Item[];
  onAnswer: (id: string, selected: string[]) => Promise<void>;
  onResolve: (id: string, ok: boolean) => Promise<void>;
}) {
  return (
    <>
      {blocksOf(items).map((block, index) => {
        if (block.kind === "group") return <ToolGroup key={index} tools={block.tools} />;
        if (block.kind === "question")
          return <QuestionCard key={block.id || index} item={block} onAnswer={onAnswer} />;
        if (block.kind === "approval")
          return <ApprovalCardView key={block.id || index} item={block} onResolve={onResolve} />;
        return <Row key={index} item={block} />;
      })}
    </>
  );
}

function Row({ item }: { item: Exclude<Item, ToolItem | QuestionItem | ApprovalCard> }) {
  switch (item.kind) {
    case "user":
      return (
        <div className="flex justify-end">
          <div className="max-w-[80%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-secondary px-4 py-2.5 text-[15px]">
            {item.text}
          </div>
        </div>
      );
    case "assistant":
      return (
        <div
          className={`whitespace-pre-wrap text-[15px] leading-relaxed ${item.live ? "caret" : ""}`}
        >
          {item.text}
        </div>
      );
    case "agent":
      return (
        <div className="flex items-center gap-2 pt-2 text-sm">
          <span>{item.emoji ?? "🤖"}</span>
          <span className="font-semibold text-primary">@{item.name}</span>
          {item.model && (
            <span className="rounded border px-1.5 font-mono text-[10px] text-muted-foreground">
              {item.model}
            </span>
          )}
        </div>
      );
    case "notice":
      return (
        <p className="border-l-2 border-primary/50 pl-3 font-mono text-xs text-muted-foreground">
          {item.text}
        </p>
      );
  }
}

function ToolGroup({ tools }: { tools: ToolItem[] }) {
  const [open, setOpen] = useState(false);
  const running = tools.find((tool) => tool.state === "running");
  const pending = tools.find((tool) => tool.state === "pending");
  return (
    <div data-tool-group="" className="overflow-hidden rounded-lg border bg-rail font-mono text-xs">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-muted-foreground hover:text-foreground"
      >
        <ChevronRight className={`size-3 transition ${open ? "rotate-90" : ""}`} />
        <Wrench className="size-3 text-primary" />
        <span>{open ? "Hide tool calls" : "Expand tool calls"}</span>
        <span>{countLabel(tools.length)}</span>
        {pending ? <span>{`Approval required for ${pending.name}`}</span> : null}
        {!pending && running ? <span>{`Running ${running.name}...`}</span> : null}
        <span className="ml-auto">
          {running ? (
            <Loader2 className="size-3 animate-spin text-primary" />
          ) : (
            <Check className="size-3 text-success" />
          )}
        </span>
      </button>
      {open &&
        tools.map((tool, index) => (
          <div key={index} data-state={tool.state} className="space-y-2 border-t px-3 py-2">
            <div className="flex items-center gap-2">
              <span className="text-foreground">{tool.name}</span>
              {tool.state === "error" ? <X className="size-3 text-destructive" /> : null}
            </div>
            {tool.args ? (
              <pre className="overflow-x-auto whitespace-pre-wrap text-muted-foreground">
                {tool.args}
              </pre>
            ) : null}
            {tool.result ? (
              <pre className="overflow-x-auto whitespace-pre-wrap text-foreground">
                {tool.result}
              </pre>
            ) : null}
          </div>
        ))}
    </div>
  );
}

function QuestionCard({
  item,
  onAnswer,
}: {
  item: QuestionItem;
  onAnswer: (id: string, selected: string[]) => Promise<void>;
}) {
  const [picked, setPicked] = useState<string[]>([]);
  const [sending, setSending] = useState(false);
  const locked = item.chosen !== null || sending;

  async function send(selected: string[]) {
    setSending(true);
    try {
      await onAnswer(item.id, selected);
    } finally {
      setSending(false);
    }
  }

  function toggle(label: string) {
    setPicked((current) =>
      current.includes(label) ? current.filter((value) => value !== label) : [...current, label],
    );
  }

  return (
    <div
      role="group"
      aria-label={item.question}
      data-question-id={item.id}
      className="rounded-lg border p-4"
    >
      <p>{item.question}</p>
      <div className="mt-3 flex flex-wrap gap-2">
        {item.options.map((label) => {
          const chosen = item.chosen?.includes(label) ?? false;
          return (
            <button
              key={label}
              type="button"
              disabled={locked}
              aria-pressed={
                item.chosen === null
                  ? item.multi && picked.includes(label)
                    ? "true"
                    : "false"
                  : chosen
                    ? "true"
                    : "false"
              }
              onClick={() => (item.multi ? toggle(label) : void send([label]))}
              className="rounded-md border px-3 py-1 text-sm"
            >
              {label}
              {label === item.default ? <span> default</span> : null}
            </button>
          );
        })}
      </div>
      {item.multi && item.chosen === null ? (
        <button
          type="button"
          disabled={locked || picked.length === 0}
          onClick={() => void send(picked)}
          className="mt-3 rounded-md bg-primary px-3 py-1 text-xs font-medium text-primary-foreground disabled:opacity-30"
        >
          Send
        </button>
      ) : null}
      {item.error ? <p className="mt-3 text-sm text-destructive">{item.error}</p> : null}
    </div>
  );
}

function ApprovalCardView({
  item,
  onResolve,
}: {
  item: ApprovalCard;
  onResolve: (id: string, ok: boolean) => Promise<void>;
}) {
  const [sending, setSending] = useState(false);

  async function act(ok: boolean) {
    setSending(true);
    try {
      await onResolve(item.id, ok);
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="rounded-lg border border-warning/40 bg-warning/5 p-4">
      {item.resolved ? (
        <p>{item.resolved === "approved" ? `Approved ${item.name}` : `Denied ${item.name}`}</p>
      ) : (
        <div className="flex items-center gap-2 text-sm">
          <span className="size-2 rounded-full bg-warning" />
          <span className="font-mono">{item.name}</span>
        </div>
      )}
      {item.args ? (
        <details className="mt-2">
          <summary>Arguments</summary>
          <pre className="mt-2 overflow-x-auto rounded bg-rail p-2 font-mono text-xs text-muted-foreground">
            {item.args}
          </pre>
        </details>
      ) : null}
      {item.error ? <p className="mt-3 text-sm text-destructive">{item.error}</p> : null}
      {item.resolved ? null : (
        <div className="mt-3 flex gap-2">
          <button
            type="button"
            disabled={sending}
            onClick={() => void act(true)}
            className="rounded-md bg-primary px-3 py-1 text-xs font-medium text-primary-foreground"
          >
            Approve
          </button>
          <button
            type="button"
            disabled={sending}
            onClick={() => void act(false)}
            className="rounded-md border px-3 py-1 text-xs"
          >
            Deny
          </button>
        </div>
      )}
    </div>
  );
}
