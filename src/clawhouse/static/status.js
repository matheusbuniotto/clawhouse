import { el, relativeTime } from "./dom.js";
const FIELDS = [
    ["User", "stat-user"],
    ["Auth mode", "stat-auth"],
    ["Token", "stat-token"],
    ["Workspace", "stat-workspace"],
    ["Model endpoint", "stat-model"],
    ["Storage", "stat-store"],
];
export function mount(root) {
    const connection = el("section", "status-section");
    connection.append(el("h2", "", "Connection & Identity"));
    const card = el("div", "status-card");
    const grid = el("dl", "status-grid");
    const values = new Map();
    for (const [label, id] of FIELDS) {
        grid.append(el("dt", "", label));
        const value = el("dd", "", "Loading…");
        value.id = id;
        values.set(id, value);
        grid.append(value);
    }
    card.append(grid);
    connection.append(card);
    const runs = el("section", "status-section");
    runs.append(el("h2", "", "Session Runs"));
    const sessionsList = el("ul", "sessions-list");
    sessionsList.id = "sessions-list";
    runs.append(sessionsList);
    const schedules = el("section", "status-section");
    schedules.append(el("h2", "", "Scheduled Automations"));
    const schedulesList = el("ul", "schedules-list");
    schedulesList.id = "schedules-list";
    schedules.append(schedulesList);
    const sandboxSection = el("section", "status-section");
    sandboxSection.append(el("h2", "", "User Sandbox"));
    const sandboxCard = el("div", "status-card");
    const sandboxGrid = el("dl", "status-grid");
    const sandboxFields = [
        ["Status", "stat-sandbox-status"],
        ["Backend", "stat-sandbox-backend"],
        ["Workspace path", "stat-sandbox-path"],
        ["Files", "stat-sandbox-files"],
    ];
    for (const [label, id] of sandboxFields) {
        sandboxGrid.append(el("dt", "", label));
        const value = el("dd", "", "Loading…");
        value.id = id;
        values.set(id, value);
        sandboxGrid.append(value);
    }
    sandboxCard.append(sandboxGrid);
    const sandboxActions = el("p", "sandbox-actions-row");
    const resetBtn = el("button", "btn-link", "Reset sandbox");
    resetBtn.id = "btn-reset-sandbox";
    resetBtn.type = "button";
    resetBtn.addEventListener("click", async () => {
        resetBtn.setAttribute("disabled", "true");
        try {
            const resp = await fetch("/api/sandbox/reset", { method: "POST" });
            if (resp.ok) {
                set("stat-sandbox-files", "0 files");
            }
        }
        finally {
            resetBtn.removeAttribute("disabled");
        }
    });
    sandboxActions.append(resetBtn);
    sandboxCard.append(sandboxActions);
    sandboxSection.append(sandboxCard);
    const diagnostics = el("section", "status-section");
    diagnostics.append(el("h2", "", "Diagnostics & Logs"));
    const logCard = el("div", "status-card");
    const logRow = el("p", "log-tail-row");
    const logTailLink = el("a", "btn-link", "Log tail");
    logTailLink.id = "log-tail-link";
    logTailLink.href = "#";
    logTailLink.target = "_blank";
    logTailLink.rel = "noopener";
    logRow.append(logTailLink);
    logCard.append(logRow);
    diagnostics.append(logCard);
    const statusLine = el("p", "status");
    statusLine.id = "status";
    statusLine.setAttribute("role", "status");
    root.append(connection, sandboxSection, runs, schedules, diagnostics, statusLine);
    function set(id, text) {
        const node = values.get(id);
        if (node)
            node.textContent = text;
    }
    function renderAuthAndConnection(auth, conn) {
        set("stat-user", auth.user_id || "Anonymous");
        set("stat-auth", auth.auth_type.toUpperCase());
        set("stat-token", auth.token_present
            ? auth.auth_type === "dev"
                ? "Present (dev)"
                : "Present (forwarded)"
            : "Not present");
        set("stat-workspace", conn.workspace_host || "Local environment");
        set("stat-model", conn.serving_endpoint || "Default endpoint");
        set("stat-store", conn.store_type === "memory" ? "In-Memory Store" : "Lakebase Postgres");
    }
    function renderSessions(items) {
        sessionsList.replaceChildren();
        if (items.length === 0) {
            sessionsList.append(el("li", "empty", "No sessions yet."));
            return;
        }
        for (const item of items) {
            const row = el("li", "session-status-row");
            const link = el("a", "session-link", item.title || "Untitled session");
            link.setAttribute("data-nav", "");
            link.href = `/chat?session=${item.id}`;
            row.append(link);
            row.append(el("span", `status-badge ${item.run_state}`, item.run_state));
            row.append(el("span", "when", relativeTime(item.created_at)));
            sessionsList.append(row);
        }
    }
    function renderSchedules(items) {
        schedulesList.replaceChildren();
        if (items.length === 0) {
            schedulesList.append(el("li", "empty", "No scheduled automations."));
            return;
        }
        for (const item of items) {
            const row = el("li", "schedule-status-row");
            const info = el("div", "schedule-info");
            const cronBadge = el("code", "schedule-cron", item.cron_expression);
            const promptSpan = el("span", "schedule-prompt", item.prompt);
            info.append(cronBadge, promptSpan);
            const meta = el("div", "schedule-meta");
            const statusBadge = el("span", `schedule-badge ${item.status}`, item.status);
            const nextRun = el("span", "when", `Next: ${relativeTime(item.next_run_at)}`);
            meta.append(statusBadge, nextRun);
            if (item.status === "active") {
                const cancelBtn = el("button", "btn-cancel-schedule", "Cancel");
                cancelBtn.type = "button";
                cancelBtn.addEventListener("click", async () => {
                    cancelBtn.disabled = true;
                    try {
                        const res = await fetch(`/api/schedules/${item.id}`, { method: "DELETE" });
                        if (res.ok) {
                            void loadSchedules();
                        }
                    }
                    catch {
                        cancelBtn.disabled = false;
                    }
                });
                meta.append(cancelBtn);
            }
            row.append(info, meta);
            schedulesList.append(row);
        }
    }
    async function loadSchedules() {
        try {
            const resp = await fetch("/api/schedules");
            if (resp.ok) {
                const items = (await resp.json());
                renderSchedules(items);
            }
        }
        catch {
            // Non-blocking
        }
    }
    async function load() {
        try {
            const resp = await fetch("/api/status");
            if (!resp.ok) {
                statusLine.textContent = "The status could not be loaded.";
                return;
            }
            const data = (await resp.json());
            renderAuthAndConnection(data.auth, data.connection);
            if (data.sandbox) {
                set("stat-sandbox-status", data.sandbox.status);
                set("stat-sandbox-backend", data.sandbox.backend);
                set("stat-sandbox-path", data.sandbox.workspace_path);
                set("stat-sandbox-files", `${data.sandbox.file_count} files`);
            }
            renderSessions(data.sessions);
            if (data.log_tail_url)
                logTailLink.href = data.log_tail_url;
            void loadSchedules();
        }
        catch {
            statusLine.textContent = "Network error while loading status.";
        }
    }
    void load();
}
