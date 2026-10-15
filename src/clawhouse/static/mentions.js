/** `@` autocomplete for agents: pure ranking over the list `GET /api/agents` returns. */
/** Name-prefix matches first, then name or description substrings; case-insensitive. */
export function agentSuggestions(agents, query) {
    const q = query.trim().toLowerCase();
    const rank = (agent) => {
        const name = agent.name.toLowerCase();
        if (!q || name.startsWith(q))
            return 0;
        if (name.includes(q) || (agent.description ?? "").toLowerCase().includes(q))
            return 1;
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
/** Local agent hits stay on top; the server adds files and tables, never a second agent row. */
export function mergeSuggestions(local, remote) {
    return [...local, ...remote.filter((item) => item.kind !== "agent")];
}
