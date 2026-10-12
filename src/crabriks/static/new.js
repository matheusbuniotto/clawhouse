import { el } from "./dom.js";
export function mount(root, ctx) {
    const form = document.createElement("form");
    form.id = "start";
    form.className = "start";
    form.append(el("p", "agent", "Agent main · built-in, read-only"));
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
    const agentsHeader = el("h2", "custom-agents-heading", "Custom Agents");
    const agentsList = el("ul", "custom-agents-list");
    const emptyNote = el("p", "empty-agents", "No custom agents created yet.");
    const createForm = document.createElement("form");
    createForm.className = "create-agent-form";
    const nameInput = document.createElement("input");
    nameInput.className = "agent-input";
    nameInput.placeholder = "Agent name (e.g. data_analyst)";
    nameInput.required = true;
    const descInput = document.createElement("input");
    descInput.className = "agent-input";
    descInput.placeholder = "Description";
    descInput.required = true;
    const promptArea = document.createElement("textarea");
    promptArea.className = "agent-prompt";
    promptArea.placeholder = "System prompt / instructions";
    promptArea.rows = 2;
    promptArea.required = true;
    const createBtn = el("button", "btn-create-agent", "Create Agent");
    createBtn.type = "submit";
    const agentStatusLine = el("p", "status");
    agentStatusLine.id = "agent-status";
    agentStatusLine.setAttribute("role", "status");
    createForm.append(nameInput, descInput, promptArea, createBtn);
    agentsSection.append(agentsHeader, agentsList, createForm, agentStatusLine);
    root.append(agentsSection);
    async function loadAgents() {
        try {
            const res = await fetch("/api/agents");
            if (!res.ok) {
                agentStatusLine.textContent = "Failed to load custom agents.";
                return;
            }
            const agents = (await res.json());
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
                    description: descInput.value.trim(),
                    system_prompt: promptArea.value.trim(),
                }),
            });
            if (!res.ok) {
                agentStatusLine.textContent = "Failed to create custom agent.";
                return;
            }
            nameInput.value = "";
            descInput.value = "";
            promptArea.value = "";
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
        ctx.navigate(`/chat?session=${body.id}`);
    }
    form.addEventListener("submit", (event) => {
        event.preventDefault();
        void start();
    });
}
