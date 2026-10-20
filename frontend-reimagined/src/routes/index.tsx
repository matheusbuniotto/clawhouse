import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { ArrowUp, Loader2, Square } from "lucide-react";
import { z } from "zod";
import { ActivityList } from "@/components/chat-activity";
import {
  applyFrame,
  assembleSession,
  markApprovalError,
  markApprovalResolved,
  markQuestionAnswered,
  markQuestionError,
  type Item,
} from "@/lib/chat-activity";
import { api, StreamStatusError, type Frame } from "@/lib/api";

export const Route = createFileRoute("/")({
  validateSearch: z.object({ session: z.string().optional(), agent: z.string().optional() }),
  head: () => ({
    meta: [
      { title: "Chat · Clawhouse" },
      {
        name: "description",
        content: "Talk to your agents, watch tools run, approve actions inline.",
      },
      { property: "og:title", content: "Chat · Clawhouse" },
      {
        property: "og:description",
        content: "Talk to your agents, watch tools run, approve actions inline.",
      },
    ],
  }),
  component: Chat,
});

function usageFrom(data: Record<string, unknown>): { in: number; win: number | null } {
  return { in: Number(data.input_tokens) || 0, win: (data.context_window as number) ?? null };
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
  const meta = useQuery({
    queryKey: ["session", session],
    queryFn: () => api.session(session!),
    enabled: !!session,
  });

  useEffect(() => {
    if (!model && models.data?.length)
      setModel((models.data.find((m) => m.default) ?? models.data[0]!).id);
  }, [models.data, model]);

  useEffect(() => {
    setItems([]);
    setUsage(null);
    if (!session) return;
    let cancel = false;
    Promise.all([api.transcript(session), api.questions(session), api.approvals()])
      .then(([transcript, questions, approvals]) => {
        if (!cancel)
          setItems(
            assembleSession(transcript.entries ?? [], questions, approvals.pending ?? [], session),
          );
      })
      .catch(() => {});
    return () => {
      cancel = true;
    };
  }, [session]);

  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: "smooth" });
  }, [items]);

  const update = (fn: (prev: Item[]) => Item[]) => setItems(fn);
  const waitingForAnswer = items.some((item) => item.kind === "question" && item.chosen === null);
  const waitingForApproval = items.some(
    (item) => item.kind === "approval" && item.resolved === null,
  );
  const blocked = waitingForAnswer || waitingForApproval;

  async function consume(frames: AsyncGenerator<Frame>) {
    for await (const frame of frames) {
      if (frame.event === "usage") setUsage(usageFrom(frame.data));
      else update((prev) => applyFrame(prev, frame.event, frame.data));
    }
  }

  async function send() {
    const msg = text.trim();
    if (!msg || busy || blocked) return;
    let sid = session;
    if (!sid) {
      sid = (await api.createSession()).id;
      nav({ to: "/", search: { session: sid, agent }, replace: true });
    }
    setText("");
    setBusy(true);
    update((prev) => [...prev, { kind: "user", text: msg }]);
    abort.current = new AbortController();
    try {
      await consume(
        api.turn(
          sid,
          { message: msg, model: model || null, agent: agent ?? null },
          abort.current.signal,
        ),
      );
    } catch (e) {
      if ((e as Error).name !== "AbortError")
        update((prev) => [...prev, { kind: "notice", text: "Connection lost." }]);
    } finally {
      setBusy(false);
      qc.invalidateQueries({ queryKey: ["sessions"] });
      qc.invalidateQueries({ queryKey: ["session", sid] });
    }
  }

  async function answer(id: string, selected: string[]) {
    try {
      await consume(api.streamAnswer(id, selected));
      update((prev) => markQuestionAnswered(prev, id, selected));
    } catch (e) {
      const message =
        e instanceof StreamStatusError
          ? "Could not send the answer."
          : "Network error while sending the answer.";
      update((prev) => markQuestionError(prev, id, message));
    }
  }

  async function resolve(id: string, ok: boolean) {
    try {
      await consume(api.streamDecision(id, ok));
      update((prev) => markApprovalResolved(prev, id, ok ? "approved" : "denied"));
    } catch (e) {
      const network = !(e instanceof StreamStatusError);
      const message = ok
        ? network
          ? "Network error while approving tool call."
          : "Failed to approve tool call."
        : network
          ? "Network error while denying tool call."
          : "Failed to deny tool call.";
      update((prev) => markApprovalError(prev, id, message));
    }
  }

  function stop() {
    abort.current?.abort();
    if (session) api.cancel(session);
    update((prev) => [
      ...prev.map((item) =>
        item.kind === "assistant" && item.live ? { ...item, live: false } : item,
      ),
      { kind: "notice", text: "Stopped." },
    ]);
  }

  const activeAgent = agents.data?.find((a) => a.name === (agent ?? "main"));
  const empty = items.length === 0;
  const placeholder = waitingForAnswer
    ? "Waiting for your answer."
    : waitingForApproval
      ? "Waiting for approval."
      : `Message @${agent ?? "main"}…`;

  return (
    <div className="flex h-full flex-col">
      <header className="flex h-14 shrink-0 items-center gap-3 border-b px-6 pl-14 md:pl-6">
        <span className="truncate font-medium">
          {meta.data?.title || (session ? "Untitled" : "New session")}
        </span>
        {usage && (
          <span className="ml-auto font-mono text-[11px] text-muted-foreground">
            ctx {usage.in.toLocaleString()}
            {usage.win ? ` / ${(usage.win / 1000).toFixed(0)}k` : ""}
          </span>
        )}
      </header>

      <div ref={scroller} className="flex-1 overflow-y-auto">
        {empty ? (
          <div className="grid h-full place-items-center grid-bg">
            <div className="text-center">
              <div className="mx-auto grid size-16 place-items-center rounded-2xl bg-surface text-4xl glow">
                {activeAgent?.signature_emoji ?? "🦞"}
              </div>
              <h2 className="mt-6 text-3xl font-semibold tracking-tight">
                What should we claw at today?
              </h2>
              <p className="mt-2 text-sm text-muted-foreground">
                Ask anything. Mention <span className="font-mono text-primary">@agent</span> to hand
                off.
              </p>
            </div>
          </div>
        ) : (
          <div className="mx-auto min-w-0 max-w-3xl space-y-5 px-4 py-6 sm:px-6 sm:py-8">
            <ActivityList items={items} onAnswer={answer} onResolve={resolve} />
            {busy && !items.some((item) => item.kind === "assistant" && item.live) && (
              <div className="flex items-center gap-2 font-mono text-xs text-muted-foreground">
                <Loader2 className="size-3 animate-spin text-primary" /> thinking…
              </div>
            )}
          </div>
        )}
      </div>

      <div className="shrink-0 px-6 pb-6">
        <div className="mx-auto max-w-3xl rounded-2xl border bg-surface p-2 transition focus-within:glow">
          <textarea
            value={text}
            disabled={blocked}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void send();
              }
            }}
            rows={Math.min(8, Math.max(2, text.split("\n").length))}
            placeholder={placeholder}
            className="w-full resize-none bg-transparent px-3 py-2 text-[15px] outline-none placeholder:text-muted-foreground disabled:opacity-60"
          />
          <div className="flex items-center gap-2 px-1">
            <select
              value={agent ?? "main"}
              onChange={(e) =>
                nav({
                  to: "/",
                  search: {
                    session,
                    agent: e.target.value === "main" ? undefined : e.target.value,
                  },
                })
              }
              className="rounded-md border bg-background px-2 py-1 font-mono text-xs text-muted-foreground outline-none hover:text-foreground"
            >
              {(agents.data ?? [{ name: "main", signature_emoji: "🦞", id: "main" }]).map((a) => (
                <option key={a.id} value={a.name}>
                  {a.signature_emoji ?? "🤖"} {a.name}
                </option>
              ))}
            </select>
            <select
              value={model}
              onChange={(e) => setModel(e.target.value)}
              className="rounded-md border bg-background px-2 py-1 font-mono text-xs text-muted-foreground outline-none hover:text-foreground"
            >
              {models.data?.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.label}
                </option>
              ))}
            </select>
            {busy ? (
              <button
                onClick={stop}
                className="ml-auto grid size-8 place-items-center rounded-lg bg-secondary text-foreground hover:bg-muted"
                aria-label="Stop"
              >
                <Square className="size-3.5 fill-current" />
              </button>
            ) : (
              <button
                onClick={() => void send()}
                disabled={blocked || !text.trim()}
                className="ml-auto grid size-8 place-items-center rounded-lg bg-primary text-primary-foreground transition disabled:opacity-30"
                aria-label="Send message"
              >
                <ArrowUp className="size-4" />
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
