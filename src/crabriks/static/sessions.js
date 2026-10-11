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
            row.append(link, el("span", "when", relativeTime(item.created_at)));
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
