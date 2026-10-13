import { beforeEach, expect, test, vi } from "vitest";

const DATA = {
  auth: { user_id: "ada@example.com", token_present: true, auth_type: "forwarded" },
  connection: {
    workspace_host: "https://adb-1.azuredatabricks.net",
    serving_endpoint: "databricks-meta-llama",
    store_type: "memory",
  },
  sessions: [
    {
      id: "sess-1",
      title: "First",
      created_at: "2026-10-10T12:00:00Z",
      run_state: "running",
    },
  ],
  log_tail_url: "https://adb-1.azuredatabricks.net/#job/logs",
};

function jsonResponse(payload: unknown): Response {
  return { ok: true, json: async () => payload } as unknown as Response;
}

beforeEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

test("renders the connection snapshot, run-state badges, and log tail link", async () => {
  vi.stubGlobal("fetch", async () => jsonResponse(DATA));

  await import("./status").then((module) => module.mount(document.body));
  await vi.waitFor(() => {
    expect(document.querySelector("#stat-user")?.textContent).toBe("ada@example.com");
  });

  expect(document.querySelector("#stat-auth")?.textContent).toBe("FORWARDED");
  expect(document.querySelector("#stat-token")?.textContent).toBe("Present (forwarded)");
  expect(document.querySelector("#stat-workspace")?.textContent).toBe(
    "https://adb-1.azuredatabricks.net",
  );
  expect(document.querySelector("#stat-model")?.textContent).toBe("databricks-meta-llama");
  expect(document.querySelector("#stat-store")?.textContent).toBe("In-Memory Store");

  const row = document.querySelector(".session-status-row") as HTMLLIElement;
  expect(row.querySelector(".session-link")?.getAttribute("href")).toBe("/chat?session=sess-1");
  expect(row.querySelector(".session-link")?.textContent).toBe("First");
  expect(row.querySelector(".status-badge")?.className).toBe("status-badge running");
  expect(document.querySelector("#log-tail-link")?.getAttribute("href")).toBe(
    "https://adb-1.azuredatabricks.net/#job/logs",
  );
});

test("renders an empty state when there are no sessions", async () => {
  vi.stubGlobal("fetch", async () => jsonResponse({ ...DATA, sessions: [] }));

  await import("./status").then((module) => module.mount(document.body));
  await vi.waitFor(() => {
    expect(document.querySelectorAll(".empty")).toHaveLength(1);
  });

  expect(document.querySelector("#sessions-list .empty")?.textContent).toBe("No sessions yet.");
});

test("reports a failed status request inline", async () => {
  vi.stubGlobal("fetch", async () => ({ ok: false, json: async () => ({}) }) as unknown as Response);

  await import("./status").then((module) => module.mount(document.body));
  await vi.waitFor(() => {
    expect(document.querySelector("#status")?.textContent).toBe("The status could not be loaded.");
  });
});

test("renders scheduled automations and handles cancel action", async () => {
  const schedulesData = [
    {
      id: "sch-1",
      session_id: "sess-1",
      cron_expression: "*/15 * * * *",
      prompt: "Check Lakeflow jobs status",
      status: "active",
      next_run_at: "2026-10-12T12:15:00Z",
      created_at: "2026-10-12T12:00:00Z",
    },
  ];

  vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/api/status")) return jsonResponse(DATA);
    if (url.includes("/api/schedules/sch-1")) return { ok: true } as Response;
    if (url.includes("/api/schedules")) return jsonResponse(schedulesData);
    return { ok: false } as Response;
  });

  await import("./status").then((module) => module.mount(document.body));

  await vi.waitFor(() => {
    expect(document.querySelector(".schedule-cron")?.textContent).toBe("*/15 * * * *");
    expect(document.querySelector(".schedule-prompt")?.textContent).toBe(
      "Check Lakeflow jobs status",
    );
    expect(document.querySelector(".schedule-badge")?.textContent).toBe("active");
  });

  const cancelBtn = document.querySelector(".btn-cancel-schedule") as HTMLButtonElement;
  expect(cancelBtn).not.toBeNull();
  cancelBtn.click();
});
