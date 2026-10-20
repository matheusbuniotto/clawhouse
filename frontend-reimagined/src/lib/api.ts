// API client for the Clawhouse backend. Falls back to an in-memory demo
// backend when the real server is unreachable (e.g. in the Lovable preview).
const BASE = (import.meta.env["VITE_API_BASE"] as string | undefined) ?? "";

export type RunState = "running" | "idle" | "ok" | "error" | "pending";
export interface Session { id: string; title: string; created_at: string; run_state?: RunState }
export interface Agent {
  id: string; name: string; description: string; system_prompt: string;
  signature_emoji?: string; is_platform?: boolean; model?: string;
  last_active_at?: string | null; last_activity?: string;
}
export interface Entry {
  role: "user" | "assistant" | "tool_call" | "tool_result" | "notice";
  content: string; tool_name: string | null; agent_id?: string | null; model?: string | null;
}
export interface Approval {
  id: string; session_id: string; tool_name: string; arguments: string;
  status: string; created_at: string; resolved_by: string | null;
}
export interface Job {
  id: string; source: "schedule" | "databricks"; name: string; agent_id: string | null;
  cron: string | null; cron_human: string | null; next_run_at: string | null;
  last_run: { status: string; started_at: string; run_url?: string | null } | null;
  can_run: boolean; can_delete: boolean;
}
export interface SandboxStatus {
  owner_id: string;
  workspace_path: string;
  backend: string;
  status: string;
  file_count: number;
}
export interface Status {
  auth: { user_id: string; token_present: boolean; auth_type: string };
  connection: { workspace_host: string | null; serving_endpoint: string | null; store_type: string };
  sessions: Session[];
  sandbox?: SandboxStatus | null;
}
export interface ModelOption { id: string; label: string; default: boolean }
export interface Question {
  id: string; session_id: string; question: string; options: string[];
  default: string | null; multi: boolean; status: string;
}
export interface Frame { event: string; data: Record<string, unknown> }

export class StreamStatusError extends Error {
  readonly status: number;
  constructor(status: number) {
    super(String(status));
    this.name = "StreamStatusError";
    this.status = status;
  }
}

let demo = false;
export const isDemo = () => demo;

async function call(path: string, init?: RequestInit): Promise<Response> {
  if (!demo) {
    try {
      const res = await fetch(BASE + path, init);
      const ct = res.headers.get("content-type") ?? "";
      if (ct.includes("json") || ct.includes("event-stream") || res.status === 204) return res;
    } catch { /* fall through */ }
    demo = true;
  }
  return mock(path, init);
}

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await call(path, init);
  if (!res.ok) throw new Error(`${res.status}`);
  return res.status === 204 ? (undefined as T) : res.json();
}
const post = (body?: unknown, method = "POST"): RequestInit => ({
  method, headers: { "content-type": "application/json" }, body: body ? JSON.stringify(body) : null,
});

export const api = {
  me: () => json<{ user_id: string }>("/api/me"),
  sessions: () => json<{ sessions: Session[] }>("/api/sessions").then((b) => b.sessions ?? []),
  session: (id: string) => json<Session>(`/api/sessions/${id}`),
  createSession: () => json<{ id: string }>("/api/sessions", post()),
  renameSession: (id: string, title: string) => json<unknown>(`/api/sessions/${id}`, post({ title }, "PATCH")),
  deleteSession: (id: string) => json<unknown>(`/api/sessions/${id}`, { method: "DELETE" }),
  transcript: (id: string) => json<{ entries?: Entry[]; run_state?: string }>(`/api/sessions/${id}/transcript`),
  cancel: (id: string) => call(`/api/sessions/${id}/cancel`, post()),
  search: (q: string) => json<{ results?: Session[] } | Session[]>(`/api/search?q=${encodeURIComponent(q)}`)
    .then((b) => (Array.isArray(b) ? b : b.results ?? [])),
  models: () => json<ModelOption[] | { models: ModelOption[] }>("/api/models").then((b) => (Array.isArray(b) ? b : b.models)),
  agents: () => json<Agent[]>("/api/agents"),
  createAgent: (a: Partial<Agent>) => json<Agent>("/api/agents", post(a)),
  deleteAgent: (id: string) => json<unknown>(`/api/agents/${encodeURIComponent(id)}`, { method: "DELETE" }),
  approvals: () => json<{ pending?: Approval[]; history?: Approval[] }>("/api/approvals"),
  questions: (sessionId: string) => json<Question[]>(`/api/sessions/${sessionId}/questions`),
  resolveApproval: (id: string, ok: boolean) => call(`/api/approvals/${id}/${ok ? "approve" : "deny"}`, post()),
  async *streamAnswer(id: string, selected: string[]): AsyncGenerator<Frame> {
    const res = await fetch(`${BASE}/api/questions/${encodeURIComponent(id)}/answer`, {
      method: "POST",
      headers: { Accept: "text/event-stream", "content-type": "application/json" },
      body: JSON.stringify({ selected }),
    });
    if (!res.ok) throw new StreamStatusError(res.status);
    yield* readFrames(res);
  },
  async *streamDecision(id: string, ok: boolean): AsyncGenerator<Frame> {
    const res = await fetch(`${BASE}/api/approvals/${encodeURIComponent(id)}/${ok ? "approve" : "deny"}`, {
      method: "POST",
      headers: { Accept: "text/event-stream" },
    });
    if (!res.ok) throw new StreamStatusError(res.status);
    yield* readFrames(res);
  },
  jobs: () => json<{ jobs: Job[]; databricks_error?: string | null }>("/api/jobs"),
  runJob: (id: string) => call(`/api/jobs/${encodeURIComponent(id)}/run`, post()),
  deleteJob: (id: string) => call(`/api/jobs/${encodeURIComponent(id)}`, { method: "DELETE" }),
  status: () => json<Status>("/api/status"),
  resetSandbox: () => call("/api/sandbox/reset", post()),
  async *turn(id: string, body: { message: string; model: string | null; agent: string | null }, signal: AbortSignal): AsyncGenerator<Frame> {
    const res = await call(`/api/sessions/${id}/turns`, { ...post(body), signal });
    if (!res.ok) {
      const b = await res.json().catch(() => ({}));
      yield { event: "error", data: { error: (b as { error?: string }).error ?? `Request failed (${res.status})` } };
      return;
    }
    yield* readFrames(res);
  },
};

export async function* readFrames(res: Response): AsyncGenerator<Frame> {
  if (!res.body) return;
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    const parts = buf.split("\n\n");
    buf = parts.pop() ?? "";
    for (const raw of parts) {
      if (!raw.trim()) continue;
      let event = "message";
      let data = "";
      for (const line of raw.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) data += line.slice(5).trim();
      }
      try { yield { event, data: data ? JSON.parse(data) as Record<string, unknown> : {} }; } catch { /* skip */ }
    }
  }
}

// ---------------- demo backend ----------------
const now = Date.now();
const iso = (ago: number) => new Date(now - ago).toISOString();
const db = {
  sessions: [
    { id: "s1", title: "Quarterly revenue breakdown", created_at: iso(3e5), run_state: "ok" as RunState },
    { id: "s2", title: "Refactor ingestion pipeline", created_at: iso(4e6), run_state: "pending" as RunState },
    { id: "s3", title: "Draft launch email", created_at: iso(9e7), run_state: "idle" as RunState },
    { id: "s4", title: "Investigate failing job #482", created_at: iso(4e8), run_state: "error" as RunState },
  ] as Session[],
  transcripts: {
    s1: [
      { role: "user", content: "Break down Q3 revenue by region.", tool_name: null },
      { role: "tool_call", content: '{"query":"SELECT region, SUM(amount) FROM sales WHERE q=3 GROUP BY 1"}', tool_name: "sql_query" },
      { role: "tool_result", content: "region | total\nNA     | 4.2M\nEMEA   | 2.9M\nAPAC   | 1.7M", tool_name: "sql_query" },
      { role: "assistant", content: "Q3 revenue totals **$8.8M**. North America leads at 4.2M (48%), followed by EMEA at 2.9M and APAC at 1.7M. APAC grew fastest quarter-over-quarter.", tool_name: null },
    ],
  } as Record<string, Entry[]>,
  agents: [
    { id: "main", name: "main", description: "The default claw. Talks to you, delegates to others.", system_prompt: "", signature_emoji: "🦞", is_platform: true, model: "claude-sonnet", last_active_at: iso(3e5), last_activity: "Answered revenue question" },
    { id: "analyst", name: "analyst", description: "Writes SQL, reads tables, builds charts.", system_prompt: "", signature_emoji: "📊", model: "gpt-5", last_active_at: iso(4e6), last_activity: "Ran sql_query" },
    { id: "writer", name: "writer", description: "Drafts copy in your voice.", system_prompt: "", signature_emoji: "✍️", model: "claude-sonnet", last_active_at: null },
  ] as Agent[],
  approvals: [
    { id: "a1", session_id: "s2", tool_name: "write_file", arguments: '{"path":"pipeline/ingest.py","bytes":2048}', status: "pending", created_at: iso(4e6), resolved_by: null },
    { id: "a2", session_id: "s1", tool_name: "sql_query", arguments: '{"query":"SELECT ..."}', status: "approved", created_at: iso(5e6), resolved_by: "you" },
  ] as Approval[],
  jobs: [
    { id: "j1", source: "schedule", name: "Daily KPI digest", agent_id: "analyst", cron: "0 8 * * *", cron_human: "Every day at 08:00", next_run_at: new Date(now + 3.6e7).toISOString(), last_run: { status: "success", started_at: iso(5e7) }, can_run: true, can_delete: true },
    { id: "j2", source: "databricks", name: "etl_orders_nightly", agent_id: null, cron: "0 2 * * *", cron_human: "Every night at 02:00", next_run_at: new Date(now + 1.2e7).toISOString(), last_run: { status: "failed", started_at: iso(8e7) }, can_run: true, can_delete: false },
  ] as Job[],
};
const r = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status, headers: { "content-type": "application/json" } });
const wait = (ms: number) => new Promise((res) => setTimeout(res, ms));

async function mock(path: string, init?: RequestInit): Promise<Response> {
  await wait(120);
  const m = init?.method ?? "GET";
  const body = init?.body ? JSON.parse(init.body as string) : {};
  const seg = (path.split("?")[0] ?? "").split("/").filter(Boolean).slice(1);
  const [a, id, sub] = seg;
  if (a === "me") return r({ user_id: "you@clawhouse.dev" });
  if (a === "models") return r([{ id: "claude-sonnet", label: "Claude Sonnet", default: true }, { id: "gpt-5", label: "GPT-5", default: false }]);
  if (a === "search") {
    const q = new URLSearchParams(path.split("?")[1]).get("q")?.toLowerCase() ?? "";
    return r(db.sessions.filter((s) => s.title.toLowerCase().includes(q)));
  }
  if (a === "sessions") {
    if (!id && m === "POST") { const s = { id: "s" + Date.now(), title: "", created_at: new Date().toISOString(), run_state: "idle" as RunState }; db.sessions.unshift(s); return r(s); }
    if (!id) return r({ sessions: db.sessions });
    const s = db.sessions.find((x) => x.id === id);
    if (!sub) {
      if (m === "PATCH" && s) s.title = body.title;
      if (m === "DELETE") db.sessions = db.sessions.filter((x) => x.id !== id);
      return s ? r(s) : r({ error: "not found" }, 404);
    }
    if (sub === "transcript") return r({ entries: db.transcripts[id] ?? [], run_state: "idle" });
    if (sub === "questions") return r([]);
    if (sub === "cancel") return r({});
    if (sub === "turns") return mockTurn(id, body.message, body.agent);
  }
  if (a === "agents") {
    if (m === "POST") { const ag = { ...body, id: body.name }; db.agents.push(ag); return r(ag); }
    if (m === "DELETE") { db.agents = db.agents.filter((x) => x.id !== id); return r({}); }
    return r(db.agents);
  }
  if (a === "approvals") {
    if (id) { const ap = db.approvals.find((x) => x.id === id); if (ap) { ap.status = sub === "approve" ? "approved" : "denied"; ap.resolved_by = "you"; } return r({}); }
    return r({ pending: db.approvals.filter((x) => x.status === "pending"), history: db.approvals.filter((x) => x.status !== "pending") });
  }
  if (a === "jobs") {
    if (m === "DELETE") db.jobs = db.jobs.filter((x) => x.id !== id);
    return r({ jobs: db.jobs });
  }
  if (a === "status") return r({
    auth: { user_id: "you@clawhouse.dev", token_present: true, auth_type: "demo" },
    connection: { workspace_host: "demo.local", serving_endpoint: "claude-sonnet", store_type: "memory" },
    sessions: db.sessions,
    sandbox: {
      owner_id: "you@clawhouse.dev",
      workspace_path: "/Workspace/demo/sandbox",
      backend: "databricks_python_exec",
      status: "ready",
      file_count: 2,
    },
  });
  if (a === "sandbox") {
    if (id === "reset" && m === "POST") {
      return r({
        owner_id: "you@clawhouse.dev",
        workspace_path: "/Workspace/demo/sandbox",
        backend: "databricks_python_exec",
        status: "ready",
        file_count: 0,
      });
    }
    return r({
      owner_id: "you@clawhouse.dev",
      workspace_path: "/Workspace/demo/sandbox",
      backend: "databricks_python_exec",
      status: "ready",
      file_count: 2,
    });
  }
  return r({ error: "not found" }, 404);
}

function mockTurn(id: string, message: string, agent: string | null): Response {
  const s = db.sessions.find((x) => x.id === id);
  if (s && !s.title) s.title = message.slice(0, 48);
  const ag = db.agents.find((x) => x.name === (agent ?? "main")) ?? db.agents[0]!;
  const reply = `Demo mode — no backend is connected, so this is a simulated reply from @${ag.name}. Point VITE_API_BASE at your Clawhouse server and real turns will stream here.`;
  const enc = new TextEncoder();
  const stream = new ReadableStream({
    async start(c) {
      const send = (event: string, data: unknown) => c.enqueue(enc.encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`));
      send("agent", { agent_id: ag.id, name: ag.name, emoji: ag.signature_emoji, model: ag.model });
      await wait(400);
      send("tool_call", { name: "recall_memory", arguments: JSON.stringify({ query: message }) });
      await wait(500);
      send("tool_result", { name: "recall_memory", content: "3 related notes found" });
      for (const w of reply.split(/(\s+)/)) { await wait(25); send("token", { text: w }); }
      send("usage", { input_tokens: 1840, output_tokens: 62, context_window: 200000 });
      send("done", { reply, status: "ok" });
      const t = (db.transcripts[id] ??= []);
      t.push({ role: "user", content: message, tool_name: null }, { role: "assistant", content: reply, tool_name: null });
      c.close();
    },
  });
  return new Response(stream, { headers: { "content-type": "text/event-stream" } });
}

export function relTime(isoStr: string | null | undefined): string {
  if (!isoStr) return "never";
  const d = (Date.now() - new Date(isoStr).getTime()) / 1000;
  const f = Math.abs(d);
  const v = f < 60 ? "just now" : f < 3600 ? `${Math.round(f / 60)}m` : f < 86400 ? `${Math.round(f / 3600)}h` : `${Math.round(f / 86400)}d`;
  if (v === "just now") return v;
  return d < 0 ? `in ${v}` : `${v} ago`;
}
