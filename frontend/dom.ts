/** Shared DOM helpers for the shell and the screen modules. */

/**
 * The activity states the UI renders: run states (`running`/`idle`/`error`)
 * and tool outcomes (`running`/`ok`/`error`). One union so the rail, the
 * status badges, and the tool rows agree on the vocabulary.
 */
export type ActivityState = "running" | "idle" | "ok" | "error";

export function isRunning(state: ActivityState | string | null | undefined): boolean {
  return state === "running";
}

export function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  className?: string,
  text?: string,
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

export function relativeTime(iso: string, now: number = Date.now()): string {
  const seconds = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  if (seconds < 45) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  if (days < 7) return `${days}d ago`;
  return new Date(iso).toLocaleDateString();
}
