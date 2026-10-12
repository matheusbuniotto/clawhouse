import { el, relativeTime } from "./dom.js";
export function mount(root) {
    const list = el("ul", "sessions");
    list.id = "sessions";
    root.append(list);
    function render(items) {
        list.replaceChildren();
        if (items.length === 0) {
            list.append(el("li", "empty", "No sessions yet. Start one."));
            return;
        }
        for (const item of items) {
            const row = el("li", "session");
            const link = el("a", "session-link", item.title || "Untitled session");
            link.setAttribute("data-nav", "");
            link.href = `/chat?session=${item.id}`;
            const meta = el("div", "session-meta");
            const when = el("span", "when", relativeTime(item.created_at));
            const delBtn = el("button", "btn-delete-session", "Delete");
            delBtn.type = "button";
            delBtn.setAttribute("aria-label", `Delete session ${item.title || item.id}`);
            delBtn.addEventListener("click", async (e) => {
                e.preventDefault();
                e.stopPropagation();
                if (!confirm(`Delete "${item.title || "Untitled session"}"?`))
                    return;
                try {
                    const res = await fetch(`/api/sessions/${item.id}`, { method: "DELETE" });
                    if (res.ok || res.status === 204) {
                        row.remove();
                        if (list.children.length === 0) {
                            list.append(el("li", "empty", "No sessions yet. Start one."));
                        }
                        window.dispatchEvent(new CustomEvent("crabriks:session-deleted", { detail: { id: item.id } }));
                    }
                }
                catch {
                    // ignore network failure
                }
            });
            meta.append(when, delBtn);
            row.append(link, meta);
            list.append(row);
        }
    }
    async function load() {
        const response = await fetch("/api/sessions");
        if (!response.ok) {
            list.append(el("li", "empty", "The sessions could not be loaded."));
            return;
        }
        const body = (await response.json());
        render(body.sessions);
    }
    void load();
}
