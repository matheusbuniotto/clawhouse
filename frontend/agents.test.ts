import { beforeEach, expect, test, vi } from "vitest";

import type { ScreenContext } from "./shell.js";

const SESSION = "11111111-1111-4111-8111-111111111111";

function context(): ScreenContext {
  return { url: new URL(`http://localhost/chat?session=${SESSION}`), navigate: vi.fn() };
}

function jsonResponse(payload: unknown): Response {
  return { ok: true, json: async () => payload } as unknown as Response;
}

function streamResponse(frames: string): Response {
  const bytes = new TextEncoder().encode(frames);
  let sent = false;
  return {
    ok: true,
    status: 200,
    body: {
      getReader: () => ({
        read: async () =>
          sent ? { done: true, value: undefined } : ((sent = true), { done: false, value: bytes }),
      }),
    },
  } as unknown as Response;
}

const AGENTS = [
  { name: "main", signature_emoji: "🦀" },
  { name: "fraud", signature_emoji: "🕵️" },
];

beforeEach(() => {
  vi.unstubAllGlobals();
  sessionStorage.clear();
  document.body.innerHTML = "";
});

test("an agent frame heads the streamed reply with handle, emoji and model", async () => {
  const frames = [
    'event: agent\ndata: {"type":"agent","agent_id":"fraud","name":"fraud","emoji":"🕵️","model":"gpt-x"}\n\n',
    'event: token\ndata: {"text":"found 3"}\n\n',
    'event: done\ndata: {"status":"ok","reply":"found 3"}\n\n',
  ].join("");
  vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.endsWith("/turns") && init?.method === "POST") return streamResponse(frames);
    if (url.endsWith("/transcript")) return jsonResponse({ entries: [] });
    if (url === "/api/agents") return jsonResponse(AGENTS);
    return jsonResponse({ models: [] });
  });

  await import("./chat").then((module) => module.mount(document.body, context()));
  await vi.waitFor(() => expect(document.querySelector(".empty")).not.toBeNull());
  (document.querySelector("#message") as HTMLTextAreaElement).value = "@fraud chargebacks";
  document
    .querySelector("#composer")
    ?.dispatchEvent(new Event("submit", { cancelable: true, bubbles: true }));

  await vi.waitFor(() => expect(document.querySelector(".assistant p")).not.toBeNull());
  const header = document.querySelector(".agent-header") as HTMLElement;
  expect(header.dataset.agentId).toBe("fraud");
  expect(header.textContent).toBe("🕵️@fraudgpt-x");
  // The header sits above the reply, not below it.
  expect(header.nextElementSibling?.classList.contains("assistant")).toBe(true);
});

test("a reloaded transcript heads each reply with the agent that wrote it", async () => {
  const entries = [
    { role: "user", content: "@fraud chargebacks", tool_name: null, agent_id: "fraud" },
    { role: "assistant", content: "three", tool_name: null, agent_id: "fraud" },
    { role: "user", content: "and last month?", tool_name: null, agent_id: "main" },
    { role: "assistant", content: "five", tool_name: null, agent_id: "main" },
    { role: "user", content: "old row", tool_name: null },
    { role: "assistant", content: "legacy", tool_name: null, agent_id: null },
  ];
  vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith("/transcript")) return jsonResponse({ entries });
    if (url === "/api/agents") return jsonResponse(AGENTS);
    return jsonResponse({ models: [] });
  });

  await import("./chat").then((module) => module.mount(document.body, context()));
  await vi.waitFor(() => expect(document.querySelectorAll(".agent-header")).toHaveLength(3));

  const headers = [...document.querySelectorAll<HTMLElement>(".agent-header")];
  expect(headers.map((h) => h.dataset.agentId)).toEqual(["fraud", "main", "main"]);
  expect(headers[0].textContent).toBe("🕵️@fraud");
});

test("an unknown @agent shows a notice above the default agent's reply", async () => {
  const frames = [
    'event: agent\ndata: {"type":"agent","agent_id":"main","name":"main","emoji":"🦀","model":"m"}\n\n',
    'event: notice\ndata: {"text":"@ghost não encontrado. Quem respondeu foi o agente padrão da sessão."}\n\n',
    'event: done\ndata: {"status":"ok","reply":"hello"}\n\n',
  ].join("");
  vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.endsWith("/turns") && init?.method === "POST") return streamResponse(frames);
    if (url.endsWith("/transcript")) return jsonResponse({ entries: [] });
    return jsonResponse({ models: [] });
  });

  await import("./chat").then((module) => module.mount(document.body, context()));
  await vi.waitFor(() => expect(document.querySelector(".empty")).not.toBeNull());
  (document.querySelector("#message") as HTMLTextAreaElement).value = "@ghost hi";
  document
    .querySelector("#composer")
    ?.dispatchEvent(new Event("submit", { cancelable: true, bubbles: true }));

  await vi.waitFor(() => expect(document.querySelector(".assistant p")).not.toBeNull());
  const note = document.querySelector(".agent-notice") as HTMLElement;
  expect(note.textContent).toContain("@ghost não encontrado");
  expect(note.nextElementSibling?.classList.contains("assistant")).toBe(true);
});

test("a reloaded notice entry renders as a notice, not a bubble", async () => {
  const entries = [
    { role: "user", content: "@ghost hi", tool_name: null, agent_id: "main" },
    { role: "notice", content: "@ghost não encontrado.", tool_name: null, agent_id: "main" },
    { role: "assistant", content: "hello", tool_name: null, agent_id: "main" },
  ];
  vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith("/transcript")) return jsonResponse({ entries });
    return jsonResponse({ models: [] });
  });

  await import("./chat").then((module) => module.mount(document.body, context()));
  await vi.waitFor(() => expect(document.querySelector(".agent-notice")).not.toBeNull());
  const log = document.querySelector("#log") as HTMLElement;
  expect([...log.children].map((n) => n.className)).toEqual([
    "bubble user",
    "agent-header",
    "agent-notice",
    "assistant",
  ]);
});
