import { createFileRoute } from "@tanstack/react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Play, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { api, relTime } from "@/lib/api";
import { PageHeader } from "@/components/AppShell";

export const Route = createFileRoute("/jobs")({
  head: () => ({ meta: [
    { title: "Jobs · Clawhouse" },
    { name: "description", content: "Scheduled agent runs and workspace jobs in one place." },
    { property: "og:title", content: "Jobs · Clawhouse" },
    { property: "og:description", content: "Scheduled agent runs and workspace jobs in one place." },
  ] }),
  component: Jobs,
});

const BADGE: Record<string, string> = {
  success: "text-success border-success/40", failed: "text-destructive border-destructive/40",
  running: "text-primary border-primary/40", pending: "text-warning border-warning/40",
};

function Jobs() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["jobs"], queryFn: api.jobs, refetchInterval: 10000 });
  return (
    <div className="h-full overflow-y-auto">
      <PageHeader title="Jobs" subtitle="Cron schedules and workspace jobs." />
      <div className="mx-auto max-w-5xl px-8 py-6">
        {q.data?.databricks_error && <p className="mb-4 rounded-md border border-destructive/40 p-3 text-sm text-destructive">{q.data.databricks_error}</p>}
        <div className="overflow-hidden rounded-xl border">
          <table className="w-full text-sm">
            <thead className="bg-surface font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
              <tr><th className="px-4 py-2 text-left">Name</th><th className="px-4 py-2 text-left">Schedule</th><th className="px-4 py-2 text-left">Next</th><th className="px-4 py-2 text-left">Last run</th><th /></tr>
            </thead>
            <tbody className="divide-y">
              {q.data?.jobs.map((j) => (
                <tr key={j.id} className="hover:bg-surface">
                  <td className="px-4 py-3">
                    <div className="font-medium">{j.name}</div>
                    <div className="font-mono text-[11px] text-muted-foreground">{j.source}{j.agent_id ? ` · @${j.agent_id}` : ""}</div>
                  </td>
                  <td className="px-4 py-3"><div>{j.cron_human ?? "—"}</div><div className="font-mono text-[11px] text-muted-foreground">{j.cron}</div></td>
                  <td className="px-4 py-3 font-mono text-xs text-muted-foreground">{j.next_run_at ? relTime(j.next_run_at) : "—"}</td>
                  <td className="px-4 py-3">
                    {j.last_run ? <span className={`rounded border px-1.5 py-0.5 font-mono text-[11px] ${BADGE[j.last_run.status] ?? ""}`}>{j.last_run.status} · {relTime(j.last_run.started_at)}</span> : <span className="text-muted-foreground">—</span>}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex justify-end gap-2">
                      {j.can_run && <button aria-label="Run now" onClick={async () => { const r = await api.runJob(j.id); r.ok ? toast.success(`"${j.name}" started`) : toast.error("Could not start job"); }} className="rounded-md border p-1.5 text-muted-foreground hover:border-primary hover:text-primary"><Play className="size-3.5" /></button>}
                      {j.can_delete && <button aria-label="Delete" onClick={async () => { if (confirm(`Delete "${j.name}"?`)) { await api.deleteJob(j.id); qc.invalidateQueries({ queryKey: ["jobs"] }); } }} className="rounded-md border p-1.5 text-muted-foreground hover:border-destructive hover:text-destructive"><Trash2 className="size-3.5" /></button>}
                    </div>
                  </td>
                </tr>
              ))}
              {q.data?.jobs.length === 0 && <tr><td colSpan={5} className="px-4 py-8 text-center text-muted-foreground">No jobs yet.</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
