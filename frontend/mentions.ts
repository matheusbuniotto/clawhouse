/** `@` autocomplete for agents: pure ranking over the list `GET /api/agents` returns. */

export interface AgentOption {
  name: string;
  description?: string;
  signature_emoji?: string;
  is_platform?: boolean;
}

export interface Suggestion {
  label: string;
  insert_text: string;
  detail: string;
  kind: string;
}

/** Name-prefix matches first, then name or description substrings; case-insensitive. */
export function agentSuggestions(agents: AgentOption[], query: string): Suggestion[] {
  const q = query.trim().toLowerCase();
  const rank = (agent: AgentOption): number => {
    const name = agent.name.toLowerCase();
    if (!q || name.startsWith(q)) return 0;
    if (name.includes(q) || (agent.description ?? "").toLowerCase().includes(q)) return 1;
    return -1;
  };
  return agents
    .map((agent, index) => ({ agent, index, score: rank(agent) }))
    .filter((item) => item.score >= 0)
    .sort((a, b) => a.score - b.score || a.index - b.index)
    .map(({ agent }) => ({
      label: `${agent.signature_emoji ?? (agent.is_platform ? "🦀" : "🤖")} @${agent.name}`,
      insert_text: `@${agent.name}`,
      detail: agent.description ?? "",
      kind: "agent",
    }));
}

export const DEFAULT_SLASH_COMMANDS: Suggestion[] = [
  { label: "/compact", insert_text: "/compact", detail: "Compact conversation history", kind: "command" },
  { label: "/schedule", insert_text: "/schedule", detail: "Schedule recurring turn: cron or every <N>m", kind: "command" },
  { label: "/jobs", insert_text: "/jobs", detail: "View or run Lakeflow Jobs and schedules", kind: "command" },
  { label: "/model", insert_text: "/model", detail: "Switch active LLM model", kind: "command" },
  { label: "/reset", insert_text: "/reset", detail: "Start a fresh session", kind: "command" },
];

export function slashSuggestions(query: string, defaults: Suggestion[] = DEFAULT_SLASH_COMMANDS): Suggestion[] {
  const q = query.trim().toLowerCase();
  return defaults.filter((cmd) => {
    if (!q) return true;
    const id = cmd.insert_text.toLowerCase().replace(/^\//, "");
    const detail = cmd.detail.toLowerCase();
    return id.includes(q) || detail.includes(q);
  });
}

/** Local hits stay on top; the server adds further items without duplicating insert_text. */
export function mergeSuggestions(local: Suggestion[], remote: Suggestion[]): Suggestion[] {
  const localInserts = new Set(local.map((s) => s.insert_text));
  return [...local, ...remote.filter((item) => !localInserts.has(item.insert_text))];
}
