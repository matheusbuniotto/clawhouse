import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Plus, Trash2, MessageSquare } from "lucide-react";
import { toast } from "sonner";
import { api, relTime } from "@/lib/api";
import { PageHeader } from "@/components/AppShell";

export const Route = createFileRoute("/agents")({
  head: () => ({ meta: [
    { title: "Agents · Clawhouse" },
    { name: "description", content: "Your crew of agents — create, inspect and chat with each one." },
    { property: "og:title", content: "Agents · Clawhouse" },
    { property: "og:description", content: "Your crew of agents — create, inspect and chat with each one." },
  ] }),
  component: Agents,
});

const PRESETS = [
  { name: "chief_of_staff", emoji: "🧭", description: "Coordinates the others and is your single point of contact." },
  { name: "researcher", emoji: "🔎", description: "Digs through sources and reports back with citations." },
  { name: "engineer", emoji: "🛠️", description: "Reads and writes code, runs commands with approval." },
];

function Agents() {
  const qc = useQueryClient();
  const nav = useNavigate();
  const agents = useQuery({ queryKey: ["agents"], queryFn: api.agents });
  const [form, setForm] = useState<null | { name: string; emoji: string; description: string; system_prompt: string }>(null);

  const chat = async (name: string) => {
    const s = await api.createSession();
    nav({ to: "/", search: { session: s.id, agent: name === "main" ? undefined : name } });
  };

  return (
    <div className="h-full overflow-y-auto">
      <PageHeader title="Agents" subtitle="Each claw has its own prompt, model and memory."
        actions={<button onClick={() => setForm({ name: "", emoji: "🤖", description: "", system_prompt: "" })} className="flex items-center gap-2 rounded-lg bg-primary px-3 py-2 text-sm font-medium text-primary-foreground"><Plus className="size-4" /> New agent</button>} />
      <div className="mx-auto max-w-5xl px-8 py-6">
        {form && (
          <form className="mb-6 space-y-3 rounded-xl border bg-surface p-5 glow" onSubmit={async (e) => {
            e.preventDefault();
            try {
              await api.createAgent({ name: form.name, signature_emoji: form.emoji, description: form.description, system_prompt: form.system_prompt });
              setForm(null); qc.invalidateQueries({ queryKey: ["agents"] }); toast.success("Agent created");
            } catch { toast.error("Could not create agent"); }
          }}>
            <div className="flex flex-wrap gap-2">
              {PRESETS.map((p) => (
                <button type="button" key={p.name} onClick={() => setForm({ ...form, name: p.name, emoji: p.emoji, description: p.description })} className="rounded-full border px-3 py-1 text-xs text-muted-foreground hover:border-primary hover:text-foreground">{p.emoji} {p.name}</button>
              ))}
            </div>
            <div className="flex gap-2">
              <input value={form.emoji} onChange={(e) => setForm({ ...form, emoji: e.target.value })} className="w-14 rounded-md border bg-background px-2 py-2 text-center" />
              <input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="name" className="flex-1 rounded-md border bg-background px-3 py-2 font-mono text-sm outline-none focus:border-primary" />
            </div>
            <input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} placeholder="What does it do?" className="w-full rounded-md border bg-background px-3 py-2 text-sm outline-none focus:border-primary" />
            <textarea value={form.system_prompt} onChange={(e) => setForm({ ...form, system_prompt: e.target.value })} placeholder="System prompt" rows={4} className="w-full rounded-md border bg-background px-3 py-2 font-mono text-xs outline-none focus:border-primary" />
            <div className="flex justify-end gap-2">
              <button type="button" onClick={() => setForm(null)} className="rounded-md border px-3 py-1.5 text-sm">Cancel</button>
              <button className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground">Create</button>
            </div>
          </form>
        )}
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {agents.data?.map((a) => (
            <div key={a.id} className="group flex flex-col rounded-xl border bg-surface p-5 transition hover:border-primary/50">
              <div className="flex items-start justify-between">
                <span className="grid size-11 place-items-center rounded-xl bg-background text-2xl">{a.signature_emoji ?? (a.is_platform ? "🦞" : "🤖")}</span>
                {a.is_platform ? <span className="rounded border px-1.5 font-mono text-[10px] text-muted-foreground">platform</span> : (
                  <button aria-label="Delete agent" className="text-muted-foreground opacity-0 group-hover:opacity-100 hover:text-destructive"
                    onClick={async () => { if (confirm(`Delete @${a.name}?`)) { await api.deleteAgent(a.id); qc.invalidateQueries({ queryKey: ["agents"] }); } }}>
                    <Trash2 className="size-4" />
                  </button>
                )}
              </div>
              <h3 className="mt-4 font-mono font-medium">@{a.name}</h3>
              <p className="mt-1 flex-1 text-sm text-muted-foreground">{a.description || "No description."}</p>
              <div className="mt-4 flex items-center justify-between border-t pt-3 font-mono text-[11px] text-muted-foreground">
                <span>{a.model ?? "default"} · {relTime(a.last_active_at)}</span>
                <button onClick={() => chat(a.name)} className="flex items-center gap-1 text-primary hover:underline"><MessageSquare className="size-3" /> chat</button>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
