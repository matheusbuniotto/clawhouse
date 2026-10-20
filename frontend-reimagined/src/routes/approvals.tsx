import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, relTime, type Approval } from "@/lib/api";
import { PageHeader } from "@/components/AppShell";

export const Route = createFileRoute("/approvals")({
  head: () => ({ meta: [
    { title: "Approvals · Clawhouse" },
    { name: "description", content: "Review and approve the actions your agents want to take." },
    { property: "og:title", content: "Approvals · Clawhouse" },
    { property: "og:description", content: "Review and approve the actions your agents want to take." },
  ] }),
  component: Approvals,
});

function Card({ a, onAct }: { a: Approval; onAct?: (ok: boolean) => void }) {
  return (
    <div className={`rounded-xl border p-4 ${onAct ? "border-warning/40 bg-warning/5" : "bg-surface"}`}>
      <div className="flex items-center gap-2 text-sm">
        <span className="font-mono text-foreground">{a.tool_name}</span>
        <Link to="/" search={{ session: a.session_id }} className="font-mono text-xs text-muted-foreground hover:text-primary">session ↗</Link>
        <span className="ml-auto font-mono text-xs text-muted-foreground">{relTime(a.created_at)}</span>
      </div>
      <pre className="mt-2 overflow-x-auto rounded-md bg-rail p-3 font-mono text-xs text-muted-foreground">{a.arguments}</pre>
      {onAct ? (
        <div className="mt-3 flex gap-2">
          <button onClick={() => onAct(true)} className="rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground">Approve</button>
          <button onClick={() => onAct(false)} className="rounded-md border px-3 py-1.5 text-xs">Deny</button>
        </div>
      ) : (
        <p className={`mt-2 font-mono text-xs ${a.status === "approved" ? "text-success" : "text-destructive"}`}>{a.status}{a.resolved_by ? ` by ${a.resolved_by}` : ""}</p>
      )}
    </div>
  );
}

function Approvals() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["approvals"], queryFn: api.approvals, refetchInterval: 3000 });
  const act = async (id: string, ok: boolean) => { await api.resolveApproval(id, ok); qc.invalidateQueries({ queryKey: ["approvals"] }); };
  const pending = q.data?.pending ?? [];
  return (
    <div className="h-full overflow-y-auto">
      <PageHeader title="Approvals" subtitle="Nothing risky runs without your say-so." />
      <div className="mx-auto max-w-3xl space-y-8 px-8 py-6">
        <section>
          <h2 className="mb-3 font-mono text-xs uppercase tracking-widest text-muted-foreground">Pending · {pending.length}</h2>
          <div className="space-y-3">
            {pending.map((a) => <Card key={a.id} a={a} onAct={(ok) => act(a.id, ok)} />)}
            {pending.length === 0 && <p className="rounded-xl border border-dashed p-6 text-center text-sm text-muted-foreground">All clear.</p>}
          </div>
        </section>
        <section>
          <h2 className="mb-3 font-mono text-xs uppercase tracking-widest text-muted-foreground">History</h2>
          <div className="space-y-3">{q.data?.history?.map((a) => <Card key={a.id} a={a} />)}</div>
        </section>
      </div>
    </div>
  );
}
