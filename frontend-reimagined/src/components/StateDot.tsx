import type { RunState } from "@/lib/api";

const CLS: Record<RunState, string> = {
  running: "bg-primary animate-pulse",
  ok: "bg-success",
  error: "bg-destructive",
  pending: "bg-warning animate-pulse",
  idle: "bg-muted-foreground/40",
};

export function StateDot({ state }: { state?: RunState | string | undefined }) {
  const c = CLS[(state as RunState) ?? "idle"] ?? CLS.idle;
  return <span className={`inline-block size-1.5 shrink-0 rounded-full ${c}`} title={state ?? "idle"} />;
}
