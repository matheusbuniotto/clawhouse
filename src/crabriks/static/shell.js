import { el, relativeTime } from "./dom.js";
const THEME_KEY = "crabriks.theme-mode";
const ROUTES = {
    "/": () => import("./chat.js"),
    "/chat": () => import("./chat.js"),
    "/sessions": () => import("./sessions.js"),
    "/new": () => import("./new.js"),
    "/approvals": () => import("./approvals.js"),
    "/status": () => import("./status.js"),
};
function requireElement(parent, selector) {
    const node = parent.querySelector(selector);
    if (!node)
        throw new Error(`shell markup is missing ${selector}`);
    return node;
}
function normalize(path) {
    return path.length > 1 && path.endsWith("/") ? path.slice(0, -1) : path;
}
function groupFor(iso, now) {
    const days = Math.floor((now - new Date(iso).getTime()) / 86_400_000);
    if (days <= 0)
        return "Today";
    if (days === 1)
        return "Yesterday";
    if (days < 7)
        return "This week";
    return "Earlier";
}
/**
 * Bind the persistent shell: rail, theme, session list, and the History-API
 * router. The rail markup is served with every document; this only wires it up
 * and mounts the screen for the current path into `#screen`.
 */
export function mountShell(root = document) {
    const shell = requireElement(root, "#shell");
    const screen = requireElement(root, "#screen");
    const sessionList = requireElement(root, "#rail-sessions");
    const user = requireElement(root, "#rail-user");
    const search = requireElement(root, "#rail-search");
    const themeToggle = requireElement(root, "#theme-toggle");
    const collapse = requireElement(root, "#rail-collapse");
    const newButton = requireElement(root, "#rail-new");
    const shellWindow = window;
    shellWindow.__crabriksShellDispose?.();
    function navigate(href, options = {}) {
        const url = new URL(href, location.href);
        const target = `${url.pathname}${url.search}`;
        if (options.replace)
            history.replaceState(null, "", target);
        else
            history.pushState(null, "", target);
        void render(url);
        void loadSessions();
    }
    async function render(url) {
        const path = normalize(url.pathname);
        const loader = ROUTES[path] ?? ROUTES["/"];
        const module = await loader();
        screen.replaceChildren();
        module.mount(screen, { url, navigate });
        updateActive(path, url);
    }
    function updateActive(path, url) {
        for (const link of shell.querySelectorAll(".rail-nav a[data-nav]")) {
            const href = link.getAttribute("href")?.split("?")[0];
            if (href === path || (path === "/" && href === "/chat")) {
                link.setAttribute("aria-current", "page");
            }
            else {
                link.removeAttribute("aria-current");
            }
        }
        const session = url.searchParams.get("session");
        for (const row of sessionList.querySelectorAll(".rail-session")) {
            if (session !== null && row.dataset.id === session) {
                row.setAttribute("aria-current", "page");
            }
            else {
                row.removeAttribute("aria-current");
            }
        }
    }
    function onClick(event) {
        if (event.defaultPrevented || event.button !== 0)
            return;
        if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey)
            return;
        const anchor = event.target?.closest?.("a[data-nav]");
        if (!(anchor instanceof HTMLAnchorElement))
            return;
        const href = anchor.getAttribute("href");
        if (!href || !href.startsWith("/"))
            return;
        event.preventDefault();
        navigate(href);
    }
    function onPopState() {
        const url = new URL(location.href);
        void render(url);
        void loadSessions();
    }
    function sessionRow(item) {
        const link = el("a", "rail-session");
        link.setAttribute("data-nav", "");
        link.dataset.id = item.id;
        link.dataset.title = item.title.toLowerCase();
        link.href = `/chat?session=${item.id}`;
        link.append(el("span", "rail-session-title", item.title || "Untitled session"));
        link.append(el("span", "rail-session-time", relativeTime(item.created_at)));
        if (item.run_state === "running") {
            const pulse = el("span", "rail-session-pulse");
            pulse.dataset.state = "running";
            pulse.setAttribute("aria-label", "Running");
            link.append(pulse);
        }
        return link;
    }
    function renderSessions(items) {
        sessionList.replaceChildren();
        if (items.length === 0) {
            sessionList.append(el("p", "rail-empty", "No sessions yet."));
            return;
        }
        const now = Date.now();
        const groups = new Map();
        for (const item of items) {
            const key = groupFor(item.created_at, now);
            const bucket = groups.get(key);
            if (bucket)
                bucket.push(item);
            else
                groups.set(key, [item]);
        }
        for (const [title, group] of groups) {
            const container = el("div", "rail-group");
            container.append(el("p", "rail-group-title", title));
            for (const item of group)
                container.append(sessionRow(item));
            sessionList.append(container);
        }
    }
    async function loadSessions() {
        try {
            const response = await fetch("/api/sessions");
            if (!response.ok) {
                renderSessions([]);
                return;
            }
            const body = (await response.json());
            renderSessions(body.sessions ?? []);
        }
        catch {
            renderSessions([]);
        }
    }
    async function loadIdentity() {
        try {
            const response = await fetch("/api/me");
            if (!response.ok) {
                user.textContent = "Not signed in";
                return;
            }
            const body = (await response.json());
            user.textContent = body.user_id;
        }
        catch {
            user.textContent = "Not signed in";
        }
    }
    function syncTheme(mode) {
        document.documentElement.dataset.themeMode = mode;
        themeToggle.setAttribute("aria-pressed", String(mode === "light"));
        themeToggle.textContent = mode === "light" ? "Light" : "Dark";
    }
    themeToggle.addEventListener("click", () => {
        const next = document.documentElement.dataset.themeMode === "light" ? "dark" : "light";
        localStorage.setItem(THEME_KEY, next);
        syncTheme(next);
    });
    search.addEventListener("input", () => {
        const term = search.value.trim().toLowerCase();
        for (const row of sessionList.querySelectorAll(".rail-session")) {
            row.hidden = term !== "" && !(row.dataset.title ?? "").includes(term);
        }
    });
    newButton.addEventListener("click", () => navigate("/new"));
    collapse.addEventListener("click", () => {
        const collapsed = shell.toggleAttribute("data-collapsed");
        collapse.setAttribute("aria-expanded", String(!collapsed));
    });
    shell.addEventListener("click", onClick);
    window.addEventListener("popstate", onPopState);
    shellWindow.__crabriksShellDispose = () => {
        window.removeEventListener("popstate", onPopState);
        shell.removeEventListener("click", onClick);
    };
    const initialMode = localStorage.getItem(THEME_KEY) === "light" ? "light" : "dark";
    localStorage.setItem(THEME_KEY, initialMode);
    syncTheme(initialMode);
    void loadIdentity();
    void loadSessions();
    void render(new URL(location.href));
}
