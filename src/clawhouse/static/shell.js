import { SESSION_RENAMED, UNTITLED, editTitle, el, isRunning, relativeTime, renameSession, } from "./dom.js";
const THEME_KEY = "clawhouse.theme-mode";
const RAIL_WIDTH_KEY = "clawhouse.rail-width";
const MIN_RAIL_WIDTH = 180;
const MAX_RAIL_WIDTH = 480;
const TITLES = {
    "/": "Clawhouse",
    "/chat": "Clawhouse",
    "/sessions": "Clawhouse · Sessions",
    "/agents": "Clawhouse · Agents",
    "/new": "Clawhouse · New session",
    "/approvals": "Clawhouse · Approvals",
    "/status": "Clawhouse · Status",
    "/jobs": "Clawhouse · Jobs",
};
const ROUTES = {
    "/": () => import("./chat.js"),
    "/chat": () => import("./chat.js"),
    "/sessions": () => import("./sessions.js"),
    "/agents": () => import("./agents.js"),
    "/new": () => import("./new.js"),
    "/approvals": () => import("./approvals.js"),
    "/status": () => import("./status.js"),
    "/jobs": () => import("./jobspage.js"),
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
function clampRailWidth(width) {
    return Math.min(MAX_RAIL_WIDTH, Math.max(MIN_RAIL_WIDTH, Math.round(width)));
}
/**
 * Bind the persistent shell: rail, theme, session list, drag-resize, and the
 * History-API router. The rail markup is served with the document; this only
 * wires it up and mounts the screen for the current path into `#screen`.
 */
export function mountShell(root = document) {
    const shell = requireElement(root, "#shell");
    const screen = requireElement(root, "#screen");
    const sessionList = requireElement(root, "#rail-sessions");
    const user = requireElement(root, "#rail-user");
    const search = requireElement(root, "#rail-search");
    const themeToggle = requireElement(root, "#theme-toggle");
    const collapse = requireElement(root, "#rail-collapse");
    const expand = requireElement(root, "#rail-expand");
    const newButton = requireElement(root, "#rail-new");
    const handle = requireElement(root, "#rail-handle");
    const agentMenuBtn = shell.querySelector("#rail-agent-menu");
    function closeAgentPopover() {
        shell.querySelector("#rail-agent-popover")?.remove();
        agentMenuBtn?.setAttribute("aria-expanded", "false");
    }
    async function toggleAgentPopover() {
        if (!agentMenuBtn)
            return;
        const existing = shell.querySelector("#rail-agent-popover");
        if (existing) {
            closeAgentPopover();
            return;
        }
        agentMenuBtn.setAttribute("aria-expanded", "true");
        const popover = el("div", "rail-agent-popover");
        popover.id = "rail-agent-popover";
        popover.setAttribute("role", "menu");
        const overviewItem = el("button", "rail-agent-popover-item", "Agents overview");
        overviewItem.type = "button";
        overviewItem.dataset.action = "overview";
        overviewItem.addEventListener("click", () => {
            closeAgentPopover();
            navigate("/agents");
        });
        const newAgentItem = el("button", "rail-agent-popover-item", "+ New agent");
        newAgentItem.type = "button";
        newAgentItem.dataset.action = "new-agent";
        newAgentItem.addEventListener("click", () => {
            closeAgentPopover();
            navigate("/agents?new=1");
        });
        popover.append(overviewItem, newAgentItem);
        const head = shell.querySelector(".rail-head") ?? shell;
        head.append(popover);
        try {
            const res = await fetch("/api/agents");
            if (!res.ok)
                return;
            const agents = (await res.json());
            if (!popover.isConnected || agents.length === 0)
                return;
            const divider = el("div", "rail-agent-popover-divider");
            popover.append(divider);
            for (const ag of agents) {
                const emoji = ag.signature_emoji || (ag.is_platform ? "🦀" : "🤖");
                const item = el("button", "rail-agent-popover-item", `${emoji} ${ag.name}`);
                item.type = "button";
                item.dataset.agent = ag.name;
                item.addEventListener("click", async () => {
                    const label = agentMenuBtn.querySelector(".rail-agent-trigger-label");
                    if (label)
                        label.textContent = `${emoji} ${ag.name}`;
                    closeAgentPopover();
                    try {
                        const sRes = await fetch("/api/sessions", { method: "POST" });
                        if (sRes.ok) {
                            const sBody = (await sRes.json());
                            const target = ag.name === "main"
                                ? `/chat?session=${sBody.id}`
                                : `/chat?session=${sBody.id}&agent=${encodeURIComponent(ag.name)}`;
                            navigate(target);
                            return;
                        }
                    }
                    catch {
                        // fallback to /agents
                    }
                    navigate("/agents");
                });
                popover.append(item);
            }
        }
        catch {
            // keep overview & new agent items available
        }
    }
    agentMenuBtn?.addEventListener("click", (event) => {
        event.stopPropagation();
        void toggleAgentPopover();
    });
    function navigate(href, options = {}) {
        closeAgentPopover();
        const url = new URL(href, location.href);
        const target = `${url.pathname}${url.search}`;
        if (options.replace)
            history.replaceState(null, "", target);
        else
            history.pushState(null, "", target);
        void render(url);
        void loadSessions();
    }
    let renderSeq = 0;
    async function render(url) {
        const path = normalize(url.pathname);
        const loader = ROUTES[path] ?? ROUTES["/"];
        // Only the latest navigation mounts: a slower, older import must not clobber it.
        const seq = ++renderSeq;
        const module = await loader();
        if (seq !== renderSeq)
            return;
        document.title = TITLES[path] ?? "Clawhouse";
        screen.replaceChildren();
        module.mount(screen, { url, navigate });
        updateActive(path, url);
    }
    function updateActive(path, url) {
        const activeAgent = url.searchParams.get("agent");
        const badgeLabel = agentMenuBtn?.querySelector(".rail-agent-trigger-label");
        if (badgeLabel && activeAgent) {
            badgeLabel.textContent = `🤖 ${activeAgent}`;
        }
        else if (badgeLabel && !activeAgent) {
            badgeLabel.textContent = "🦀 main";
        }
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
        let currentTitle = item.title;
        const link = el("a", "rail-session");
        link.setAttribute("data-nav", "");
        link.dataset.id = item.id;
        link.dataset.title = currentTitle.toLowerCase();
        link.href = `/chat?session=${item.id}`;
        const titleSpan = el("span", "rail-session-title", currentTitle || UNTITLED);
        link.append(titleSpan);
        const actions = el("span", "rail-session-actions");
        const renameBtn = el("button", "rail-session-rename", "✎");
        renameBtn.type = "button";
        renameBtn.setAttribute("aria-label", `Rename session ${currentTitle || item.id}`);
        renameBtn.title = "Rename session";
        renameBtn.addEventListener("click", (e) => {
            e.preventDefault();
            e.stopPropagation();
            if (titleSpan.hidden)
                return;
            editTitle(titleSpan, currentTitle, async (newTitle) => {
                const saved = await renameSession(item.id, newTitle);
                if (saved !== null) {
                    currentTitle = saved;
                    link.dataset.title = saved.toLowerCase();
                }
                return saved;
            });
        });
        const delBtn = el("button", "rail-session-delete", "×");
        delBtn.type = "button";
        delBtn.setAttribute("aria-label", `Delete session ${currentTitle || item.id}`);
        delBtn.title = "Delete session";
        delBtn.addEventListener("click", async (e) => {
            e.preventDefault();
            e.stopPropagation();
            if (!confirm(`Delete "${currentTitle || UNTITLED}"?`))
                return;
            try {
                const res = await fetch(`/api/sessions/${item.id}`, {
                    method: "DELETE",
                });
                if (res.ok || res.status === 204) {
                    const currentSession = new URL(location.href).searchParams.get("session");
                    if (currentSession === item.id) {
                        navigate("/chat");
                    }
                    void loadSessions();
                }
            }
            catch {
                // ignore network error
            }
        });
        actions.append(renameBtn, delBtn);
        link.append(actions);
        link.append(el("span", "rail-session-time", relativeTime(item.created_at)));
        if (isRunning(item.run_state)) {
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
        const label = themeToggle.querySelector(".rail-theme-label");
        if (label)
            label.textContent = mode === "light" ? "Light" : "Dark";
    }
    function applyRailWidth(width) {
        const clamped = clampRailWidth(width);
        document.documentElement.style.setProperty("--rail-width", `${clamped}px`);
        localStorage.setItem(RAIL_WIDTH_KEY, String(clamped));
    }
    function startResize(event) {
        if (shell.hasAttribute("data-collapsed"))
            return;
        event.preventDefault();
        shell.setAttribute("data-resizing", "");
        const left = shell.getBoundingClientRect().left;
        function onMove(move) {
            applyRailWidth(move.clientX - left);
        }
        function onEnd() {
            shell.removeAttribute("data-resizing");
            window.removeEventListener("pointermove", onMove);
            window.removeEventListener("pointerup", onEnd);
            window.removeEventListener("pointercancel", onEnd);
        }
        window.addEventListener("pointermove", onMove);
        window.addEventListener("pointerup", onEnd);
        window.addEventListener("pointercancel", onEnd);
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
    function setCollapsed(collapsed) {
        if (collapsed)
            shell.setAttribute("data-collapsed", "");
        else
            shell.removeAttribute("data-collapsed");
        collapse.setAttribute("aria-expanded", String(!collapsed));
        expand.setAttribute("aria-expanded", String(collapsed));
    }
    collapse.addEventListener("click", () => setCollapsed(!shell.hasAttribute("data-collapsed")));
    expand.addEventListener("click", () => setCollapsed(false));
    handle.addEventListener("pointerdown", startResize);
    shell.addEventListener("click", onClick);
    window.addEventListener("popstate", onPopState);
    window.addEventListener("clawhouse:session-deleted", () => {
        void loadSessions();
    });
    window.addEventListener(SESSION_RENAMED, (event) => {
        const detail = event.detail;
        if (!detail)
            return;
        for (const row of sessionList.querySelectorAll(".rail-session")) {
            if (row.dataset.id === detail.id) {
                row.dataset.title = detail.title.toLowerCase();
                const titleEl = row.querySelector(".rail-session-title");
                if (titleEl)
                    titleEl.textContent = detail.title || UNTITLED;
            }
        }
    });
    const storedWidth = Number(localStorage.getItem(RAIL_WIDTH_KEY));
    if (Number.isFinite(storedWidth) && storedWidth > 0)
        applyRailWidth(storedWidth);
    const initialMode = localStorage.getItem(THEME_KEY) === "light" ? "light" : "dark";
    localStorage.setItem(THEME_KEY, initialMode);
    syncTheme(initialMode);
    void loadIdentity();
    void loadSessions();
    void render(new URL(location.href));
}
