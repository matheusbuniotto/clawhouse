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
