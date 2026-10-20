import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Pencil, Search, Trash2 } from "lucide-react";
import { api, relTime } from "@/lib/api";
import { PageHeader } from "@/components/AppShell";
import { StateDot } from "@/components/StateDot";

export const Route = createFileRoute("/sessions")({
  head: () => ({ meta: [
    { title: "Sessions · Clawhouse" },
    { name: "description", content: "Search, rename and clean up past agent sessions." },
    { property: "og:title", content: "Sessions · Clawhouse" },
    { property: "og:description", content: "Search, rename and clean up past agent sessions." },
  ] }),
  component: Sessions,
});

function Sessions() {
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const all = useQuery({ queryKey: ["sessions"], queryFn: api.sessions });
  const found = useQuery({ queryKey: ["search", q], queryFn: () => api.search(q), enabled: q.length > 1 });
  const rows = q.length > 1 ? found.data ?? [] : all.data ?? [];
  const refresh = () => qc.invalidateQueries({ queryKey: ["sessions"] });

  return (
    <div className="h-full overflow-y-auto">
      <PageHeader title="Sessions" subtitle={`${all.data?.length ?? 0} conversations`} />
      <div className="mx-auto max-w-4xl px-8 py-6">
        <div className="flex items-center gap-2 rounded-lg border bg-surface px-3 py-2">
          <Search className="size-4 text-muted-foreground" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search across all transcripts…" className="w-full bg-transparent text-sm outline-none" />
        </div>
        <ul className="mt-4 divide-y rounded-lg border">
          {rows.map((s) => (
            <li key={s.id} className="group flex items-center gap-3 px-4 py-3 hover:bg-surface">
              <StateDot state={s.run_state} />
              <Link to="/" search={{ session: s.id }} className="flex-1 truncate text-sm">{s.title || "Untitled"}</Link>
              <span className="font-mono text-xs text-muted-foreground">{relTime(s.created_at)}</span>
              <button aria-label="Rename" className="text-muted-foreground opacity-0 group-hover:opacity-100 hover:text-foreground"
                onClick={async () => { const t = prompt("Rename session", s.title); if (t) { await api.renameSession(s.id, t); refresh(); } }}>
                <Pencil className="size-3.5" />
              </button>
              <button aria-label="Delete" className="text-muted-foreground opacity-0 group-hover:opacity-100 hover:text-destructive"
                onClick={async () => { if (confirm("Delete this session?")) { await api.deleteSession(s.id); refresh(); } }}>
                <Trash2 className="size-3.5" />
              </button>
            </li>
          ))}
          {rows.length === 0 && <li className="px-4 py-8 text-center text-sm text-muted-foreground">Nothing here.</li>}
        </ul>
      </div>
    </div>
  );
}
