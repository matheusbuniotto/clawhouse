import { el } from "./dom.js";
export function mount(root) {
    const pendingSection = el("section", "approvals-section");
    pendingSection.append(el("h2", "", "Pending Approvals"));
    const pendingList = el("ul", "approvals-list");
    pendingList.id = "pending-list";
    pendingSection.append(pendingList);
    const historySection = el("section", "approvals-section");
    historySection.append(el("h2", "", "History"));
    const historyList = el("ul", "approvals-list");
    historyList.id = "history-list";
    historySection.append(historyList);
    const statusLine = el("p", "status");
    statusLine.id = "status";
    statusLine.setAttribute("role", "status");
    root.append(pendingSection, historySection, statusLine);
    function renderPending(items) {
        pendingList.replaceChildren();
        if (items.length === 0) {
            pendingList.append(el("li", "empty", "No pending approvals."));
            return;
        }
        for (const item of items) {
            const card = el("li", "approval-card");
            const header = el("div", "approval-header");
            header.append(el("strong", "tool-name", item.tool_name));
            header.append(el("span", "when", new Date(item.created_at).toLocaleString()));
            card.append(header);
            const sessionLink = el("a", "session-link");
            sessionLink.setAttribute("data-nav", "");
            sessionLink.href = `/chat?session=${item.session_id}`;
            sessionLink.textContent = `Session: ${item.session_id}`;
            card.append(sessionLink);
            card.append(el("pre", "args-json", item.arguments));
            const actions = el("div", "approval-actions");
            const approveBtn = el("button", "btn-approve", "Approve");
            const denyBtn = el("button", "btn-deny", "Deny");
            approveBtn.addEventListener("click", async () => {
                approveBtn.disabled = true;
                denyBtn.disabled = true;
                statusLine.textContent = `Approving ${item.tool_name}…`;
                const res = await fetch(`/api/approvals/${item.id}/approve`, { method: "POST" });
                if (res.ok) {
                    statusLine.textContent = `Approved ${item.tool_name}.`;
                    await load();
                }
                else {
                    statusLine.textContent = "Failed to approve tool call.";
                    approveBtn.disabled = false;
                    denyBtn.disabled = false;
                }
            });
            denyBtn.addEventListener("click", async () => {
                approveBtn.disabled = true;
                denyBtn.disabled = true;
                statusLine.textContent = `Denying ${item.tool_name}…`;
                const res = await fetch(`/api/approvals/${item.id}/deny`, { method: "POST" });
                if (res.ok) {
                    statusLine.textContent = `Denied ${item.tool_name}.`;
                    await load();
                }
                else {
                    statusLine.textContent = "Failed to deny tool call.";
                    approveBtn.disabled = false;
                    denyBtn.disabled = false;
                }
            });
            actions.append(approveBtn, denyBtn);
            card.append(actions);
            pendingList.append(card);
        }
    }
    function renderHistory(items) {
        historyList.replaceChildren();
        if (items.length === 0) {
            historyList.append(el("li", "empty", "No approval history."));
            return;
        }
        for (const item of items) {
            const card = el("li", "approval-history-row");
            card.append(el("strong", "tool-name", item.tool_name));
            card.append(el("span", `status-badge ${item.status}`, item.status));
            card.append(el("span", "when", new Date(item.created_at).toLocaleString()));
            if (item.resolved_by)
                card.append(el("span", "resolver", `by ${item.resolved_by}`));
            historyList.append(card);
        }
    }
    async function load() {
        const resp = await fetch("/api/approvals");
        if (!resp.ok) {
            statusLine.textContent = "The approvals could not be loaded.";
            return;
        }
        const body = (await resp.json());
        renderPending(body.pending ?? []);
        renderHistory(body.history ?? []);
    }
    void load();
}
