import { beforeEach, expect, test, vi } from "vitest";

const SESSIONS = [
  { id: "s1", title: "Alpha Analytics", created_at: "2026-10-15T10:00:00Z" },
  { id: "s2", title: "Lakeflow Pipeline", created_at: "2026-10-14T10:00:00Z" },
];

function jsonResponse(payload: unknown): Response {
  return { ok: true, status: 200, json: async () => payload } as unknown as Response;
}

beforeEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

test("filters sessions list and updates counter", async () => {
  vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
    if (String(input) === "/api/sessions") {
      return jsonResponse({ sessions: SESSIONS });
    }
    return jsonResponse({});
  });

  const { mount } = await import("./sessions");
  mount(document.body);

  await vi.waitFor(() => expect(document.querySelectorAll(".session")).toHaveLength(2));

  const search = document.querySelector("#sessions-search") as HTMLInputElement;
  const count = document.querySelector("#sessions-count") as HTMLElement;
  expect(search).not.toBeNull();
  expect(count).not.toBeNull();
  expect(count.textContent).toContain("2");

  search.value = "k";
  search.dispatchEvent(new Event("input", { bubbles: true }));

  const visible = [...document.querySelectorAll<HTMLElement>(".session")].filter(
    (row) => !row.hidden,
  );
  expect(visible).toHaveLength(1);
  expect(visible[0].querySelector(".session-link")?.textContent).toBe("Lakeflow Pipeline");
  expect(count.textContent).toContain("1");
});

test("executes inline rename and clear actions on sessions page", async () => {
  const calls: { url: string; method: string; body?: string }[] = [];
  vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    calls.push({ url, method, body: init?.body as string | undefined });
    if (url === "/api/sessions" && method === "GET") {
      return jsonResponse({ sessions: SESSIONS });
    }
    if (url === "/api/sessions/s1" && method === "PATCH") {
      const sent = JSON.parse(String(init?.body)) as { title: string };
      return jsonResponse({ id: "s1", title: sent.title, created_at: SESSIONS[0].created_at });
    }
    if (url === "/api/sessions/s1/clear" && method === "POST") {
      return jsonResponse({ cleared: true });
    }
    return jsonResponse({});
  });
  const confirm = vi.fn(() => true);
  vi.stubGlobal("confirm", confirm);

  const renamed: unknown[] = [];
  window.addEventListener("clawhouse:session-renamed", (event) =>
    renamed.push((event as CustomEvent).detail),
  );

  const { mount } = await import("./sessions");
  mount(document.body);

  await vi.waitFor(() => expect(document.querySelectorAll(".session")).toHaveLength(2));

  const firstRow = document.querySelector(".session") as HTMLElement;
  const renameBtn = firstRow.querySelector(".btn-rename-session") as HTMLButtonElement;
  const clearBtn = firstRow.querySelector(".btn-clear-session") as HTMLButtonElement;
  expect(renameBtn).not.toBeNull();
  expect(clearBtn).not.toBeNull();

  renameBtn.click();
  const input = firstRow.querySelector("input.title-input") as HTMLInputElement;
  expect(input).not.toBeNull();
  expect(input.value).toBe("Alpha Analytics");
  input.value = "Beta Reporting";
  input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));

  await vi.waitFor(() =>
    expect(firstRow.querySelector(".session-link")?.textContent).toBe("Beta Reporting"),
  );
  expect(renamed).toEqual([{ id: "s1", title: "Beta Reporting" }]);

  clearBtn.click();
  await vi.waitFor(() => expect(firstRow.dataset.cleared).toBe("true"));
  expect(
    calls.some((call) => call.url === "/api/sessions/s1/clear" && call.method === "POST"),
  ).toBe(true);
  expect(confirm).toHaveBeenCalledTimes(1);
  expect(document.querySelectorAll(".session")).toHaveLength(2);
});

test("search of 2 characters replaces the session list", async () => {
  const calls: string[] = [];
  vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
    const url = String(input);
    calls.push(url);
    if (url === "/api/sessions") return jsonResponse({ sessions: SESSIONS });
    if (url.startsWith("/api/search?q=")) {
      return jsonResponse({
        results: [
          {
            session_id: "s2",
            role: "user",
            excerpt: "nightly partition",
            created_at: "2026-10-14T10:00:00Z",
          },
        ],
      });
    }
    return jsonResponse({});
  });
  const { mount } = await import("./sessions");
  mount(document.body);
  await vi.waitFor(() => expect(document.querySelectorAll(".session")).toHaveLength(2));
  const search = document.querySelector("#sessions-search") as HTMLInputElement;
  search.value = "ni";
  search.dispatchEvent(new Event("input", { bubbles: true }));
  await vi.waitFor(() => expect(calls.some((url) => url.startsWith("/api/search?q=ni"))).toBe(true));
  await vi.waitFor(() =>
    expect(document.querySelector(".session-link")?.textContent).toBe("nightly partition"),
  );
  expect(document.querySelectorAll(".session")).toHaveLength(1);
});

test("search failure keeps the previous list", async () => {
  vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url === "/api/sessions") return jsonResponse({ sessions: SESSIONS });
    return { ok: false, status: 500, json: async () => ({}) } as unknown as Response;
  });
  const { mount } = await import("./sessions");
  mount(document.body);
  await vi.waitFor(() => expect(document.querySelectorAll(".session")).toHaveLength(2));
  const search = document.querySelector("#sessions-search") as HTMLInputElement;
  search.value = "ni";
  search.dispatchEvent(new Event("input", { bubbles: true }));
  await vi.waitFor(() => {
    const error = document.querySelector(".sessions-error") as HTMLElement;
    expect(error.hidden).toBe(false);
  });
  expect(document.querySelectorAll(".session")).toHaveLength(2);
  expect(document.querySelector(".session-link")?.textContent).toBe("Alpha Analytics");
});
