import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { ArrowUp, ChevronRight, Square, Wrench, Check, X, Loader2 } from "lucide-react";
import { z } from "zod";
import { api, type Entry } from "@/lib/api";

export const Route = createFileRoute("/")({
  validateSearch: z.object({ session: z.string().optional(), agent: z.string().optional() }),
  head: () => ({
    meta: [
      { title: "Chat · Clawhouse" },
      { name: "description", content: "Talk to your agents, watch tools run, approve actions inline." },
      { property: "og:title", content: "Chat · Clawhouse" },
      { property: "og:description", content: "Talk to your agents, watch tools run, approve actions inline." },
    ],
  }),
  component: Chat,
});

type Item =
  | { kind: "user"; text: string }
  | { kind: "assistant"; text: string; live?: boolean }
  | { kind: "tool"; name: string; args: string; result?: string | undefined; state: "running" | "ok" | "error" }
  | { kind: "agent"; name: string; emoji?: string | undefined; model?: string | undefined }
  | { kind: "notice"; text: string }
  | { kind: "approval"; id: string; name: string; args?: string | undefined; resolved?: "approved" | "denied" };

function fromEntries(entries: Entry[]): Item[] {
  const out: Item[] = [];
  for (const e of entries) {
    if (e.role === "user") out.push({ kind: "user", text: e.content });
    else if (e.role === "assistant") out.push({ kind: "assistant", text: e.content });
    else if (e.role === "notice") out.push({ kind: "notice", text: e.content });
    else if (e.role === "tool_call") out.push({ kind: "tool", name: e.tool_name ?? "tool", args: e.content, state: "ok" });
    else if (e.role === "tool_result") {
      const t = [...out].reverse().find((i) => i.kind === "tool" && !i.result) as Extract<Item, { kind: "tool" }> | undefined;
      if (t) t.result = e.content;
      else out.push({ kind: "tool", name: e.tool_name ?? "tool", args: "", result: e.content, state: "ok" });
    }
  }
  return out;
}

function Chat() {
  const { session, agent } = Route.useSearch();
  const nav = useNavigate();
  const qc = useQueryClient();
  const [items, setItems] = useState<Item[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [usage, setUsage] = useState<{ in: number; win: number | null } | null>(null);
  const [model, setModel] = useState("");
  const abort = useRef<AbortController | null>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const models = useQuery({ queryKey: ["models"], queryFn: api.models });
  const agents = useQuery({ queryKey: ["agents"], queryFn: api.agents });
  const meta = useQuery({ queryKey: ["session", session], queryFn: () => api.session(session!), enabled: !!session });

  useEffect(() => {
    if (!model && models.data?.length) setModel((models.data.find((m) => m.default) ?? models.data[0]!).id);
  }, [models.data, model]);

  useEffect(() => {
    setItems([]); setUsage(null);
    if (!session) return;
    api.transcript(session).then((b) => setItems(fromEntries(b.entries ?? []))).catch(() => {});
  }, [session]);

  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: "smooth" });
  }, [items]);

  const update = (fn: (prev: Item[]) => Item[]) => setItems(fn);

  async function send() {
    const msg = text.trim();
    if (!msg || busy) return;
    let sid = session;
    if (!sid) {
      sid = (await api.createSession()).id;
      nav({ to: "/", search: { session: sid, agent }, replace: true });
    }
    setText(""); setBusy(true);
    update((p) => [...p, { kind: "user", text: msg }]);
    abort.current = new AbortController();
    try {
      for await (const f of api.turn(sid, { message: msg, model: model || null, agent: agent ?? null }, abort.current.signal)) {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const d = f.data as any;
        update((p) => {
          const n = [...p];
          const last = n[n.length - 1];
          switch (f.event) {
            case "agent": n.push({ kind: "agent", name: d.name || d.agent_id, emoji: d.emoji, model: d.model }); break;
            case "notice": n.push({ kind: "notice", text: d.text }); break;
            case "token":
              if (last?.kind === "assistant" && last.live) n[n.length - 1] = { ...last, text: last.text + d.text };
              else n.push({ kind: "assistant", text: d.text, live: true });
              break;
            case "tool_call": n.push({ kind: "tool", name: d.name ?? "tool", args: d.arguments ?? "", state: "running" }); break;
            case "tool_result": {
              const i = n.map((x) => x.kind === "tool" && x.state === "running").lastIndexOf(true);
              if (i >= 0) n[i] = { ...(n[i] as Extract<Item, { kind: "tool" }>), result: d.content, state: "ok" };
              break;
            }
            case "approval_required": n.push({ kind: "approval", id: d.approval_id, name: d.name ?? "tool", args: d.arguments }); break;
            case "done":
              return n.map((x) => (x.kind === "assistant" && x.live ? { ...x, live: false } : x));
            case "error":
              n.push({ kind: "notice", text: d.error ?? "The turn failed." });
              return n.map((x) => (x.kind === "tool" && x.state === "running" ? { ...x, state: "error" } : x));
          }
          return n;
        });
        if (f.event === "usage") setUsage({ in: Number(d.input_tokens) || 0, win: (d.context_window as number) ?? null });
      }
    } catch (e) {
      if ((e as Error).name !== "AbortError") update((p) => [...p, { kind: "notice", text: "Connection lost." }]);
    } finally {
      setBusy(false);
      qc.invalidateQueries({ queryKey: ["sessions"] });
      qc.invalidateQueries({ queryKey: ["session", sid] });
    }
  }

  function stop() {
    abort.current?.abort();
    if (session) api.cancel(session);
    update((p) => [...p.map((x) => (x.kind === "assistant" && x.live ? { ...x, live: false } : x)), { kind: "notice", text: "Stopped." }]);
  }

  const activeAgent = agents.data?.find((a) => a.name === (agent ?? "main"));
  const empty = items.length === 0;

  return (
    <div className="flex h-full flex-col">
      <header className="flex h-14 shrink-0 items-center gap-3 border-b px-6 pl-14 md:pl-6">
        <span className="truncate font-medium">{meta.data?.title || (session ? "Untitled" : "New session")}</span>
        {usage && (
          <span className="ml-auto font-mono text-[11px] text-muted-foreground">
            ctx {usage.in.toLocaleString()}{usage.win ? ` / ${(usage.win / 1000).toFixed(0)}k` : ""}
          </span>
        )}
      </header>

      <div ref={scroller} className="flex-1 overflow-y-auto">
        {empty ? (
          <div className="grid h-full place-items-center grid-bg">
            <div className="text-center">
              <div className="mx-auto grid size-16 place-items-center rounded-2xl bg-surface text-4xl glow">{activeAgent?.signature_emoji ?? "🦞"}</div>
              <h2 className="mt-6 text-3xl font-semibold tracking-tight">What should we claw at today?</h2>
              <p className="mt-2 text-sm text-muted-foreground">Ask anything. Mention <span className="font-mono text-primary">@agent</span> to hand off.</p>
            </div>
          </div>
        ) : (
          <div className="mx-auto max-w-3xl space-y-5 px-6 py-8">
            {items.map((it, i) => <Row key={i} item={it} onResolve={(ok) => update((p) => p.map((x, j) => (j === i && x.kind === "approval" ? { ...x, resolved: ok ? "approved" : "denied" } : x)))} />)}
            {busy && !items.some((x) => x.kind === "assistant" && x.live) && (
              <div className="flex items-center gap-2 font-mono text-xs text-muted-foreground"><Loader2 className="size-3 animate-spin text-primary" /> thinking…</div>
            )}
          </div>
        )}
      </div>

      <div className="shrink-0 px-6 pb-6">
        <div className="mx-auto max-w-3xl rounded-2xl border bg-surface p-2 transition focus-within:glow">
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
            rows={Math.min(8, Math.max(2, text.split("\n").length))}
            placeholder={`Message @${agent ?? "main"}…`}
            className="w-full resize-none bg-transparent px-3 py-2 text-[15px] outline-none placeholder:text-muted-foreground"
          />
          <div className="flex items-center gap-2 px-1">
            <select value={agent ?? "main"} onChange={(e) => nav({ to: "/", search: { session, agent: e.target.value === "main" ? undefined : e.target.value } })}
              className="rounded-md border bg-background px-2 py-1 font-mono text-xs text-muted-foreground outline-none hover:text-foreground">
              {(agents.data ?? [{ name: "main", signature_emoji: "🦞", id: "main" }]).map((a) => (
                <option key={a.id} value={a.name}>{a.signature_emoji ?? "🤖"} {a.name}</option>
              ))}
            </select>
            <select value={model} onChange={(e) => setModel(e.target.value)} className="rounded-md border bg-background px-2 py-1 font-mono text-xs text-muted-foreground outline-none hover:text-foreground">
              {models.data?.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
            </select>
            {busy ? (
              <button onClick={stop} className="ml-auto grid size-8 place-items-center rounded-lg bg-secondary text-foreground hover:bg-muted" aria-label="Stop"><Square className="size-3.5 fill-current" /></button>
            ) : (
              <button onClick={send} disabled={!text.trim()} className="ml-auto grid size-8 place-items-center rounded-lg bg-primary text-primary-foreground transition disabled:opacity-30" aria-label="Send"><ArrowUp className="size-4" /></button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function Row({ item, onResolve }: { item: Item; onResolve: (ok: boolean) => void }) {
  const [open, setOpen] = useState(false);
  switch (item.kind) {
    case "user":
      return <div className="flex justify-end"><div className="max-w-[80%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-secondary px-4 py-2.5 text-[15px]">{item.text}</div></div>;
    case "assistant":
      return <div className={`whitespace-pre-wrap text-[15px] leading-relaxed ${item.live ? "caret" : ""}`}>{item.text}</div>;
    case "agent":
      return (
        <div className="flex items-center gap-2 pt-2 text-sm">
          <span>{item.emoji ?? "🤖"}</span><span className="font-semibold text-primary">@{item.name}</span>
          {item.model && <span className="rounded border px-1.5 font-mono text-[10px] text-muted-foreground">{item.model}</span>}
        </div>
      );
    case "notice":
      return <p className="border-l-2 border-primary/50 pl-3 font-mono text-xs text-muted-foreground">{item.text}</p>;
    case "tool":
      return (
        <div className="overflow-hidden rounded-lg border bg-rail font-mono text-xs">
          <button onClick={() => setOpen(!open)} className="flex w-full items-center gap-2 px-3 py-2 text-left text-muted-foreground hover:text-foreground">
            <ChevronRight className={`size-3 transition ${open ? "rotate-90" : ""}`} />
            <Wrench className="size-3 text-primary" />
            <span className="text-foreground">{item.name}</span>
            <span className="truncate opacity-60">{item.args}</span>
            <span className="ml-auto">
              {item.state === "running" ? <Loader2 className="size-3 animate-spin text-primary" /> : item.state === "ok" ? <Check className="size-3 text-success" /> : <X className="size-3 text-destructive" />}
            </span>
          </button>
          {open && (
            <div className="space-y-2 border-t px-3 py-2">
              {item.args && <pre className="overflow-x-auto whitespace-pre-wrap text-muted-foreground">{item.args}</pre>}
              {item.result && <pre className="overflow-x-auto whitespace-pre-wrap border-t pt-2 text-foreground">{item.result}</pre>}
            </div>
          )}
        </div>
      );
    case "approval":
      return (
        <div className="rounded-lg border border-warning/40 bg-warning/5 p-4">
          <div className="flex items-center gap-2 text-sm"><span className="size-2 rounded-full bg-warning" /> Approval needed for <span className="font-mono text-warning">{item.name}</span></div>
          {item.args && <pre className="mt-2 overflow-x-auto rounded bg-rail p-2 font-mono text-xs text-muted-foreground">{item.args}</pre>}
          {item.resolved ? (
            <p className="mt-3 font-mono text-xs text-muted-foreground">{item.resolved}</p>
          ) : (
            <div className="mt-3 flex gap-2">
              <button onClick={async () => { await api.resolveApproval(item.id, true); onResolve(true); }} className="rounded-md bg-primary px-3 py-1 text-xs font-medium text-primary-foreground">Approve</button>
              <button onClick={async () => { await api.resolveApproval(item.id, false); onResolve(false); }} className="rounded-md border px-3 py-1 text-xs">Deny</button>
            </div>
          )}
        </div>
      );
  }
}
