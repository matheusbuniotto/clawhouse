import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { afterEach, beforeEach, expect, test, vi } from "vitest";

const NOW = Date.UTC(2026, 9, 10, 12, 0, 0);
const HOUR = 3_600_000;

const INDEX = readFileSync(resolve(process.cwd(), "src/crabriks/static/index.html"), "utf8");

const SESSIONS = [
  { id: "s1", title: "First", created_at: new Date(NOW - HOUR).toISOString(), run_state: "running" },
  { id: "s2", title: "Second", created_at: new Date(NOW - 3 * 24 * HOUR).toISOString(), run_state: "idle" },
];

function jsonResponse(payload: unknown): Response {
  return { ok: true, json: async () => payload } as unknown as Response;
}

function loadMarkup(): void {
  const parsed = new DOMParser().parseFromString(INDEX, "text/html");
  document.body.innerHTML = parsed.body.innerHTML;
  delete document.documentElement.dataset.themeMode;
}

function stubFetch(): void {
  vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url === "/api/me") return jsonResponse({ user_id: "ada@example.com" });
    if (url === "/api/sessions") return jsonResponse({ sessions: SESSIONS });
    if (url === "/api/models") return jsonResponse({ models: [] });
    if (url.endsWith("/transcript")) return jsonResponse({ entries: [] });
    if (url === "/api/status") {
      return jsonResponse({
        auth: { user_id: "ada@example.com", token_present: false, auth_type: "forwarded" },
        connection: { workspace_host: null, serving_endpoint: null, store_type: "memory" },
        sessions: [],
        log_tail_url: "",
      });
    }
    return jsonResponse({});
  });
}

async function mount(): Promise<void> {
  vi.resetModules();
  const { mountShell } = await import("./shell");
  mountShell(document.body);
}

beforeEach(() => {
  localStorage.clear();
  stubFetch();
  loadMarkup();
  vi.spyOn(Date, "now").mockReturnValue(NOW);
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

test("renders the persistent rail, caller identity, and dark-by-default theme", async () => {
  await mount();

  expect(document.querySelector("#rail .rail-brand")?.textContent).toBe("Crabriks");
  expect(document.querySelector("#rail-collapse")?.getAttribute("aria-expanded")).toBe("true");
  expect(
    [...document.querySelectorAll("#rail .rail-nav a[data-nav]")].map((link) =>
      link.getAttribute("href"),
    ),
  ).toEqual(["/chat", "/sessions", "/approvals", "/status"]);
  expect(document.querySelector("#rail .rail-heading")?.textContent).toBe("Sessions");
  expect(document.querySelector("#rail-search")).not.toBeNull();
  expect(document.querySelector("#rail-new")).not.toBeNull();
  expect(document.querySelector("#rail-handle")).not.toBeNull();
  expect(document.querySelector("#theme-toggle")?.getAttribute("aria-pressed")).toBe("false");
  expect(document.documentElement.dataset.themeMode).toBe("dark");

  await vi.waitFor(() =>
    expect(document.querySelector("#rail-user")?.textContent).toBe("ada@example.com"),
  );
});

test("the theme toggle persists the mode and keeps dark the default", async () => {
  await mount();
  const toggle = document.querySelector("#theme-toggle") as HTMLButtonElement;

  expect(document.documentElement.dataset.themeMode).toBe("dark");
  expect(localStorage.getItem("crabriks.theme-mode")).toBe("dark");

  toggle.click();
  expect(document.documentElement.dataset.themeMode).toBe("light");
  expect(localStorage.getItem("crabriks.theme-mode")).toBe("light");
  expect(toggle.getAttribute("aria-pressed")).toBe("true");

  toggle.click();
  expect(document.documentElement.dataset.themeMode).toBe("dark");
  expect(localStorage.getItem("crabriks.theme-mode")).toBe("dark");
});

test("the rail groups sessions with relative times and a running pulse", async () => {
  await mount();

  await vi.waitFor(() => expect(document.querySelectorAll(".rail-session")).toHaveLength(2));
  expect(
    [...document.querySelectorAll(".rail-group-title")].map((node) => node.textContent),
  ).toEqual(["Today", "This week"]);

  const first = document.querySelector('.rail-session[data-id="s1"]') as HTMLElement;
  expect(first.querySelector(".rail-session-title")?.textContent).toBe("First");
  expect(first.querySelector(".rail-session-time")?.textContent).toBe("1h ago");
  expect(first.querySelector(".rail-session-pulse")?.getAttribute("data-state")).toBe("running");
  expect(document.querySelector('.rail-session[data-id="s2"] .rail-session-pulse')).toBeNull();
});

test("the rail search filters session rows", async () => {
  await mount();
  await vi.waitFor(() => expect(document.querySelectorAll(".rail-session")).toHaveLength(2));

  const search = document.querySelector("#rail-search") as HTMLInputElement;
  search.value = "sec";
  search.dispatchEvent(new Event("input"));

  expect((document.querySelector('.rail-session[data-id="s1"]') as HTMLElement).hidden).toBe(true);
  expect((document.querySelector('.rail-session[data-id="s2"]') as HTMLElement).hidden).toBe(false);
});

test("clicking a nav link swaps the screen in place without a document reload", async () => {
  const pushState = vi.spyOn(history, "pushState");
  await mount();
  await vi.waitFor(() => expect(document.querySelector("#screen #log")).not.toBeNull());

  const rail = document.querySelector("#rail");
  (window as unknown as { __shellAlive?: string }).__shellAlive = "yes";
  (document.querySelector('a[href="/sessions"]') as HTMLAnchorElement).click();

  await vi.waitFor(() => expect(document.querySelector("#screen #sessions")).not.toBeNull());
  expect(location.pathname).toBe("/sessions");
  expect(pushState).toHaveBeenCalled();
  expect(document.querySelector("#rail")).toBe(rail);
  expect((window as unknown as { __shellAlive?: string }).__shellAlive).toBe("yes");
  expect(document.querySelector("#nav-sessions")?.getAttribute("aria-current")).toBe("page");
});

test("the new-session action and rail session links navigate in place", async () => {
  await mount();
  await vi.waitFor(() => expect(document.querySelectorAll(".rail-session")).toHaveLength(2));

  (document.querySelector("#rail-new") as HTMLButtonElement).click();
  await vi.waitFor(() => expect(document.querySelector("#screen #start")).not.toBeNull());
  expect(location.pathname).toBe("/new");

  (document.querySelector('.rail-session[data-id="s1"]') as HTMLAnchorElement).click();
  await vi.waitFor(() => expect(document.querySelector("#screen #log")).not.toBeNull());
  expect(location.pathname).toBe("/chat");
  expect(location.search).toBe("?session=s1");
});

test("clicking the delete button on a rail session calls DELETE and refreshes the list", async () => {
  let deleted = false;
  vi.spyOn(window, "confirm").mockReturnValue(true);
  vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url === "/api/sessions/s1" && init?.method === "DELETE") {
      deleted = true;
      return { ok: true, status: 204 } as Response;
    }
    if (url === "/api/sessions") {
      return jsonResponse({ sessions: deleted ? [SESSIONS[1]] : SESSIONS });
    }
    if (url === "/api/me") return jsonResponse({ user_id: "ada@example.com" });
    if (url === "/api/models") return jsonResponse({ models: [] });
    if (url.endsWith("/transcript")) return jsonResponse({ entries: [] });
    return jsonResponse({});
  });

  await mount();
  await vi.waitFor(() => expect(document.querySelectorAll(".rail-session")).toHaveLength(2));

  const delBtn = document.querySelector(
    '.rail-session[data-id="s1"] .rail-session-delete',
  ) as HTMLButtonElement;
  expect(delBtn).not.toBeNull();
  delBtn.click();

  await vi.waitFor(() => expect(deleted).toBe(true));
  await vi.waitFor(() => expect(document.querySelectorAll(".rail-session")).toHaveLength(1));
  expect(document.querySelector('.rail-session[data-id="s1"]')).toBeNull();
  expect(document.querySelector('.rail-session[data-id="s2"]')).not.toBeNull();
});

test("back and forward re-render the screen from the URL", async () => {
  await mount();
  await vi.waitFor(() => expect(document.querySelector("#screen #log")).not.toBeNull());

  history.replaceState(null, "", "/status");
  window.dispatchEvent(new PopStateEvent("popstate"));

  await vi.waitFor(() => expect(document.querySelector("#screen #stat-user")).not.toBeNull());
  expect(document.querySelector("#nav-status")?.getAttribute("aria-current")).toBe("page");
});

test("the rail collapses and expands", async () => {
  await mount();
  const shell = document.querySelector("#shell") as HTMLElement;
  const collapse = document.querySelector("#rail-collapse") as HTMLButtonElement;

  expect(shell.hasAttribute("data-collapsed")).toBe(false);
  collapse.click();
  expect(shell.hasAttribute("data-collapsed")).toBe(true);
  expect(collapse.getAttribute("aria-expanded")).toBe("false");
  collapse.click();
  expect(shell.hasAttribute("data-collapsed")).toBe(false);
  expect(collapse.getAttribute("aria-expanded")).toBe("true");
});

test("a collapsed rail exposes an expand affordance that restores it", async () => {
  await mount();
  const shell = document.querySelector("#shell") as HTMLElement;
  const collapse = document.querySelector("#rail-collapse") as HTMLButtonElement;
  const expand = document.querySelector("#rail-expand") as HTMLButtonElement;

  expect(shell.hasAttribute("data-collapsed")).toBe(false);
  expect(expand.getAttribute("aria-expanded")).toBe("false");

  collapse.click();
  expect(shell.hasAttribute("data-collapsed")).toBe(true);
  expect(expand.getAttribute("aria-expanded")).toBe("true");

  expand.click();
  expect(shell.hasAttribute("data-collapsed")).toBe(false);
  expect(expand.getAttribute("aria-expanded")).toBe("false");
  expect(collapse.getAttribute("aria-expanded")).toBe("true");
});

test("dragging the rail handle resizes the rail and persists the width", async () => {
  await mount();
  const shell = document.querySelector("#shell") as HTMLElement;
  const handle = document.querySelector("#rail-handle") as HTMLElement;

  handle.dispatchEvent(
    new MouseEvent("pointerdown", { clientX: 280, bubbles: true, cancelable: true }),
  );
  expect(shell.hasAttribute("data-resizing")).toBe(true);

  window.dispatchEvent(new MouseEvent("pointermove", { clientX: 360 }));
  expect(document.documentElement.style.getPropertyValue("--rail-width")).toBe("360px");
  expect(localStorage.getItem("crabriks.rail-width")).toBe("360");

  window.dispatchEvent(new MouseEvent("pointermove", { clientX: 10 }));
  expect(document.documentElement.style.getPropertyValue("--rail-width")).toBe("180px");

  window.dispatchEvent(new MouseEvent("pointerup"));
  expect(shell.hasAttribute("data-resizing")).toBe(false);
});

test("a stored rail width is restored on mount", async () => {
  localStorage.setItem("crabriks.rail-width", "320");
  await mount();
  expect(document.documentElement.style.getPropertyValue("--rail-width")).toBe("320px");
});
