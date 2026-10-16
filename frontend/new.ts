import { el } from "./dom.js";
import type { ScreenContext } from "./shell.js";

interface AgentItem {
  id: string;
  name: string;
  description: string;
  system_prompt: string;
  signature_emoji?: string;
  is_platform?: boolean;
}

export function mount(root: HTMLElement, ctx: ScreenContext): void {
  let selectedAgentName = "main";

  const pickerSection = el("section", "agent-picker-section");
  const pickerHeading = el("h2", "agent-picker-heading", "Choose Agent");
  const agentCards = el("div", "agent-cards-grid");
  const manageLink = el("a", "manage-agents-link", "Manage or create agents →");
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

  function renderCards(agents: AgentItem[]): void {
    agentCards.replaceChildren();
    for (const ag of agents) {
      const card = el(
        "div",
        `agent-card${ag.name === selectedAgentName ? " selected" : ""}`,
      );
      const header = el("div", "agent-card-header");
      const emojiSpan = el(
        "span",
        "agent-card-emoji",
        ag.signature_emoji || (ag.is_platform ? "🦀" : "🤖"),
      );
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

  async function loadAgents(): Promise<void> {
    try {
      const res = await fetch("/api/agents");
      if (!res.ok) {
        statusLine.textContent = "Failed to load custom agents.";
        return;
      }
      const agents = (await res.json()) as AgentItem[];
      renderCards(agents);
    } catch {
      statusLine.textContent = "Failed to load custom agents.";
    }
  }

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
    const agentParam =
      selectedAgentName !== "main"
        ? `&agent=${encodeURIComponent(selectedAgentName)}`
        : "";
    ctx.navigate(`/chat?session=${body.id}${agentParam}`);
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    void start();
  });
}
