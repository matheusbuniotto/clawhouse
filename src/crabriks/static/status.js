const statUserNode = document.querySelector("#stat-user");
const statAuthNode = document.querySelector("#stat-auth");
const statTokenNode = document.querySelector("#stat-token");
const statWorkspaceNode = document.querySelector("#stat-workspace");
const statModelNode = document.querySelector("#stat-model");
const statStoreNode = document.querySelector("#stat-store");
const sessionsListNode = document.querySelector("#sessions-list");
const logTailLinkNode = document.querySelector("#log-tail-link");
const statusNode = document.querySelector("#status");
if (!statUserNode ||
    !statAuthNode ||
    !statTokenNode ||
    !statWorkspaceNode ||
    !statModelNode ||
    !statStoreNode ||
    !sessionsListNode ||
    !logTailLinkNode ||
    !statusNode) {
    throw new Error("status page is missing a required element");
}
const statUser = statUserNode;
const statAuth = statAuthNode;
const statToken = statTokenNode;
const statWorkspace = statWorkspaceNode;
const statModel = statModelNode;
const statStore = statStoreNode;
const sessionsList = sessionsListNode;
const logTailLink = logTailLinkNode;
const statusLine = statusNode;
function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className)
        node.className = className;
    if (text !== undefined)
        node.textContent = text;
    return node;
}
function renderAuthAndConnection(auth, connection) {
    statUser.textContent = auth.user_id || "Anonymous";
    statAuth.textContent = auth.auth_type.toUpperCase();
    statToken.textContent = auth.token_present
        ? auth.auth_type === "dev"
            ? "Present (dev)"
            : "Present (forwarded)"
        : "Not present";
    statWorkspace.textContent = connection.workspace_host || "Local environment";
    statModel.textContent = connection.serving_endpoint || "Default endpoint";
    statStore.textContent =
        connection.store_type === "memory" ? "In-Memory Store" : "Lakebase Postgres";
}
function renderSessions(items) {
    sessionsList.replaceChildren();
    if (items.length === 0) {
        sessionsList.append(el("li", "empty", "No sessions yet."));
        return;
    }
    for (const item of items) {
        const row = el("li", "session-status-row");
        const link = document.createElement("a");
        link.className = "session-link";
        link.href = `/chat?session=${item.id}`;
        link.textContent = item.title || "Untitled session";
        const badge = el("span", `status-badge ${item.run_state}`, item.run_state);
        const when = el("span", "when", new Date(item.created_at).toLocaleString());
        row.append(link, badge, when);
        sessionsList.append(row);
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
        renderSessions(data.sessions);
        if (data.log_tail_url) {
            logTailLink.href = data.log_tail_url;
        }
    }
    catch {
        statusLine.textContent = "Network error while loading status.";
    }
}
void load();
export {};
