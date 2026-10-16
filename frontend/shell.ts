import {
  SESSION_RENAMED,
  UNTITLED,
  editTitle,
  el,
  isRunning,
  relativeTime,
  renameSession,
  type ActivityState,
  type SessionRenamed,
} from "./dom.js";

export interface ScreenContext {
  url: URL;
  navigate: (href: string, options?: { replace?: boolean }) => void;
}

interface ScreenModule {
  mount(root: HTMLElement, ctx: ScreenContext): void;
}

interface RailSession {
  id: string;
  title: string;
  created_at: string;
  run_state?: ActivityState;
}

const THEME_KEY = "clawhouse.theme-mode";
const RAIL_WIDTH_KEY = "clawhouse.rail-width";
const MIN_RAIL_WIDTH = 180;
const MAX_RAIL_WIDTH = 480;

const TITLES: Record<string, string> = {
  "/": "Clawhouse",
  "/chat": "Clawhouse",
  "/sessions": "Clawhouse · Sessions",
  "/new": "Clawhouse · New session",
  "/approvals": "Clawhouse · Approvals",
  "/status": "Clawhouse · Status",
  "/jobs": "Clawhouse · Jobs",
};

const ROUTES: Record<string, () => Promise<ScreenModule>> = {
  "/": () => import("./chat.js"),
  "/chat": () => import("./chat.js"),
  "/sessions": () => import("./sessions.js"),
  "/new": () => import("./new.js"),
  "/approvals": () => import("./approvals.js"),
  "/status": () => import("./status.js"),
  "/jobs": () => import("./jobspage.js"),
};

function requireElement<T extends Element>(
  parent: ParentNode,
  selector: string,
): T {
  const node = parent.querySelector<T>(selector);
  if (!node) throw new Error(`shell markup is missing ${selector}`);
  return node;
}

function normalize(path: string): string {
  return path.length > 1 && path.endsWith("/") ? path.slice(0, -1) : path;
}

function groupFor(iso: string, now: number): string {
  const days = Math.floor((now - new Date(iso).getTime()) / 86_400_000);
  if (days <= 0) return "Today";
  if (days === 1) return "Yesterday";
  if (days < 7) return "This week";
  return "Earlier";
}

function clampRailWidth(width: number): number {
  return Math.min(MAX_RAIL_WIDTH, Math.max(MIN_RAIL_WIDTH, Math.round(width)));
}

/**
 * Bind the persistent shell: rail, theme, session list, drag-resize, and the
 * History-API router. The rail markup is served with the document; this only
 * wires it up and mounts the screen for the current path into `#screen`.
 */
export function mountShell(root: ParentNode = document): void {
  const shell = requireElement<HTMLElement>(root, "#shell");
  const screen = requireElement<HTMLElement>(root, "#screen");
  const sessionList = requireElement<HTMLElement>(root, "#rail-sessions");
  const user = requireElement<HTMLElement>(root, "#rail-user");
  const search = requireElement<HTMLInputElement>(root, "#rail-search");
  const themeToggle = requireElement<HTMLButtonElement>(root, "#theme-toggle");
  const collapse = requireElement<HTMLButtonElement>(root, "#rail-collapse");
  const expand = requireElement<HTMLButtonElement>(root, "#rail-expand");
  const newButton = requireElement<HTMLButtonElement>(root, "#rail-new");
  const handle = requireElement<HTMLElement>(root, "#rail-handle");

  function navigate(href: string, options: { replace?: boolean } = {}): void {
    const url = new URL(href, location.href);
    const target = `${url.pathname}${url.search}`;
    if (options.replace) history.replaceState(null, "", target);
    else history.pushState(null, "", target);
    void render(url);
    void loadSessions();
  }

  let renderSeq = 0;

  async function render(url: URL): Promise<void> {
    const path = normalize(url.pathname);
    const loader = ROUTES[path] ?? ROUTES["/"];
    // Only the latest navigation mounts: a slower, older import must not clobber it.
    const seq = ++renderSeq;
    const module = await loader();
    if (seq !== renderSeq) return;
    document.title = TITLES[path] ?? "Clawhouse";
    screen.replaceChildren();
    module.mount(screen, { url, navigate });
    updateActive(path, url);
  }

  function updateActive(path: string, url: URL): void {
    for (const link of shell.querySelectorAll<HTMLAnchorElement>(
      ".rail-nav a[data-nav]",
    )) {
      const href = link.getAttribute("href")?.split("?")[0];
      if (href === path || (path === "/" && href === "/chat")) {
        link.setAttribute("aria-current", "page");
      } else {
        link.removeAttribute("aria-current");
      }
    }
    const session = url.searchParams.get("session");
    for (const row of sessionList.querySelectorAll<HTMLAnchorElement>(
      ".rail-session",
    )) {
      if (session !== null && row.dataset.id === session) {
        row.setAttribute("aria-current", "page");
      } else {
        row.removeAttribute("aria-current");
      }
    }
  }

  function onClick(event: MouseEvent): void {
    if (event.defaultPrevented || event.button !== 0) return;
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey)
      return;
    const anchor = (event.target as Element | null)?.closest?.("a[data-nav]");
    if (!(anchor instanceof HTMLAnchorElement)) return;
    const href = anchor.getAttribute("href");
    if (!href || !href.startsWith("/")) return;
    event.preventDefault();
    navigate(href);
  }

  function onPopState(): void {
    const url = new URL(location.href);
    void render(url);
    void loadSessions();
  }

  function sessionRow(item: RailSession): HTMLAnchorElement {
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
    renameBtn.setAttribute(
      "aria-label",
      `Rename session ${currentTitle || item.id}`,
    );
    renameBtn.title = "Rename session";
    renameBtn.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      if (titleSpan.hidden) return;
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
    delBtn.setAttribute(
      "aria-label",
      `Delete session ${currentTitle || item.id}`,
    );
    delBtn.title = "Delete session";
    delBtn.addEventListener("click", async (e) => {
      e.preventDefault();
      e.stopPropagation();
      if (!confirm(`Delete "${currentTitle || UNTITLED}"?`)) return;
      try {
        const res = await fetch(`/api/sessions/${item.id}`, {
          method: "DELETE",
        });
        if (res.ok || res.status === 204) {
          const currentSession = new URL(location.href).searchParams.get(
            "session",
          );
          if (currentSession === item.id) {
            navigate("/chat");
          }
          void loadSessions();
        }
      } catch {
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

  function renderSessions(items: RailSession[]): void {
    sessionList.replaceChildren();
    if (items.length === 0) {
      sessionList.append(el("p", "rail-empty", "No sessions yet."));
      return;
    }
    const now = Date.now();
    const groups = new Map<string, RailSession[]>();
    for (const item of items) {
      const key = groupFor(item.created_at, now);
      const bucket = groups.get(key);
      if (bucket) bucket.push(item);
      else groups.set(key, [item]);
    }
    for (const [title, group] of groups) {
      const container = el("div", "rail-group");
      container.append(el("p", "rail-group-title", title));
      for (const item of group) container.append(sessionRow(item));
      sessionList.append(container);
    }
  }

  async function loadSessions(): Promise<void> {
    try {
      const response = await fetch("/api/sessions");
      if (!response.ok) {
        renderSessions([]);
        return;
      }
      const body = (await response.json()) as { sessions?: RailSession[] };
      renderSessions(body.sessions ?? []);
    } catch {
      renderSessions([]);
    }
  }

  async function loadIdentity(): Promise<void> {
    try {
      const response = await fetch("/api/me");
      if (!response.ok) {
        user.textContent = "Not signed in";
        return;
      }
      const body = (await response.json()) as { user_id: string };
      user.textContent = body.user_id;
    } catch {
      user.textContent = "Not signed in";
    }
  }

  function syncTheme(mode: string): void {
    document.documentElement.dataset.themeMode = mode;
    themeToggle.setAttribute("aria-pressed", String(mode === "light"));
    const label = themeToggle.querySelector<HTMLElement>(".rail-theme-label");
    if (label) label.textContent = mode === "light" ? "Light" : "Dark";
  }

  function applyRailWidth(width: number): void {
    const clamped = clampRailWidth(width);
    document.documentElement.style.setProperty("--rail-width", `${clamped}px`);
    localStorage.setItem(RAIL_WIDTH_KEY, String(clamped));
  }

  function startResize(event: MouseEvent): void {
    if (shell.hasAttribute("data-collapsed")) return;
    event.preventDefault();
    shell.setAttribute("data-resizing", "");
    const left = shell.getBoundingClientRect().left;

    function onMove(move: MouseEvent): void {
      applyRailWidth(move.clientX - left);
    }
    function onEnd(): void {
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
    const next =
      document.documentElement.dataset.themeMode === "light" ? "dark" : "light";
    localStorage.setItem(THEME_KEY, next);
    syncTheme(next);
  });

  search.addEventListener("input", () => {
    const term = search.value.trim().toLowerCase();
    for (const row of sessionList.querySelectorAll<HTMLElement>(
      ".rail-session",
    )) {
      row.hidden = term !== "" && !(row.dataset.title ?? "").includes(term);
    }
  });

  newButton.addEventListener("click", () => navigate("/new"));

  function setCollapsed(collapsed: boolean): void {
    if (collapsed) shell.setAttribute("data-collapsed", "");
    else shell.removeAttribute("data-collapsed");
    collapse.setAttribute("aria-expanded", String(!collapsed));
    expand.setAttribute("aria-expanded", String(collapsed));
  }

  collapse.addEventListener("click", () =>
    setCollapsed(!shell.hasAttribute("data-collapsed")),
  );
  expand.addEventListener("click", () => setCollapsed(false));
  handle.addEventListener("pointerdown", startResize);
  shell.addEventListener("click", onClick);
  window.addEventListener("popstate", onPopState);
  window.addEventListener("clawhouse:session-deleted", () => {
    void loadSessions();
  });
  window.addEventListener(SESSION_RENAMED, (event) => {
    const detail = (event as CustomEvent<SessionRenamed>).detail;
    if (!detail) return;
    for (const row of sessionList.querySelectorAll<HTMLElement>(
      ".rail-session",
    )) {
      if (row.dataset.id === detail.id) {
        row.dataset.title = detail.title.toLowerCase();
        const titleEl = row.querySelector<HTMLElement>(".rail-session-title");
        if (titleEl) titleEl.textContent = detail.title || UNTITLED;
      }
    }
  });

  const storedWidth = Number(localStorage.getItem(RAIL_WIDTH_KEY));
  if (Number.isFinite(storedWidth) && storedWidth > 0)
    applyRailWidth(storedWidth);
  const initialMode =
    localStorage.getItem(THEME_KEY) === "light" ? "light" : "dark";
  localStorage.setItem(THEME_KEY, initialMode);
  syncTheme(initialMode);
  void loadIdentity();
  void loadSessions();
  void render(new URL(location.href));
}
