import { el } from "./dom.js";
export function mount(root, ctx) {
    let selectedAgentName = "main";
    const pickerSection = el("section", "agent-picker-section");
    const pickerHeading = el("h2", "agent-picker-heading", "Choose Agent");
    const agentCards = el("div", "agent-cards-grid");
    const manageLink = el("a", "manage-agents-link", "Gerenciar ou criar agentes →");
    manageLink.href = "/agents";
    manageLink.setAttribute("data-nav", "");
    pickerSection.append(pickerHeading, agentCards, manageLink);
    root.append(pickerSection);
    const form = document.createElement("form");
    form.id = "start";
    form.className = "start";
    const startDesc = el("p", "agent", "Active: 🦀 main · platform workspace");
    startDesc.id = "active-agent-desc";
    form.append(startDesc);
    const button = el("button", "", "Start session");
    button.type = "submit";
    form.append(button);
    const statusLine = el("p", "status");
    statusLine.id = "status";
    statusLine.setAttribute("role", "status");
    form.append(statusLine);
    root.append(form);
    function renderCards(agents) {
        agentCards.replaceChildren();
        for (const ag of agents) {
            const card = el("div", `agent-card${ag.name === selectedAgentName ? " selected" : ""}`);
            const header = el("div", "agent-card-header");
            const emojiSpan = el("span", "agent-card-emoji", ag.signature_emoji || (ag.is_platform ? "🦀" : "🤖"));
            const nameSpan = el("strong", "agent-card-name", `@${ag.name}`);
            header.append(emojiSpan, nameSpan);
            const descP = el("p", "agent-card-desc", ag.description);
            card.append(header, descP);
            card.addEventListener("click", () => {
                selectedAgentName = ag.name;
                startDesc.textContent = `Active: ${ag.signature_emoji || (ag.is_platform ? "🦀" : "🤖")} ${ag.name} · ${ag.is_platform ? "platform workspace" : "custom agent workspace"}`;
                renderCards(agents);
            });
            agentCards.append(card);
        }
    }
    async function loadAgents() {
        try {
            const res = await fetch("/api/agents");
            if (!res.ok) {
                statusLine.textContent = "Failed to load custom agents.";
                return;
            }
            const agents = (await res.json());
            renderCards(agents);
        }
        catch {
            statusLine.textContent = "Failed to load custom agents.";
        }
    }
    void loadAgents();
    async function start() {
        button.disabled = true;
        statusLine.textContent = "";
        const response = await fetch("/api/sessions", { method: "POST" });
        if (!response.ok) {
            statusLine.textContent = "The session could not be started.";
            button.disabled = false;
            return;
        }
        const body = (await response.json());
        const agentParam = selectedAgentName !== "main"
            ? `&agent=${encodeURIComponent(selectedAgentName)}`
            : "";
        ctx.navigate(`/chat?session=${body.id}${agentParam}`);
    }
    form.addEventListener("submit", (event) => {
        event.preventDefault();
        void start();
    });
}
