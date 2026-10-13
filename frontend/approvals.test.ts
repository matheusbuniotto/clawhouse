import { beforeEach, expect, test, vi } from "vitest";

const PENDING = {
  id: "appr-1",
  session_id: "sess-1",
  tool_name: "lookup",
  arguments: '{"q":"notes"}',
  status: "pending",
  created_at: "2026-10-10T12:00:00Z",
  resolved_by: null,
};

const HISTORY = {
  id: "appr-0",
  session_id: "sess-0",
  tool_name: "clock",
  arguments: "{}",
  status: "approved",
  created_at: "2026-10-10T11:00:00Z",
  resolved_by: "ada@example.com",
};

function jsonResponse(payload: unknown): Response {
  return { ok: true, json: async () => payload } as unknown as Response;
}

beforeEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

test("renders pending cards and resolved history from the approvals endpoint", async () => {
  const calls: string[] = [];
  vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
    calls.push(String(input));
    return jsonResponse({ approvals: [PENDING, HISTORY], pending: [PENDING], history: [HISTORY] });
  });

  await import("./approvals").then((module) => module.mount(document.body));
  await vi.waitFor(() => {
    expect(document.querySelectorAll(".approval-card")).toHaveLength(1);
  });

  const card = document.querySelector(".approval-card") as HTMLLIElement;
  expect(card.querySelector(".tool-name")?.textContent).toBe("lookup");
  expect(card.querySelector(".args-json")?.textContent).toBe('{"q":"notes"}');
  expect(card.querySelector(".btn-approve")?.textContent).toBe("Approve");
  expect(card.querySelector(".btn-deny")?.textContent).toBe("Deny");
  expect(card.querySelector("a.session-link")?.getAttribute("href")).toBe("/chat?session=sess-1");
  expect(card.querySelector(".when")?.textContent).toBeTruthy();

  const row = document.querySelector(".approval-history-row") as HTMLLIElement;
  expect(row.querySelector(".tool-name")?.textContent).toBe("clock");
  expect(row.querySelector(".status-badge")?.className).toBe("status-badge approved");
  expect(row.querySelector(".resolver")?.textContent).toBe("by ada@example.com");
  expect(calls).toEqual(["/api/approvals"]);
});

test("approving a pending tool posts the decision and reloads the list", async () => {
  const calls: string[] = [];
  let listCalls = 0;
  vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push(`${init?.method ?? "GET"} ${String(input)}`);
    if (String(input) === "/api/approvals" && !init?.method) {
      listCalls += 1;
      return jsonResponse(
        listCalls === 1
          ? { approvals: [PENDING], pending: [PENDING], history: [] }
          : { approvals: [HISTORY], pending: [], history: [HISTORY] },
      );
    }
    return jsonResponse({ status: "ok" });
  });

  await import("./approvals").then((module) => module.mount(document.body));
  await vi.waitFor(() => {
    expect(document.querySelectorAll(".approval-card")).toHaveLength(1);
  });

  (document.querySelector(".btn-approve") as HTMLButtonElement).click();
  await vi.waitFor(() => {
    expect(document.querySelectorAll(".approval-card")).toHaveLength(0);
  });

  expect(calls).toEqual([
    "GET /api/approvals",
    "POST /api/approvals/appr-1/approve",
    "GET /api/approvals",
  ]);
  expect(document.querySelector("#status")?.textContent).toBe("Approved lookup.");
  expect(document.querySelectorAll(".approval-history-row")).toHaveLength(1);
});

test("renders an empty state for each approvals list", async () => {
  vi.stubGlobal("fetch", async () => jsonResponse({ approvals: [], pending: [], history: [] }));

  await import("./approvals").then((module) => module.mount(document.body));
  await vi.waitFor(() => {
    expect(document.querySelectorAll(".empty")).toHaveLength(2);
  });

  expect(document.querySelector("#pending-list .empty")?.textContent).toBe("No pending approvals.");
  expect(document.querySelector("#history-list .empty")?.textContent).toBe("No approval history.");
});
