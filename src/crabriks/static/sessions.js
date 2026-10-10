const list = document.querySelector("#sessions");
const statusNode = document.querySelector("#status");
if (!list || !statusNode) {
    throw new Error("sessions page is missing a required element");
}
const sessions = list;
const statusLine = statusNode;
function el(tag, className, text) {
    const node = document.createElement(tag);
    node.className = className;
    if (text !== undefined)
        node.textContent = text;
    return node;
}
function render(items) {
    sessions.replaceChildren();
    if (items.length === 0) {
        sessions.append(el("li", "empty", "No sessions yet. Start one."));
        return;
    }
    for (const item of items) {
        const row = el("li", "session");
        const link = document.createElement("a");
        link.className = "session-link";
        link.href = `/chat?session=${item.id}`;
        link.textContent = item.title || "Untitled session";
        row.append(link);
        row.append(el("span", "when", new Date(item.created_at).toLocaleString()));
        sessions.append(row);
    }
}
async function load() {
    const response = await fetch("/api/sessions");
    if (!response.ok) {
        statusLine.textContent = "The sessions could not be loaded.";
        return;
    }
    const body = (await response.json());
    render(body.sessions);
}
void load();
export {};
