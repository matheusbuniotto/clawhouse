import { Link, useNavigate, useRouterState } from "@tanstack/react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { Activity, Bot, CalendarClock, MessageSquare, Plus, Search, ShieldCheck, History, PanelLeftClose, PanelLeft } from "lucide-react";
import { api, isDemo, type Session } from "@/lib/api";
import { StateDot } from "./StateDot";

const NAV = [
  { to: "/", label: "Chat", icon: MessageSquare },
  { to: "/sessions", label: "Sessions", icon: History },
  { to: "/agents", label: "Agents", icon: Bot },
  { to: "/approvals", label: "Approvals", icon: ShieldCheck },
  { to: "/jobs", label: "Jobs", icon: CalendarClock },
  { to: "/status", label: "Status", icon: Activity },
] as const;

function group(iso: string) {
  const d = Math.floor((Date.now() - new Date(iso).getTime()) / 864e5);
  return d <= 0 ? "Today" : d === 1 ? "Yesterday" : d < 7 ? "This week" : "Earlier";
}

export function AppShell({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(true);
  const [q, setQ] = useState("");
  const nav = useNavigate();
  const qc = useQueryClient();
  const loc = useRouterState({ select: (s) => s.location });
  const current = (loc.search as { session?: string }).session;
  const sessions = useQuery({ queryKey: ["sessions"], queryFn: api.sessions, refetchInterval: 5000 });
  const me = useQuery({ queryKey: ["me"], queryFn: api.me });
  const pending = useQuery({ queryKey: ["approvals"], queryFn: api.approvals, refetchInterval: 5000 });

  const newChat = async () => {
    const s = await api.createSession();
    await qc.invalidateQueries({ queryKey: ["sessions"] });
    nav({ to: "/", search: { session: s.id } });
  };

  const list = (sessions.data ?? []).filter((s) => (s.title || "Untitled").toLowerCase().includes(q.toLowerCase()));
  const groups = list.reduce<Record<string, Session[]>>((acc, s) => ((acc[group(s.created_at)] ??= []).push(s), acc), {});
  const pendingCount = pending.data?.pending?.length ?? 0;

  return (
    <div className="flex h-screen overflow-hidden">
      {open && (
        <aside className="flex w-72 shrink-0 flex-col border-r bg-rail">
          <div className="flex items-center justify-between px-4 pt-4 pb-3">
            <Link to="/" className="flex items-center gap-2">
              <span className="grid size-8 place-items-center rounded-lg bg-primary text-lg glow">🦞</span>
              <span className="font-semibold tracking-tight">Clawhouse</span>
            </Link>
            <button onClick={() => setOpen(false)} className="rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground" aria-label="Collapse sidebar">
              <PanelLeftClose className="size-4" />
            </button>
          </div>
          <div className="px-3">
            <button onClick={newChat} className="flex w-full items-center justify-center gap-2 rounded-lg bg-primary px-3 py-2 text-sm font-medium text-primary-foreground transition hover:brightness-110">
              <Plus className="size-4" /> New session
            </button>
          </div>
          <nav className="mt-3 space-y-0.5 px-2">
            {NAV.map(({ to, label, icon: Icon }) => {
              const active = loc.pathname === to;
              return (
                <Link key={to} to={to} className={`flex items-center gap-3 rounded-md px-3 py-1.5 text-sm transition ${active ? "bg-accent text-accent-foreground" : "text-muted-foreground hover:bg-muted hover:text-foreground"}`}>
                  <Icon className={`size-4 ${active ? "text-primary" : ""}`} />
                  {label}
                  {label === "Approvals" && pendingCount > 0 && (
                    <span className="ml-auto rounded-full bg-primary px-1.5 font-mono text-[10px] text-primary-foreground">{pendingCount}</span>
                  )}
                </Link>
              );
            })}
          </nav>
          <div className="mx-3 mt-4 flex items-center gap-2 rounded-md border bg-surface px-2.5 py-1.5">
            <Search className="size-3.5 text-muted-foreground" />
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Filter sessions" className="w-full bg-transparent text-sm outline-none placeholder:text-muted-foreground" />
          </div>
          <div className="mt-2 flex-1 overflow-y-auto px-2 pb-4">
            {Object.entries(groups).map(([g, items]) => (
              <div key={g} className="mt-3">
                <div className="px-3 pb-1 font-mono text-[10px] uppercase tracking-widest text-muted-foreground">{g}</div>
                {items.map((s) => (
                  <Link key={s.id} to="/" search={{ session: s.id }} className={`group flex items-center gap-2 rounded-md px-3 py-1.5 text-sm ${current === s.id ? "bg-accent text-accent-foreground" : "text-muted-foreground hover:bg-muted hover:text-foreground"}`}>
                    <StateDot state={s.run_state} />
                    <span className="truncate">{s.title || "Untitled"}</span>
                  </Link>
                ))}
              </div>
            ))}
            {list.length === 0 && <p className="px-3 pt-4 text-xs text-muted-foreground">No sessions yet.</p>}
          </div>
          <div className="flex items-center gap-2 border-t px-4 py-3 text-xs text-muted-foreground">
            <span className="grid size-6 place-items-center rounded-full bg-secondary font-mono text-[10px] text-foreground">
              {(me.data?.user_id ?? "?").slice(0, 2).toUpperCase()}
            </span>
            <span className="truncate">{me.data?.user_id ?? "Not signed in"}</span>
            {isDemo() && <span className="ml-auto rounded border border-warning/40 px-1.5 font-mono text-[10px] text-warning">DEMO</span>}
          </div>
        </aside>
      )}
      <main className="relative flex min-w-0 flex-1 flex-col">
        {!open && (
          <button onClick={() => setOpen(true)} className="absolute top-3 left-3 z-10 rounded-md border bg-surface p-1.5 text-muted-foreground hover:text-foreground" aria-label="Expand sidebar">
            <PanelLeft className="size-4" />
          </button>
        )}
        {children}
      </main>
    </div>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  return (
    <header className="flex items-end justify-between gap-4 border-b px-8 py-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-muted-foreground">{subtitle}</p>}
      </div>
      {actions}
    </header>
  );
}
