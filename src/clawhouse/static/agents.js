import { el, relativeTime } from "./dom.js";
export function mount(root, ctx) {
    let currentAgents = [];
    let activeCleanup = null;
    const page = el("section", "agents-page");
    const header = el("header", "agents-header");
    const titleWrap = el("div", "agents-title-group");
    const heading = el("h2", "agents-heading", "Agentes");
    const subtitle = el("p", "agents-subtitle", "Quem está na sua equipe e o que está fazendo");
    titleWrap.append(heading, subtitle);
    const actions = el("div", "agents-header-actions");
    const manageBtn = el("button", "btn-secondary", "Gerenciar agentes");
    manageBtn.id = "btn-manage-agents";
    manageBtn.type = "button";
    const newBtn = el("button", "btn-primary", "Novo agente");
    newBtn.id = "btn-new-agent";
    newBtn.type = "button";
    actions.append(manageBtn, newBtn);
    header.append(titleWrap, actions);
    const grid = el("div", "agents-grid");
    page.append(header, grid);
    root.append(page);
    function closeModal() {
        if (activeCleanup) {
            activeCleanup();
            activeCleanup = null;
        }
        page.querySelector(".modal-backdrop")?.remove();
    }
    function openModal(modalDialog) {
        closeModal();
        const backdrop = el("div", "modal-backdrop");
        backdrop.append(modalDialog);
        backdrop.addEventListener("click", (event) => {
            if (event.target === backdrop) {
                closeModal();
            }
        });
        const onKeyDown = (event) => {
            if (event.key === "Escape") {
                closeModal();
            }
        };
        window.addEventListener("keydown", onKeyDown);
        activeCleanup = () => window.removeEventListener("keydown", onKeyDown);
        page.append(backdrop);
    }
    async function launchAgentSession(agent, button) {
        button.disabled = true;
        try {
            const res = await fetch("/api/sessions", { method: "POST" });
            if (!res.ok) {
                button.disabled = false;
                return;
            }
            const body = (await res.json());
            const target = agent.name === "main"
                ? `/chat?session=${body.id}`
                : `/chat?session=${body.id}&agent=${encodeURIComponent(agent.name)}`;
            ctx.navigate(target);
        }
        catch {
            button.disabled = false;
        }
    }
    function renderGrid(agents) {
        grid.replaceChildren();
        for (const ag of agents) {
            const card = el("article", "agent-card");
            card.dataset.agent = ag.name;
            const top = el("div", "agent-card-top");
            const avatar = el("div", "agent-card-avatar", ag.signature_emoji || (ag.is_platform ? "🦀" : "🤖"));
            const identity = el("div", "agent-card-identity");
            const title = el("h3", "agent-card-title", ag.name);
            const modelBadge = el("span", "agent-card-model", ag.model || "databricks");
            identity.append(title, modelBadge);
            top.append(avatar, identity);
            const statusText = ag.last_active_at
                ? relativeTime(ag.last_active_at, Date.now())
                : "Recém-criado";
            const statusRow = el("p", "agent-card-status", statusText);
            const activityText = ag.last_activity || ag.description || "";
            const activityP = el("p", "agent-card-activity", activityText);
            const footer = el("div", "agent-card-footer");
            const openBtn = el("button", "btn-open-chat", "Abrir chat");
            openBtn.type = "button";
            openBtn.addEventListener("click", () => {
                void launchAgentSession(ag, openBtn);
            });
            footer.append(openBtn);
            card.append(top, statusRow, activityP, footer);
            grid.append(card);
        }
    }
    async function loadAgents() {
        grid.replaceChildren(el("p", "agents-loading", "Carregando agentes…"));
        try {
            const res = await fetch("/api/agents");
            if (!res.ok) {
                throw new Error(`HTTP ${res.status}`);
            }
            currentAgents = (await res.json());
            renderGrid(currentAgents);
        }
        catch {
            const errBox = el("div", "agents-error");
            const msg = el("p", "agents-error-text", "Não foi possível carregar os agentes.");
            const retryBtn = el("button", "btn-retry-agents", "Tentar novamente");
            retryBtn.type = "button";
            retryBtn.addEventListener("click", () => {
                void loadAgents();
            });
            errBox.append(msg, retryBtn);
            grid.replaceChildren(errBox);
        }
    }
    function openNewAgentModal() {
        const dialog = el("div", "modal-dialog");
        dialog.id = "modal-new-agent";
        dialog.setAttribute("role", "dialog");
        dialog.setAttribute("aria-modal", "true");
        const head = el("header", "modal-header");
        const title = el("h3", "modal-title", "Novo agente");
        const closeBtn = el("button", "modal-close", "×");
        closeBtn.type = "button";
        closeBtn.setAttribute("aria-label", "Fechar");
        closeBtn.addEventListener("click", closeModal);
        head.append(title, closeBtn);
        const form = document.createElement("form");
        form.className = "modal-form";
        const nameInput = document.createElement("input");
        nameInput.className = "agent-input";
        nameInput.name = "name";
        nameInput.placeholder = "Nome do agente (ex: data_analyst)";
        nameInput.required = true;
        const emojiInput = document.createElement("input");
        emojiInput.className = "agent-input";
        emojiInput.name = "signature_emoji";
        emojiInput.placeholder = "Emoji (ex: 📊, 🤖)";
        emojiInput.maxLength = 4;
        emojiInput.value = "🤖";
        const descInput = document.createElement("input");
        descInput.className = "agent-input";
        descInput.name = "description";
        descInput.placeholder = "Descrição curta";
        descInput.required = true;
        const promptArea = document.createElement("textarea");
        promptArea.className = "agent-prompt";
        promptArea.name = "system_prompt";
        promptArea.placeholder = "Instruções de operação (AGENTS.md)";
        promptArea.rows = 3;
        promptArea.required = true;
        const soulArea = document.createElement("textarea");
        soulArea.className = "agent-prompt";
        soulArea.name = "soul";
        soulArea.placeholder = "Opcional: SOUL.md (persona, tom de voz)";
        soulArea.rows = 2;
        const contextArea = document.createElement("textarea");
        contextArea.className = "agent-prompt";
        contextArea.name = "context";
        contextArea.placeholder = "Opcional: CONTEXT.md (contexto de domínio e tabelas)";
        contextArea.rows = 2;
        const statusLine = el("p", "modal-status");
        statusLine.setAttribute("role", "status");
        const actionsRow = el("div", "modal-actions");
        const submitBtn = el("button", "btn-primary", "Criar agente");
        submitBtn.type = "submit";
        actionsRow.append(submitBtn);
        form.append(nameInput, emojiInput, descInput, promptArea, soulArea, contextArea, statusLine, actionsRow);
        form.addEventListener("submit", async (event) => {
            event.preventDefault();
            submitBtn.disabled = true;
            statusLine.textContent = "";
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
                    statusLine.textContent = `Erro ao criar agente (${res.status}).`;
                    submitBtn.disabled = false;
                    return;
                }
                closeModal();
                await loadAgents();
            }
            catch {
                statusLine.textContent = "Erro ao criar agente.";
                submitBtn.disabled = false;
            }
        });
        dialog.append(head, form);
        openModal(dialog);
    }
    function openManageAgentsModal() {
        const dialog = el("div", "modal-dialog");
        dialog.id = "modal-manage-agents";
        dialog.setAttribute("role", "dialog");
        dialog.setAttribute("aria-modal", "true");
        const head = el("header", "modal-header");
        const title = el("h3", "modal-title", "Gerenciar agentes");
        const closeBtn = el("button", "modal-close", "×");
        closeBtn.type = "button";
        closeBtn.setAttribute("aria-label", "Fechar");
        closeBtn.addEventListener("click", closeModal);
        head.append(title, closeBtn);
        const list = el("ul", "manage-agents-list");
        const statusLine = el("p", "modal-status");
        function renderRows() {
            list.replaceChildren();
            for (const ag of currentAgents) {
                const row = el("li", "manage-agent-row");
                const info = el("div", "manage-agent-info");
                const emoji = el("span", "manage-agent-emoji", ag.signature_emoji || (ag.is_platform ? "🦀" : "🤖"));
                const name = el("strong", "agent-name", `@${ag.name}`);
                const desc = el("span", "agent-desc", ag.description);
                info.append(emoji, name, desc);
                row.append(info);
                if (ag.is_platform || ag.name === "main") {
                    row.append(el("span", "agent-protected-badge", "Plataforma"));
                }
                else {
                    const delBtn = el("button", "btn-delete-agent", "Excluir");
                    delBtn.type = "button";
                    delBtn.addEventListener("click", async () => {
                        delBtn.disabled = true;
                        statusLine.textContent = "";
                        try {
                            const delRes = await fetch(`/api/agents/${encodeURIComponent(ag.id)}`, { method: "DELETE" });
                            if (!delRes.ok) {
                                statusLine.textContent = `Falha ao excluir @${ag.name}.`;
                                delBtn.disabled = false;
                                return;
                            }
                            await loadAgents();
                            renderRows();
                        }
                        catch {
                            statusLine.textContent = `Falha ao excluir @${ag.name}.`;
                            delBtn.disabled = false;
                        }
                    });
                    row.append(delBtn);
                }
                list.append(row);
            }
        }
        renderRows();
        dialog.append(head, list, statusLine);
        openModal(dialog);
    }
    newBtn.addEventListener("click", openNewAgentModal);
    manageBtn.addEventListener("click", openManageAgentsModal);
    void loadAgents();
}
