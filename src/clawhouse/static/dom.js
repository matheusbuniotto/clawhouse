/** Shared DOM helpers for the shell and the screen modules. */
export function isRunning(state) {
    return state === "running";
}
export function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className)
        node.className = className;
    if (text !== undefined)
        node.textContent = text;
    return node;
}
export function svgEl(tag, attrs = {}) {
    const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (const [name, value] of Object.entries(attrs))
        node.setAttribute(name, value);
    return node;
}
export function relativeTime(iso, now = Date.now()) {
    const seconds = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
    if (seconds < 45)
        return "just now";
    const minutes = Math.round(seconds / 60);
    if (minutes < 60)
        return `${minutes}m ago`;
    const hours = Math.round(minutes / 60);
    if (hours < 24)
        return `${hours}h ago`;
    const days = Math.round(hours / 24);
    if (days < 7)
        return `${days}d ago`;
    return new Date(iso).toLocaleDateString();
}
/** A collapsed "Raw JSON" disclosure, shared by the structured tool-result views. */
export function rawJsonDisclosure(rawJson) {
    const details = el("details", "tabular-raw");
    details.append(el("summary", "", "Raw JSON"), el("pre", "tool-io tool-output", rawJson));
    return details;
}
/** Fired on `window` after a rename lands, so the rail, chat header, and sessions page agree. */
export const SESSION_RENAMED = "clawhouse:session-renamed";
export const UNTITLED = "Untitled session";
/** PATCH a session title. Returns the saved title, or null when the server refused it. */
export async function renameSession(id, title) {
    try {
        const response = await fetch(`/api/sessions/${id}`, {
            method: "PATCH",
            headers: { "content-type": "application/json" },
            body: JSON.stringify({ title }),
        });
        if (!response.ok)
            return null;
        const body = (await response.json());
        const saved = body.title || title;
        window.dispatchEvent(new CustomEvent(SESSION_RENAMED, { detail: { id, title: saved } }));
        return saved;
    }
    catch {
        return null;
    }
}
/** Empty a session's transcript; the session, its id, and its title stay. */
export async function clearSession(id) {
    try {
        const response = await fetch(`/api/sessions/${id}/clear`, { method: "POST" });
        return response.ok;
    }
    catch {
        return false;
    }
}
/**
 * Swap `label` for a title input. Enter, Save, or leaving the field saves;
 * Escape restores the label without a request. Events stay inside the editor
 * so an enclosing link does not navigate.
 */
export function editTitle(label, current, save, inputId) {
    const previous = label.textContent ?? "";
    const editor = el("span", "title-editor");
    const input = el("input", "title-input");
    input.type = "text";
    input.value = current;
    input.maxLength = 120;
    input.setAttribute("aria-label", "Session title");
    if (inputId)
        input.id = inputId;
    const saveButton = el("button", "title-save", "Save");
    saveButton.type = "button";
    editor.append(input, saveButton);
    let settled = false;
    function finish(text) {
        settled = true;
        editor.remove();
        label.textContent = text;
        label.hidden = false;
    }
    async function commit() {
        if (settled)
            return;
        settled = true;
        const title = input.value.trim();
        if (!title || title === current) {
            finish(previous);
            return;
        }
        finish((await save(title)) ?? previous);
    }
    for (const node of [editor, input, saveButton]) {
        node.addEventListener("click", (event) => {
            event.preventDefault();
            event.stopPropagation();
        });
    }
    // Keep focus in the input so pressing Save does not first count as leaving it.
    saveButton.addEventListener("mousedown", (event) => event.preventDefault());
    saveButton.addEventListener("click", () => void commit());
    input.addEventListener("keydown", (event) => {
        event.stopPropagation();
        if (event.key === "Escape") {
            event.preventDefault();
            if (!settled)
                finish(previous);
        }
        else if (event.key === "Enter") {
            event.preventDefault();
            void commit();
        }
    });
    input.addEventListener("blur", () => void commit());
    label.hidden = true;
    label.after(editor);
    input.focus();
    input.select();
    return input;
}
