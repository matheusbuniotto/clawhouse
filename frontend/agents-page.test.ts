import { beforeEach, expect, test, vi } from "vitest";

import type { ScreenContext } from "./shell.js";

const NOW = Date.UTC(2026, 9, 10, 12, 0, 0);

function jsonResponse(payload: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
    text: async () => JSON.stringify(payload),
  } as unknown as Response;
}

beforeEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
  vi.spyOn(Date, "now").mockReturnValue(NOW);
});

test("renders header copy and loading state while fetching agents", async () => {
  let resolveAgents!: (r: Response) => void;
  vi.stubGlobal(
    "fetch",
    () =>
      new Promise<Response>((resolve) => {
        resolveAgents = resolve;
      }),
  );

  const ctx: ScreenContext = { url: new URL("http://localhost/agents"), navigate: vi.fn() };
  const { mount } = await import("./agents.js");
  mount(document.body, ctx);

  expect(document.querySelector(".agents-page h2")?.textContent).toBe("Agentes");
  expect(document.querySelector(".agents-subtitle")?.textContent).toBe(
    "Quem está na sua equipe e o que está fazendo",
  );
  expect(document.querySelector("#btn-manage-agents")?.textContent).toBe("Gerenciar agentes");
  expect(document.querySelector("#btn-new-agent")?.textContent).toBe("Novo agente");
  expect(document.querySelector(".agents-grid .agents-loading")).not.toBeNull();

  resolveAgents(jsonResponse([]));
});

test("renders error state on fetch failure and retries when clicking retry button", async () => {
  let attempt = 0;
  vi.stubGlobal("fetch", async () => {
    attempt += 1;
    if (attempt === 1) {
      return jsonResponse({ detail: "boom" }, 500);
    }
    return jsonResponse([
      {
        id: "platform-main",
        name: "main",
        description: "Platform agent",
        system_prompt: "",
        signature_emoji: "🦀",
        is_platform: true,
        model: "databricks-claude-sonnet-4-6",
        last_active_at: null,
        last_activity: "Heartbeat & platform operations",
      },
    ]);
  });

  const ctx: ScreenContext = { url: new URL("http://localhost/agents"), navigate: vi.fn() };
  const { mount } = await import("./agents.js");
  mount(document.body, ctx);

  await vi.waitFor(() => expect(document.querySelector(".agents-error")).not.toBeNull());
  const retryBtn = document.querySelector(".btn-retry-agents") as HTMLButtonElement;
  expect(retryBtn).not.toBeNull();

  retryBtn.click();
  await vi.waitFor(() => expect(document.querySelectorAll(".agent-card").length).toBe(1));
  expect(attempt).toBe(2);
});

test("renders agent cards with avatar, model badge, relative status, activity, and open chat button", async () => {
  const twoHoursAgo = new Date(NOW - 2 * 3_600_000).toISOString();
  vi.stubGlobal("fetch", async () =>
    jsonResponse([
      {
        id: "platform-main",
        name: "main",
        description: "Default workspace orchestrator",
        system_prompt: "",
        signature_emoji: "🦀",
        is_platform: true,
        model: "databricks-claude-sonnet-4-6",
        last_active_at: twoHoursAgo,
        last_activity: "Investigated 14 high-risk transactions",
      },
      {
        id: "agent-1",
        name: "fraud",
        description: "Fraud specialist",
        system_prompt: "Check chargebacks",
        signature_emoji: "🕵️",
        is_platform: false,
        model: "databricks-claude-sonnet-4-6",
        last_active_at: null,
        last_activity: "Fraud specialist",
      },
    ]),
  );

  const ctx: ScreenContext = { url: new URL("http://localhost/agents"), navigate: vi.fn() };
  const { mount } = await import("./agents.js");
  mount(document.body, ctx);

  await vi.waitFor(() => expect(document.querySelectorAll(".agent-card").length).toBe(2));
  const cards = document.querySelectorAll<HTMLElement>(".agent-card");

  expect(cards[0].querySelector(".agent-card-avatar")?.textContent).toBe("🦀");
  expect(cards[0].querySelector(".agent-card-title")?.textContent).toBe("main");
  expect(cards[0].querySelector(".agent-card-model")?.textContent).toBe(
    "databricks-claude-sonnet-4-6",
  );
  expect(cards[0].querySelector(".agent-card-status")?.textContent).toContain("2h ago");
  expect(cards[0].querySelector(".agent-card-activity")?.textContent).toBe(
    "Investigated 14 high-risk transactions",
  );
  expect(cards[0].querySelector(".btn-open-chat")?.textContent).toBe("Abrir chat");

  expect(cards[1].querySelector(".agent-card-avatar")?.textContent).toBe("🕵️");
  expect(cards[1].querySelector(".agent-card-title")?.textContent).toBe("fraud");
  expect(cards[1].querySelector(".agent-card-status")?.textContent).toContain("Recém-criado");
  expect(cards[1].querySelector(".agent-card-activity")?.textContent).toBe("Fraud specialist");
  expect(cards[1].querySelector(".btn-open-chat")?.textContent).toBe("Abrir chat");
});

test("creates a session and navigates to chat with agent parameter when clicking Abrir chat", async () => {
  vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url === "/api/agents") {
      return jsonResponse([
        {
          id: "platform-main",
          name: "main",
          description: "Platform agent",
          system_prompt: "",
          signature_emoji: "🦀",
          is_platform: true,
          model: "databricks",
          last_active_at: null,
          last_activity: "Heartbeat & platform operations",
        },
        {
          id: "agent-1",
          name: "fraud",
          description: "Fraud specialist",
          system_prompt: "Check chargebacks",
          signature_emoji: "🕵️",
          is_platform: false,
          model: "databricks",
          last_active_at: null,
          last_activity: "Fraud specialist",
        },
      ]);
    }
    if (url === "/api/sessions" && init?.method === "POST") {
      return jsonResponse({ id: "sess-99" }, 201);
    }
    return jsonResponse({});
  });

  const navigate = vi.fn();
  const ctx: ScreenContext = { url: new URL("http://localhost/agents"), navigate };
  const { mount } = await import("./agents.js");
  mount(document.body, ctx);

  await vi.waitFor(() => expect(document.querySelectorAll(".agent-card").length).toBe(2));
  const buttons = document.querySelectorAll<HTMLButtonElement>(".btn-open-chat");

  buttons[0].click();
  await vi.waitFor(() => expect(navigate).toHaveBeenCalledWith("/chat?session=sess-99"));

  buttons[1].click();
  await vi.waitFor(() =>
    expect(navigate).toHaveBeenCalledWith("/chat?session=sess-99&agent=fraud"),
  );
});

test("creates a new custom agent via #modal-new-agent and refreshes the grid", async () => {
  const agents = [
    {
      id: "platform-main",
      name: "main",
      description: "Platform agent",
      system_prompt: "",
      signature_emoji: "🦀",
      is_platform: true,
      model: "databricks",
      last_active_at: null,
      last_activity: "Heartbeat & platform operations",
    },
  ];
  let postedBody: Record<string, unknown> | null = null;

  vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url === "/api/agents" && (!init?.method || init.method === "GET")) {
      return jsonResponse(agents);
    }
    if (url === "/api/agents" && init?.method === "POST") {
      postedBody = JSON.parse(String(init.body));
      const created = {
        id: "agent-writer",
        name: String(postedBody?.name),
        description: String(postedBody?.description),
        system_prompt: String(postedBody?.system_prompt),
        signature_emoji: String(postedBody?.signature_emoji),
        is_platform: false,
        model: "databricks",
        last_active_at: null,
        last_activity: String(postedBody?.description),
      };
      agents.push(created);
      return jsonResponse(created, 201);
    }
    return jsonResponse({});
  });

  const ctx: ScreenContext = { url: new URL("http://localhost/agents"), navigate: vi.fn() };
  const { mount } = await import("./agents.js");
  mount(document.body, ctx);

  await vi.waitFor(() => expect(document.querySelectorAll(".agent-card").length).toBe(1));
  (document.querySelector("#btn-new-agent") as HTMLButtonElement).click();

  const modal = document.querySelector("#modal-new-agent") as HTMLElement;
  expect(modal).not.toBeNull();
  const emojiInput = modal.querySelector('input[name="signature_emoji"]') as HTMLInputElement;
  expect(emojiInput.value).toBe("🤖");

  (modal.querySelector('input[name="name"]') as HTMLInputElement).value = "writer";
  emojiInput.value = "✍️";
  (modal.querySelector('input[name="description"]') as HTMLInputElement).value = "Writer agent";
  (modal.querySelector('textarea[name="system_prompt"]') as HTMLTextAreaElement).value =
    "Write docs";
  (modal.querySelector('textarea[name="soul"]') as HTMLTextAreaElement).value = "Calm tone";
  (modal.querySelector('textarea[name="context"]') as HTMLTextAreaElement).value = "Docs repo";

  modal.querySelector("form")?.dispatchEvent(new Event("submit", { cancelable: true, bubbles: true }));

  await vi.waitFor(() => expect(document.querySelector("#modal-new-agent")).toBeNull());
  expect(postedBody).toEqual({
    name: "writer",
    signature_emoji: "✍️",
    description: "Writer agent",
    system_prompt: "Write docs",
    soul: "Calm tone",
    context: "Docs repo",
  });
  await vi.waitFor(() => expect(document.querySelectorAll(".agent-card").length).toBe(2));
});

test("keeps #modal-new-agent open and shows .modal-status when POST /api/agents fails", async () => {
  vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url === "/api/agents" && init?.method === "POST") {
      return jsonResponse({ detail: "Invalid agent name" }, 422);
    }
    return jsonResponse([]);
  });

  const ctx: ScreenContext = { url: new URL("http://localhost/agents"), navigate: vi.fn() };
  const { mount } = await import("./agents.js");
  mount(document.body, ctx);

  await vi.waitFor(() => expect(document.querySelector(".agents-loading")).toBeNull());
  (document.querySelector("#btn-new-agent") as HTMLButtonElement).click();

  const modal = document.querySelector("#modal-new-agent") as HTMLElement;
  (modal.querySelector('input[name="name"]') as HTMLInputElement).value = "bad name";
  (modal.querySelector('input[name="description"]') as HTMLInputElement).value = "desc";
  (modal.querySelector('textarea[name="system_prompt"]') as HTMLTextAreaElement).value = "prompt";

  modal.querySelector("form")?.dispatchEvent(new Event("submit", { cancelable: true, bubbles: true }));

  await vi.waitFor(() =>
    expect(modal.querySelector(".modal-status")?.textContent).toContain("422"),
  );
  expect(document.querySelector("#modal-new-agent")).not.toBeNull();
  expect((modal.querySelector('button[type="submit"]') as HTMLButtonElement).disabled).toBe(false);
});

test("lists agents in #modal-manage-agents, protects main, and deletes a custom agent", async () => {
  let agents = [
    {
      id: "platform-main",
      name: "main",
      description: "Platform agent",
      system_prompt: "",
      signature_emoji: "🦀",
      is_platform: true,
      model: "databricks",
      last_active_at: null,
      last_activity: "Heartbeat & platform operations",
    },
    {
      id: "agent-123",
      name: "analyst",
      description: "Data Analyst",
      system_prompt: "Analyze data",
      signature_emoji: "📊",
      is_platform: false,
      model: "databricks",
      last_active_at: null,
      last_activity: "Data Analyst",
    },
  ];

  vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url === "/api/agents" && (!init?.method || init.method === "GET")) {
      return jsonResponse(agents);
    }
    if (url === "/api/agents/agent-123" && init?.method === "DELETE") {
      agents = agents.filter((a) => a.id !== "agent-123");
      return jsonResponse({}, 204);
    }
    return jsonResponse({});
  });

  const ctx: ScreenContext = { url: new URL("http://localhost/agents"), navigate: vi.fn() };
  const { mount } = await import("./agents.js");
  mount(document.body, ctx);

  await vi.waitFor(() => expect(document.querySelectorAll(".agent-card").length).toBe(2));
  (document.querySelector("#btn-manage-agents") as HTMLButtonElement).click();

  const modal = document.querySelector("#modal-manage-agents") as HTMLElement;
  expect(modal).not.toBeNull();
  const rows = modal.querySelectorAll(".manage-agent-row");
  expect(rows.length).toBe(2);
  expect(rows[0].querySelector(".btn-delete-agent")).toBeNull();
  const delBtn = rows[1].querySelector(".btn-delete-agent") as HTMLButtonElement;
  expect(delBtn).not.toBeNull();

  delBtn.click();

  await vi.waitFor(() => expect(document.querySelectorAll(".agent-card").length).toBe(1));
  expect(modal.querySelectorAll(".manage-agent-row").length).toBe(1);
});

test("closes active modal on close button, backdrop click, or Escape key", async () => {
  vi.stubGlobal("fetch", async () => jsonResponse([]));

  const ctx: ScreenContext = { url: new URL("http://localhost/agents"), navigate: vi.fn() };
  const { mount } = await import("./agents.js");
  mount(document.body, ctx);

  await vi.waitFor(() => expect(document.querySelector(".agents-loading")).toBeNull());

  // 1. Close button
  (document.querySelector("#btn-new-agent") as HTMLButtonElement).click();
  expect(document.querySelector("#modal-new-agent")).not.toBeNull();
  (document.querySelector("#modal-new-agent .modal-close") as HTMLButtonElement).click();
  expect(document.querySelector("#modal-new-agent")).toBeNull();

  // 2. Backdrop click
  (document.querySelector("#btn-manage-agents") as HTMLButtonElement).click();
  const backdrop = document.querySelector(".modal-backdrop") as HTMLElement;
  expect(backdrop).not.toBeNull();
  backdrop.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  expect(document.querySelector("#modal-manage-agents")).toBeNull();

  // 3. Escape key
  (document.querySelector("#btn-new-agent") as HTMLButtonElement).click();
  expect(document.querySelector("#modal-new-agent")).not.toBeNull();
  window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
  expect(document.querySelector("#modal-new-agent")).toBeNull();
});
