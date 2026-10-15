import { beforeEach, expect, test, vi } from "vitest";

import type { ScreenContext } from "./shell.js";

const SESSION = "11111111-1111-4111-8111-111111111111";

function context(): ScreenContext {
  return {
    url: new URL(`http://localhost/chat?session=${SESSION}`),
    navigate: vi.fn(),
  };
}

function jsonResponse(payload: unknown, status = 200): Response {
  return {
    ok: status < 400,
    status,
    json: async () => payload,
  } as unknown as Response;
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
          sent
            ? { done: true, value: undefined }
            : ((sent = true), { done: false, value: bytes }),
      }),
    },
  } as unknown as Response;
}

async function mountChat(): Promise<void> {
  await import("./chat").then((module) =>
    module.mount(document.body, context()),
  );
}

function submit(text: string): void {
  (document.querySelector("#message") as HTMLTextAreaElement).value = text;
  document
    .querySelector("#composer")
    ?.dispatchEvent(new Event("submit", { cancelable: true, bubbles: true }));
}

const log = (): HTMLElement => document.querySelector("#log") as HTMLElement;

beforeEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
  sessionStorage.clear();
  document.body.innerHTML = "";
});

test("a reloaded header keeps the model, and the notice sits below it", async () => {
  const entries = [
    { role: "user", content: "@nope oi", tool_name: null, agent_id: "main" },
    {
      role: "notice",
      content: "@nope não encontrado.",
      tool_name: null,
      agent_id: "main",
      model: "m-1",
    },
    {
      role: "assistant",
      content: "Oi!",
      tool_name: null,
      agent_id: "main",
      model: "m-1",
    },
  ];
  vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith("/transcript"))
      return jsonResponse({ entries, run_state: "idle" });
    if (url === "/api/approvals") return jsonResponse({ pending: [] });
    if (url.endsWith("/questions")) return jsonResponse([]);
    return jsonResponse({ models: [] });
  });
  await mountChat();
  await vi.waitFor(() =>
    expect(log().querySelector(".agent-header")).not.toBeNull(),
  );

  expect(log().querySelector(".agent-header-model")?.textContent).toBe("m-1");
  const order = [...log().children].map((node) => node.className.split(" ")[0]);
  expect(order.indexOf("agent-header")).toBeLessThan(
    order.indexOf("agent-notice"),
  );
});

test("a message sent before the history arrives stays on screen", async () => {
  let releaseTranscript: (() => void) | undefined;
  const transcriptLanded = new Promise<void>(
    (resolve) => (releaseTranscript = resolve),
  );
  vi.stubGlobal(
    "fetch",
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/turns") && init?.method === "POST") {
        return streamResponse(
          'event: done\ndata: {"status":"ok","reply":"Olá"}\n\n',
        );
      }
      if (url.endsWith("/transcript")) {
        await transcriptLanded;
        return jsonResponse({ entries: [], run_state: "running" });
      }
      return jsonResponse({ models: [] });
    },
  );
  await mountChat();
  submit("oi");
  releaseTranscript?.();

  await vi.waitFor(() =>
    expect(log().querySelector(".assistant")?.textContent).toContain("Olá"),
  );
  expect(log().querySelector(".bubble.user")?.textContent).toBe("oi");
});

test("reloading mid-turn keeps the composer closed and shows the final state", async () => {
  vi.useFakeTimers({ toFake: ["setTimeout"] });
  let calls = 0;
  vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith("/transcript")) {
      calls += 1;
      const user = { role: "user", content: "relatório", tool_name: null };
      if (calls < 2)
        return jsonResponse({ entries: [user], run_state: "running" });
      const reply = { role: "assistant", content: "Pronto", tool_name: null };
      return jsonResponse({ entries: [user, reply], run_state: "idle" });
    }
    if (url === "/api/approvals") return jsonResponse({ pending: [] });
    if (url.endsWith("/questions")) return jsonResponse([]);
    return jsonResponse({ models: [] });
  });
  await mountChat();
  await vi.waitFor(() =>
    expect(log().querySelector(".assistant.thinking")).not.toBeNull(),
  );
  expect(
    (document.querySelector("#message") as HTMLTextAreaElement).disabled,
  ).toBe(true);

  await vi.advanceTimersByTimeAsync(1600);
  await vi.waitFor(() =>
    expect(log().querySelector(".assistant")?.textContent).toContain("Pronto"),
  );
  expect(log().querySelector(".assistant.thinking")).toBeNull();
  expect(
    (document.querySelector("#message") as HTMLTextAreaElement).disabled,
  ).toBe(false);
});

test("a pending question found on reload closes the composer", async () => {
  vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith("/transcript"))
      return jsonResponse({ entries: [], run_state: "idle" });
    if (url.endsWith("/questions")) {
      return jsonResponse([
        { id: "q", question: "Mês?", options: ["Set", "Out"], default: "Out" },
      ]);
    }
    if (url === "/api/approvals") return jsonResponse({ pending: [] });
    return jsonResponse({ models: [] });
  });
  await mountChat();
  await vi.waitFor(() =>
    expect(document.querySelector(".question-card")).not.toBeNull(),
  );
  expect(
    (document.querySelector("#message") as HTMLTextAreaElement).disabled,
  ).toBe(true);
});

test("a pending approval found on reload closes the composer", async () => {
  vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith("/transcript"))
      return jsonResponse({ entries: [], run_state: "idle" });
    if (url.endsWith("/questions")) return jsonResponse([]);
    if (url === "/api/approvals")
      return jsonResponse({ pending: [{ session_id: SESSION }] });
    return jsonResponse({ models: [] });
  });
  await mountChat();
  await vi.waitFor(() =>
    expect(
      (document.querySelector("#message") as HTMLTextAreaElement).disabled,
    ).toBe(true),
  );
  expect(document.querySelector("#status")?.textContent).toBe(
    "Ação aguardando aprovação acima.",
  );
});

test("a refused turn gives the message back instead of reporting a broken stream", async () => {
  vi.stubGlobal(
    "fetch",
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/turns") && init?.method === "POST") {
        return jsonResponse(
          { error: "A tool call is pending approval for this session." },
          409,
        );
      }
      if (url.endsWith("/transcript"))
        return jsonResponse({ entries: [], run_state: "idle" });
      if (url === "/api/approvals") return jsonResponse({ pending: [] });
      if (url.endsWith("/questions")) return jsonResponse([]);
      return jsonResponse({ models: [] });
    },
  );
  await mountChat();
  await vi.waitFor(() =>
    expect(document.querySelector(".empty")).not.toBeNull(),
  );
  submit("oi");
  await vi.waitFor(() =>
    expect(document.querySelector("#status")?.textContent).toBe(
      "A tool call is pending approval for this session.",
    ),
  );
  expect(log().querySelector(".bubble.user")).toBeNull();
  expect(
    (document.querySelector("#message") as HTMLTextAreaElement).value,
  ).toBe("oi");
});
