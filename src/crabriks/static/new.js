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
