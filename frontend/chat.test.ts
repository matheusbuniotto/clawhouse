import { beforeEach, expect, test, vi } from "vitest";

const SESSION = "11111111-1111-4111-8111-111111111111";

const PAGE = `
  <p id="who">Checking sign-in…</p>
  <main id="log" class="log"></main>
  <form id="composer" class="composer">
    <select id="model"></select>
    <textarea id="message"></textarea>
    <button type="submit">Send</button>
    <p id="status" class="status" role="status"></p>
  </form>
`;

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

beforeEach(() => {
  vi.resetModules();
  vi.unstubAllGlobals();
  sessionStorage.clear();
  document.body.innerHTML = PAGE;
});

test("renders a loaded transcript as markdown and one merged tool row", async () => {
  sessionStorage.setItem("crabriks.session", SESSION);
  const entries = [
    { role: "user", content: "What is `pandas`?", tool_name: null },
    { role: "tool_call", content: '{"q":"pandas"}', tool_name: "lookup" },
    { role: "tool_result", content: "a dataframe library", tool_name: "lookup" },
    {
      role: "assistant",
      content: "# Answer\n\n| a | b |\n| --- | --- |\n| 1 | 2 |",
      tool_name: null,
    },
  ];
  vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith("/transcript")) return jsonResponse({ entries });
    if (url === "/api/me") return jsonResponse({ user_id: "ada@example.com" });
    if (url === "/api/models") {
      return jsonResponse({ models: [{ id: "m", label: "M", default: true }] });
    }
    return jsonResponse({});
  });

  await import("./chat");
  await vi.waitFor(() => expect(document.querySelector(".assistant")).not.toBeNull());

  const log = document.querySelector("#log") as HTMLElement;
  expect(document.querySelector("#who")?.textContent).toBe("ada@example.com");
  expect(log.querySelector(".bubble.user")?.textContent).toBe("What is `pandas`?");
  expect(log.querySelector(".bubble.assistant")).toBeNull();
  expect(log.querySelectorAll(".tool-row")).toHaveLength(1);
  expect((log.querySelector(".tool-row") as HTMLElement).dataset.state).toBe("ok");
  expect(log.querySelector(".tool-output")?.textContent).toBe("a dataframe library");
  expect(log.querySelector(".assistant h1")?.textContent).toBe("Answer");
  expect(log.querySelector(".assistant table")).not.toBeNull();
});

test("streams a turn into markdown and a shared tool row", async () => {
  sessionStorage.setItem("crabriks.session", SESSION);
  const frames = [
    'event: token\ndata: {"text":"# Hi"}\n\n',
    'event: tool_call\ndata: {"name":"lookup","arguments":"{}"}\n\n',
    'event: tool_result\ndata: {"name":"lookup","content":"ok"}\n\n',
    'event: done\ndata: {"status":"ok","reply":"# Hi\\n\\nAll done."}\n\n',
  ].join("");
  vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.endsWith("/turns") && init?.method === "POST") return streamResponse(frames);
    if (url.endsWith("/transcript")) return jsonResponse({ entries: [] });
    if (url === "/api/me") return jsonResponse({ user_id: "ada@example.com" });
    if (url === "/api/models") return jsonResponse({ models: [] });
    return jsonResponse({});
  });

  await import("./chat");
  await vi.waitFor(() => expect(document.querySelector(".empty")).not.toBeNull());

  const input = document.querySelector("#message") as HTMLTextAreaElement;
  input.value = "hello";
  document
    .querySelector("#composer")
    ?.dispatchEvent(new Event("submit", { cancelable: true, bubbles: true }));

  await vi.waitFor(() => expect(document.querySelector(".assistant h1")).not.toBeNull());

  const log = document.querySelector("#log") as HTMLElement;
  expect(log.querySelector(".bubble.user")?.textContent).toBe("hello");
  expect(log.querySelectorAll(".tool-row")).toHaveLength(1);
  expect(log.querySelector(".assistant h1")?.textContent).toBe("Hi");
  expect(log.querySelector(".assistant p")?.textContent).toBe("All done.");
  expect(document.querySelector("#status")?.textContent).toBe("");
});

test("a failed turn marks the running tool row and reports inline", async () => {
  sessionStorage.setItem("crabriks.session", SESSION);
  const frames =
    'event: tool_call\ndata: {"name":"lookup","arguments":"{}"}\n\n' +
    'event: error\ndata: {"status":"error","reply":"","error":"The turn failed."}\n\n';
  vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.endsWith("/turns") && init?.method === "POST") return streamResponse(frames);
    if (url.endsWith("/transcript")) return jsonResponse({ entries: [] });
    if (url === "/api/me") return jsonResponse({ user_id: "ada@example.com" });
    return jsonResponse({ models: [] });
  });

  await import("./chat");
  await vi.waitFor(() => expect(document.querySelector(".empty")).not.toBeNull());

  (document.querySelector("#message") as HTMLTextAreaElement).value = "hello";
  document
    .querySelector("#composer")
    ?.dispatchEvent(new Event("submit", { cancelable: true, bubbles: true }));

  await vi.waitFor(() =>
    expect(document.querySelector("#status")?.textContent).toBe("The turn failed."),
  );

  const row = document.querySelector(".tool-row") as HTMLElement;
  expect(row.dataset.state).toBe("error");
  expect(row.querySelector(".tool-output")?.textContent).toBe("The turn failed.");
});
