import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { beforeEach, expect, test, vi } from "vitest";

/**
 * External-behaviour test for the shipped entry: it imports the compiled
 * `boot.js` (what every page loads) rather than calling `mountShell` directly,
 * so a shell that never boots fails here.
 */

const INDEX = readFileSync(resolve(process.cwd(), "src/clawhouse/static/index.html"), "utf8");
const ENTRY = "../src/clawhouse/static/boot.js";

const SESSION = "11111111-1111-4111-8111-111111111111";

function jsonResponse(payload: unknown): Response {
  return { ok: true, json: async () => payload } as unknown as Response;
}

function stubFetch(): void {
  vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url === "/api/me") return jsonResponse({ user_id: "ada@example.com" });
    if (url === "/api/sessions") return jsonResponse({ sessions: [] });
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

async function boot(): Promise<void> {
  vi.resetModules();
  await import(ENTRY);
}

beforeEach(() => {
  localStorage.clear();
  stubFetch();
  const parsed = new DOMParser().parseFromString(INDEX, "text/html");
  document.body.innerHTML = parsed.body.innerHTML;
  delete document.documentElement.dataset.themeMode;
  history.replaceState(null, "", "/chat");
});

test("the shipped entry boots the rail, the router, and the theme", async () => {
  await boot();

  expect(document.querySelector("#rail .rail-brand")?.textContent).toBe("Clawhouse");
  expect(document.querySelector("#theme-toggle")?.getAttribute("aria-pressed")).toBe("false");
  expect(document.documentElement.dataset.themeMode).toBe("dark");

  await vi.waitFor(() =>
    expect(document.querySelector("#rail-user")?.textContent).toBe("ada@example.com"),
  );
  await vi.waitFor(() => expect(document.querySelector("#screen #log")).not.toBeNull());
});

test("a nav click through the shipped entry mounts the target and pushes history", async () => {
  const pushState = vi.spyOn(history, "pushState");
  await boot();
  await vi.waitFor(() => expect(document.querySelector("#screen #log")).not.toBeNull());

  const rail = document.querySelector("#rail");
  (document.querySelector('a[href="/sessions"]') as HTMLAnchorElement).click();

  await vi.waitFor(() => expect(document.querySelector("#screen #sessions")).not.toBeNull());
  expect(location.pathname).toBe("/sessions");
  expect(pushState).toHaveBeenCalled();
  expect(document.querySelector("#rail")).toBe(rail);
});

test("the theme toggle through the shipped entry applies data-theme-mode", async () => {
  await boot();

  (document.querySelector("#theme-toggle") as HTMLButtonElement).click();
  expect(document.documentElement.dataset.themeMode).toBe("light");
  expect(localStorage.getItem("clawhouse.theme-mode")).toBe("light");
});

test("a session deep link boots straight into the chat screen", async () => {
  history.replaceState(null, "", `/chat?session=${SESSION}`);
  await boot();

  await vi.waitFor(() => expect(document.querySelector("#screen #log")).not.toBeNull());
  expect(document.querySelector("#screen #composer")).not.toBeNull();
  expect(location.search).toBe(`?session=${SESSION}`);
});
