import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, isDemo, relTime } from "@/lib/api";
import { PageHeader } from "@/components/AppShell";
import { StateDot } from "@/components/StateDot";

export const Route = createFileRoute("/status")({
  head: () => ({ meta: [
    { title: "Status · Clawhouse" },
    { name: "description", content: "Connection, auth and live session health for your workspace." },
    { property: "og:title", content: "Status · Clawhouse" },
    { property: "og:description", content: "Connection, auth and live session health for your workspace." },
  ] }),
  component: StatusPage,
});

function StatusPage() {
  const qc = useQueryClient();
  const [resetting, setResetting] = useState(false);
  const q = useQuery({ queryKey: ["status"], queryFn: api.status, refetchInterval: 5000 });
  const s = q.data;
  const sandbox = s?.sandbox;
  const fields: [string, string | undefined | null, (boolean | undefined)?][] = [
    ["User", s?.auth.user_id], ["Auth mode", s?.auth.auth_type], ["Token", s ? (s.auth.token_present ? "present" : "missing") : undefined, s?.auth.token_present],
    ["Workspace", s?.connection.workspace_host], ["Model endpoint", s?.connection.serving_endpoint], ["Store", s?.connection.store_type],
  ];
  return (
    <div className="h-full overflow-y-auto">
      <PageHeader title="Status" subtitle={isDemo() ? "Running against the built-in demo backend." : "Live gateway health."} />
      <div className="mx-auto max-w-5xl space-y-8 px-8 py-6">
        <div className="grid gap-px overflow-hidden rounded-xl border bg-border sm:grid-cols-3">
          {fields.map(([k, v, ok]) => (
            <div key={k} className="bg-surface p-4">
              <div className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">{k}</div>
              <div className={`mt-1 truncate font-mono text-sm ${ok === false ? "text-destructive" : ok ? "text-success" : ""}`}>{v ?? "—"}</div>
            </div>
          ))}
        </div>
        {sandbox && (
          <section>
            <h2 className="mb-3 font-mono text-xs uppercase tracking-widest text-muted-foreground">User Sandbox</h2>
            <div className="rounded-xl border bg-surface p-4">
              <dl className="grid gap-3 sm:grid-cols-2">
                <div>
                  <dt className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">Status</dt>
                  <dd id="stat-sandbox-status" className="mt-1 font-mono text-sm">{sandbox.status}</dd>
                </div>
                <div>
                  <dt className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">Backend</dt>
                  <dd id="stat-sandbox-backend" className="mt-1 font-mono text-sm">{sandbox.backend}</dd>
                </div>
                <div className="sm:col-span-2">
                  <dt className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">Workspace path</dt>
                  <dd id="stat-sandbox-path" className="mt-1 truncate font-mono text-sm">{sandbox.workspace_path}</dd>
                </div>
                <div>
                  <dt className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">Files</dt>
                  <dd id="stat-sandbox-files" className="mt-1 font-mono text-sm">{sandbox.file_count} files</dd>
                </div>
              </dl>
              <button
                id="btn-reset-sandbox"
                type="button"
                disabled={resetting}
                className="mt-4 text-sm text-primary hover:underline disabled:opacity-50"
                onClick={async () => {
                  setResetting(true);
                  try {
                    await api.resetSandbox();
                    await qc.invalidateQueries({ queryKey: ["status"] });
                  } finally {
                    setResetting(false);
                  }
                }}
              >
                Reset sandbox
              </button>
            </div>
          </section>
        )}
        <section>
          <h2 className="mb-3 font-mono text-xs uppercase tracking-widest text-muted-foreground">Sessions</h2>
          <ul className="divide-y rounded-xl border">
            {s?.sessions.map((x) => (
              <li key={x.id} className="flex items-center gap-3 px-4 py-2.5 text-sm">
                <StateDot state={x.run_state} />
                <Link to="/" search={{ session: x.id }} className="flex-1 truncate hover:text-primary">{x.title || "Untitled"}</Link>
                <span className="font-mono text-xs text-muted-foreground">{x.run_state}</span>
                <span className="w-16 text-right font-mono text-xs text-muted-foreground">{relTime(x.created_at)}</span>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </div>
  );
}
