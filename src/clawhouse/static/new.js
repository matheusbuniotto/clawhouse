import { el } from "./dom.js";
export function mount(root, ctx) {
    let selectedAgentName = "main";
    const pickerSection = el("section", "agent-picker-section");
    const pickerHeading = el("h2", "agent-picker-heading", "Choose Agent");
    const agentCards = el("div", "agent-cards-grid");
    pickerSection.append(pickerHeading, agentCards);
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
    // Custom agents manager section
    const agentsSection = el("section", "custom-agents-section");
    const agentsHeader = el("h2", "custom-agents-heading", "Create Workspace Agent");
    const agentsList = el("ul", "custom-agents-list");
    const emptyNote = el("p", "empty-agents", "No custom agents created yet.");
    const createForm = document.createElement("form");
    createForm.className = "create-agent-form";
    const nameInput = document.createElement("input");
    nameInput.className = "agent-input";
    nameInput.placeholder = "Agent name (e.g. data_analyst)";
    nameInput.required = true;
    const emojiInput = document.createElement("input");
    emojiInput.className = "agent-input";
    emojiInput.placeholder = "Emoji (e.g. 📊, 🤖)";
    emojiInput.maxLength = 4;
    emojiInput.value = "🤖";
    const descInput = document.createElement("input");
    descInput.className = "agent-input";
    descInput.placeholder = "Description";
    descInput.required = true;
    const promptArea = document.createElement("textarea");
    promptArea.className = "agent-prompt";
    promptArea.placeholder = "Operating rules / AGENTS.md instructions";
    promptArea.rows = 2;
    promptArea.required = true;
    const soulArea = document.createElement("textarea");
    soulArea.className = "agent-prompt";
    soulArea.placeholder = "Optional SOUL.md (persona, voice)";
    soulArea.rows = 2;
    const contextArea = document.createElement("textarea");
    contextArea.className = "agent-prompt";
    contextArea.placeholder = "Optional CONTEXT.md (domain & project context)";
    contextArea.rows = 2;
    const createBtn = el("button", "btn-create-agent", "Create Agent");
    createBtn.type = "submit";
    const agentStatusLine = el("p", "status");
    agentStatusLine.id = "agent-status";
    agentStatusLine.setAttribute("role", "status");
    createForm.append(nameInput, emojiInput, descInput, promptArea, soulArea, contextArea, createBtn);
    agentsSection.append(agentsHeader, agentsList, createForm, agentStatusLine);
    root.append(agentsSection);
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
                agentStatusLine.textContent = "Failed to load custom agents.";
                return;
            }
            const agents = (await res.json());
            renderCards(agents);
            agentsList.replaceChildren();
            const customOnly = agents.filter((ag) => !ag.is_platform);
            if (customOnly.length === 0) {
                agentsList.append(emptyNote);
                return;
            }
            for (const ag of customOnly) {
                const item = el("li", "custom-agent-item");
                const title = el("strong", "agent-name", `@${ag.name}`);
                const desc = el("span", "agent-desc", ag.description);
                const delBtn = el("button", "btn-delete-agent", "Delete");
                delBtn.type = "button";
                delBtn.addEventListener("click", async () => {
                    delBtn.disabled = true;
                    agentStatusLine.textContent = "";
                    try {
                        const delRes = await fetch(`/api/agents/${encodeURIComponent(ag.id)}`, {
                            method: "DELETE",
                        });
                        if (!delRes.ok) {
                            agentStatusLine.textContent = `Failed to delete agent @${ag.name}.`;
                            delBtn.disabled = false;
                            return;
                        }
                        if (selectedAgentName === ag.name) {
                            selectedAgentName = "main";
                            startDesc.textContent = "Active: 🦀 main · platform workspace";
                        }
                        void loadAgents();
                    }
                    catch {
                        agentStatusLine.textContent = `Failed to delete agent @${ag.name}.`;
                        delBtn.disabled = false;
                    }
                });
                item.append(title, desc, delBtn);
                agentsList.append(item);
            }
        }
        catch {
            agentStatusLine.textContent = "Failed to load custom agents.";
        }
    }
    createForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        createBtn.disabled = true;
        agentStatusLine.textContent = "";
        try {
            const res = await fetch("/api/agents", {
                method: "POST",
                headers: { "content-type": "application/json" },
                body: JSON.stringify({
                    name: nameInput.value.trim(),
                    signature_emoji: emojiInput.value.trim() || "🤖",
                    description: descInput.value.trim(),
                    system_prompt: promptArea.value.trim(),
                    soul: soulArea.value.trim() || null,
                    context: contextArea.value.trim() || null,
                }),
            });
            if (!res.ok) {
                agentStatusLine.textContent = "Failed to create custom agent.";
                return;
            }
            nameInput.value = "";
            emojiInput.value = "🤖";
            descInput.value = "";
            promptArea.value = "";
            soulArea.value = "";
            contextArea.value = "";
            void loadAgents();
        }
        catch {
            agentStatusLine.textContent = "Failed to create custom agent.";
        }
        finally {
            createBtn.disabled = false;
        }
    });
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
        const agentParam = selectedAgentName !== "main" ? `&agent=${encodeURIComponent(selectedAgentName)}` : "";
        ctx.navigate(`/chat?session=${body.id}${agentParam}`);
    }
    form.addEventListener("submit", (event) => {
        event.preventDefault();
        void start();
    });
}
