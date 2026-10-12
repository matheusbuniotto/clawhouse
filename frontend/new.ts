import { el } from "./dom.js";
import type { ScreenContext } from "./shell.js";

export function mount(root: HTMLElement, ctx: ScreenContext): void {
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

  createForm.append(nameInput, descInput, promptArea, createBtn);
  agentsSection.append(agentsHeader, agentsList, createForm);
  root.append(agentsSection);

  async function loadAgents(): Promise<void> {
    try {
      const res = await fetch("/api/agents");
      if (!res.ok) return;
      const data = (await res.json()) as {
        agents: { name: string; description: string; system_prompt: string }[];
      };
      agentsList.replaceChildren();
      if (!data.agents || data.agents.length === 0) {
        agentsList.append(emptyNote);
        return;
      }
      for (const ag of data.agents) {
        const item = el("li", "custom-agent-item");
        const title = el("strong", "agent-name", `@${ag.name}`);
        const desc = el("span", "agent-desc", ag.description);
        const delBtn = el("button", "btn-delete-agent", "Delete");
        delBtn.type = "button";
        delBtn.addEventListener("click", async () => {
          delBtn.disabled = true;
          await fetch(`/api/agents/${encodeURIComponent(ag.name)}`, { method: "DELETE" });
          void loadAgents();
        });
        item.append(title, desc, delBtn);
        agentsList.append(item);
      }
    } catch {
      // ignore
    }
  }

  createForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    createBtn.disabled = true;
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
      if (res.ok) {
        nameInput.value = "";
        descInput.value = "";
        promptArea.value = "";
        void loadAgents();
      }
    } finally {
      createBtn.disabled = false;
    }
  });

  void loadAgents();

  async function start(): Promise<void> {
    button.disabled = true;
    statusLine.textContent = "";
    const response = await fetch("/api/sessions", { method: "POST" });
    if (!response.ok) {
      statusLine.textContent = "The session could not be started.";
      button.disabled = false;
      return;
    }
    const body = (await response.json()) as { id: string };
    ctx.navigate(`/chat?session=${body.id}`);
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    void start();
  });
}
