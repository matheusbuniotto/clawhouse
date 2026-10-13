import { beforeEach, expect, test, vi } from "vitest";

import type { ScreenContext } from "./shell.js";

function context(): ScreenContext {
  return { url: new URL("http://localhost/new"), navigate: vi.fn() };
}

function jsonResponse(payload: unknown): Response {
  return { ok: true, json: async () => payload } as unknown as Response;
}

beforeEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

test("renders custom agents list and deletes agent by ID", async () => {
  const agents = [
    {
      id: "platform-main",
      name: "main",
      description: "Platform agent",
      system_prompt: "",
      is_platform: true,
    },
    {
      id: "agent-123",
      name: "analyst",
      description: "Data Analyst",
      system_prompt: "Analyst prompt",
      is_platform: false,
    },
  ];

  const fetchCalls: { url: string; method?: string }[] = [];
  vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    fetchCalls.push({ url, method: init?.method ?? "GET" });
    if (url === "/api/agents" && (!init || init.method === "GET")) {
      return jsonResponse(agents);
    }
    if (url === "/api/agents/agent-123" && init?.method === "DELETE") {
      return { ok: true, status: 204 } as Response;
    }
    return jsonResponse({});
  });

  await import("./new").then((module) => module.mount(document.body, context()));
  await vi.waitFor(() => expect(document.querySelector(".agent-name")).not.toBeNull());

  expect(document.querySelector(".agent-name")?.textContent).toBe("@analyst");
  expect(document.querySelector(".agent-desc")?.textContent).toBe("Data Analyst");

  // Click delete button
  const delBtn = document.querySelector(".btn-delete-agent") as HTMLButtonElement;
  delBtn.click();

  await vi.waitFor(() => {
    const deleteCall = fetchCalls.find(
      (c) => c.url === "/api/agents/agent-123" && c.method === "DELETE"
    );
    expect(deleteCall).toBeDefined();
  });
});

test("creates a new custom agent and refreshes list", async () => {
  let created = false;
  vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url === "/api/agents" && (!init || init.method === "GET")) {
      if (created) {
        return jsonResponse([
          {
            id: "agent-created",
            name: "writer",
            description: "Writer agent",
            system_prompt: "Write docs",
            is_platform: false,
          },
        ]);
      }
      return jsonResponse([]);
    }
    if (url === "/api/agents" && init?.method === "POST") {
      created = true;
      return jsonResponse({
        id: "agent-created",
        name: "writer",
        description: "Writer agent",
        system_prompt: "Write docs",
        is_platform: false,
      });
    }
    return jsonResponse({});
  });

  await import("./new").then((module) => module.mount(document.body, context()));
  await vi.waitFor(() => expect(document.querySelector(".empty-agents")).not.toBeNull());

  const form = document.querySelector(".create-agent-form") as HTMLFormElement;
  const inputs = form.querySelectorAll<HTMLInputElement | HTMLTextAreaElement>("input, textarea");
  // inputs: [nameInput, emojiInput, descInput, promptArea, soulArea, contextArea]
  inputs[0].value = "writer";
  inputs[1].value = "✍️";
  inputs[2].value = "Writer agent";
  inputs[3].value = "Write docs";

  form.dispatchEvent(new Event("submit", { cancelable: true, bubbles: true }));

  await vi.waitFor(() => expect(document.querySelector(".agent-name")?.textContent).toBe("@writer"));
});

test("renders agent picker cards and selects agent", async () => {
  const agents = [
    {
      id: "platform-main",
      name: "main",
      description: "Platform agent",
      system_prompt: "",
      is_platform: true,
      signature_emoji: "🦀",
    },
    {
      id: "agent-123",
      name: "analyst",
      description: "Data Analyst",
      system_prompt: "Analyst prompt",
      is_platform: false,
      signature_emoji: "📊",
    },
  ];

  vi.stubGlobal("fetch", async () => jsonResponse(agents));

  await import("./new").then((module) => module.mount(document.body, context()));
  await vi.waitFor(() => expect(document.querySelectorAll(".agent-card").length).toBe(2));

  const cards = document.querySelectorAll<HTMLElement>(".agent-card");
  expect(cards[0].textContent).toContain("@main");
  expect(cards[1].textContent).toContain("@analyst");

  // Click analyst card
  cards[1].click();
  expect(document.querySelector("#active-agent-desc")?.textContent).toContain("📊 analyst");
});
