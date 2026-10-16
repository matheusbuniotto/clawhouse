import { beforeEach, expect, test, vi } from "vitest";

import type { ScreenContext } from "./shell.js";

const SESSION = "11111111-1111-4111-8111-111111111111";

function context(search = `?session=${SESSION}`): ScreenContext {
  return { url: new URL(`http://localhost/chat${search}`), navigate: vi.fn() };
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

beforeEach(() => {
  vi.unstubAllGlobals();
  sessionStorage.clear();
  document.body.innerHTML = "";
});

test("renders a loaded transcript as markdown and one merged tool row", async () => {
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
    if (url === "/api/models") {
      return jsonResponse({ models: [{ id: "m", label: "M", default: true }] });
    }
    return jsonResponse({});
  });

  await import("./chat").then((module) => module.mount(document.body, context()));
  await vi.waitFor(() => expect(document.querySelector(".assistant")).not.toBeNull());

  const log = document.querySelector("#log") as HTMLElement;
  expect(log.querySelector(".bubble.user")?.textContent).toBe("What is `pandas`?");
  expect(log.querySelector(".bubble.assistant")).toBeNull();
  expect(log.querySelectorAll(".tool-row")).toHaveLength(1);
  expect((log.querySelector(".tool-row") as HTMLElement).dataset.state).toBe("ok");
  expect(log.querySelector(".tool-output")?.textContent).toBe("a dataframe library");
  expect(log.querySelector(".assistant h1")?.textContent).toBe("Answer");
  expect(log.querySelector(".assistant table")).not.toBeNull();
});

test("streams a turn into markdown and a shared tool row", async () => {
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
    if (url === "/api/models") return jsonResponse({ models: [] });
    return jsonResponse({});
  });

  await import("./chat").then((module) => module.mount(document.body, context()));
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

test("fills the context ring from a usage frame", async () => {
  const frames =
    'event: usage\ndata: {"input_tokens":150000,"output_tokens":12,"context_window":300000}\n\n' +
    'event: done\ndata: {"status":"ok","reply":"ok"}\n\n';
  vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.endsWith("/turns") && init?.method === "POST") return streamResponse(frames);
    if (url.endsWith("/transcript")) return jsonResponse({ entries: [] });
    if (url === "/api/models") {
      return jsonResponse({ models: [{ id: "m", label: "M", default: true }] });
    }
    return jsonResponse({});
  });

  await import("./chat").then((module) => module.mount(document.body, context()));
  await vi.waitFor(() => expect(document.querySelector(".empty")).not.toBeNull());

  (document.querySelector("#message") as HTMLTextAreaElement).value = "hello";
  document
    .querySelector("#composer")
    ?.dispatchEvent(new Event("submit", { cancelable: true, bubbles: true }));

  await vi.waitFor(() =>
    expect(document.querySelector("#ctx-meter")?.getAttribute("data-level")).toBe("warn"),
  );
  expect(document.querySelector(".ctx-label")?.textContent).toBe("150k");
});

test("a failed turn marks the running tool row and reports inline", async () => {
  const frames =
    'event: tool_call\ndata: {"name":"lookup","arguments":"{}"}\n\n' +
    'event: error\ndata: {"status":"error","reply":"","error":"The turn failed."}\n\n';
  vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.endsWith("/turns") && init?.method === "POST") return streamResponse(frames);
    if (url.endsWith("/transcript")) return jsonResponse({ entries: [] });
    return jsonResponse({ models: [] });
  });

  await import("./chat").then((module) => module.mount(document.body, context()));
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

test("the composer grows, keeps the model pill inline, and exposes abort only while running", async () => {
  let release: (() => void) | undefined;
  vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.endsWith("/turns") && init?.method === "POST") {
      return {
        ok: true,
        status: 200,
        body: {
          getReader: () => ({
            read: () =>
              new Promise((resolve) => {
                release = () => resolve({ done: true, value: undefined });
              }),
          }),
        },
      } as unknown as Response;
    }
    if (url.endsWith("/transcript")) return jsonResponse({ entries: [] });
    return jsonResponse({ models: [] });
  });

  await import("./chat").then((module) => module.mount(document.body, context()));

  const composer = document.querySelector("#composer") as HTMLFormElement;
  const model = document.querySelector("#model") as HTMLSelectElement;
  const abort = document.querySelector("#abort") as HTMLButtonElement;
  const message = document.querySelector("#message") as HTMLTextAreaElement;

  expect(model.className).toBe("model-pill");
  expect(composer.contains(model)).toBe(true);
  expect(abort.hidden).toBe(true);

  Object.defineProperty(message, "scrollHeight", { value: 96, configurable: true });
  message.value = "line\nline";
  message.dispatchEvent(new Event("input"));
  expect(message.style.height).toBe("96px");

  message.value = "hello";
  composer.dispatchEvent(new Event("submit", { cancelable: true, bubbles: true }));
  await vi.waitFor(() => expect(abort.hidden).toBe(false));

  abort.click();
  expect(abort.hidden).toBe(true);
  release?.();
});

test("when unhatched and no sessions exist, the chat composer pre-fills the wake-up draft message", async () => {
  vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url === "/api/hatch") return jsonResponse({ hatched: false });
    if (url === "/api/sessions") return jsonResponse({ sessions: [] });
    if (url.endsWith("/transcript")) return jsonResponse({ entries: [] });
    if (url === "/api/models") return jsonResponse({ models: [] });
    return jsonResponse({});
  });

  await import("./chat").then((module) => module.mount(document.body, context()));
  const message = document.querySelector("#message") as HTMLTextAreaElement;

  await vi.waitFor(() => expect(message.value).toBe("Wake up, my friend!"));
});

test("when already hatched or sessions exist, the composer is not pre-filled", async () => {
  vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url === "/api/hatch") return jsonResponse({ hatched: true });
    if (url === "/api/sessions") return jsonResponse({ sessions: [] });
    if (url.endsWith("/transcript")) return jsonResponse({ entries: [] });
    if (url === "/api/models") return jsonResponse({ models: [] });
    return jsonResponse({});
  });

  await import("./chat").then((module) => module.mount(document.body, context()));
  const message = document.querySelector("#message") as HTMLTextAreaElement;

  await vi.waitFor(() => expect(document.querySelector(".empty")).not.toBeNull());
  expect(message.value).toBe("");
});

test("shows autocomplete popover on @ trigger and inserts suggestion on Enter", async () => {
  vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.startsWith("/api/composer/suggestions")) {
      return jsonResponse({
        suggestions: [
          {
            label: "main",
            insert_text: "@main",
            detail: "Databricks Assistant",
            kind: "agent",
          },
        ],
      });
    }
    // Agent rows come from GET /api/agents (#97); server agent rows are ignored.
    if (url === "/api/agents") {
      return jsonResponse([{ name: "main", description: "Platform", signature_emoji: "🦀" }]);
    }
    if (url.endsWith("/transcript")) return jsonResponse({ entries: [] });
    if (url === "/api/models") return jsonResponse({ models: [] });
    return jsonResponse({});
  });

  await import("./chat").then((module) => module.mount(document.body, context()));
  await vi.waitFor(() => expect(document.querySelector(".empty")).not.toBeNull());
  const message = document.querySelector("#message") as HTMLTextAreaElement;

  message.value = "@ma";
  message.selectionStart = 3;
  message.selectionEnd = 3;
  message.dispatchEvent(new Event("input"));

  await vi.waitFor(() => expect(document.querySelector(".composer-popover")).not.toBeNull());
  expect(document.querySelector(".popover-item-label")?.textContent).toBe("🦀 @main");

  // Press Enter to select
  message.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));

  expect(document.querySelector(".composer-popover")).toBeNull();
  expect(message.value).toBe("@main ");
});

test("shows autocomplete popover on / trigger and inserts /skill suggestion on Enter", async () => {
  vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.startsWith("/api/composer/suggestions")) {
      return jsonResponse({
        suggestions: [
          {
            label: "/skill:code-review",
            insert_text: "/skill:code-review",
            detail: "Activate code-review skill instructions",
            kind: "skill",
          },
        ],
      });
    }
    if (url.endsWith("/transcript")) return jsonResponse({ entries: [] });
    if (url === "/api/models") return jsonResponse({ models: [] });
    return jsonResponse({});
  });

  await import("./chat").then((module) => module.mount(document.body, context()));
  const message = document.querySelector("#message") as HTMLTextAreaElement;

  message.value = "/sk";
  message.selectionStart = 3;
  message.selectionEnd = 3;
  message.dispatchEvent(new Event("input"));

  await vi.waitFor(() => expect(document.querySelector(".composer-popover")).not.toBeNull());
  expect(document.querySelector(".popover-item-label")?.textContent).toBe("/skill:code-review");

  // Press Enter to select
  message.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));

  expect(document.querySelector(".composer-popover")).toBeNull();
  expect(message.value).toBe("/skill:code-review ");
});

test("immediately renders user turn and thinking indicator upon submit before response arrives", async () => {
  let resolveResponse: ((value: Response) => void) | null = null;
  const delayedResponse = new Promise<Response>((resolve) => {
    resolveResponse = resolve;
  });

  vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.endsWith("/turns") && init?.method === "POST") return delayedResponse;
    if (url.endsWith("/transcript")) return jsonResponse({ entries: [] });
    if (url === "/api/models") return jsonResponse({ models: [] });
    return jsonResponse({});
  });

  await import("./chat").then((module) => module.mount(document.body, context()));
  const input = document.querySelector("#message") as HTMLTextAreaElement;
  input.value = "my fast query";
  document
    .querySelector("#composer")
    ?.dispatchEvent(new Event("submit", { cancelable: true, bubbles: true }));

  // Immediately, user bubble is present and thinking indicator is rendered
  const log = document.querySelector("#log") as HTMLElement;
  expect(log.querySelector(".bubble.user")?.textContent).toBe("my fast query");
  expect(log.querySelector(".assistant.thinking")).not.toBeNull();
  expect(log.querySelector(".thinking-indicator")?.textContent).toContain("Thinking");

  // Complete response
  const doneFrame = 'event: done\ndata: {"status":"ok","reply":"Answered"}\n\n';
  resolveResponse!(streamResponse(doneFrame));

  await vi.waitFor(() => expect(log.querySelector(".assistant:not(.thinking)")).not.toBeNull());
  expect(log.querySelector(".assistant.thinking")).toBeNull();
  expect(log.querySelector(".assistant")?.textContent).toContain("Answered");
});

test("slash command triggers popover at start of input and after whitespace", async () => {
  vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.startsWith("/api/composer/suggestions")) {
      return jsonResponse({
        suggestions: [
          { label: "/compact", insert_text: "/compact", detail: "Compact history", kind: "command" },
          { label: "/jobs", insert_text: "/jobs", detail: "View jobs", kind: "command" },
        ],
      });
    }
    if (url.endsWith("/transcript")) return jsonResponse({ entries: [] });
    if (url === "/api/models") return jsonResponse({ models: [] });
    return jsonResponse({});
  });

  await import("./chat").then((module) => module.mount(document.body, context()));
  const message = document.querySelector("#message") as HTMLTextAreaElement;

  // At start of input
  message.value = "/";
  message.selectionStart = 1;
  message.selectionEnd = 1;
  message.dispatchEvent(new Event("input"));

  const popover = document.querySelector(".composer-popover");
  expect(popover).not.toBeNull();
  const items = document.querySelectorAll(".composer-popover-item");
  expect(items.length).toBeGreaterThan(0);
});

test("slash command keyboard navigation moves active highlight", async () => {
  vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith("/transcript")) return jsonResponse({ entries: [] });
    return jsonResponse({});
  });

  await import("./chat").then((module) => module.mount(document.body, context()));
  const message = document.querySelector("#message") as HTMLTextAreaElement;

  message.value = "/";
  message.selectionStart = 1;
  message.selectionEnd = 1;
  message.dispatchEvent(new Event("input"));

  const items = document.querySelectorAll(".composer-popover-item");
  expect(items[0]?.classList.contains("active")).toBe(true);

  // ArrowDown moves down
  message.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true }));
  expect(document.querySelectorAll(".composer-popover-item")[1]?.classList.contains("active")).toBe(true);

  // ArrowUp moves back
  message.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowUp", bubbles: true }));
  expect(document.querySelectorAll(".composer-popover-item")[0]?.classList.contains("active")).toBe(true);
});

test("slash command selection inserts command", async () => {
  vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith("/transcript")) return jsonResponse({ entries: [] });
    return jsonResponse({});
  });

  await import("./chat").then((module) => module.mount(document.body, context()));
  const message = document.querySelector("#message") as HTMLTextAreaElement;

  message.value = "/co";
  message.selectionStart = 3;
  message.selectionEnd = 3;
  message.dispatchEvent(new Event("input"));

  message.dispatchEvent(new KeyboardEvent("keydown", { key: "Tab", bubbles: true }));
  expect(message.value).toBe("/compact ");
  expect(document.querySelector(".composer-popover")).toBeNull();
});

test("slash command popover dismiss closes popover", async () => {
  vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith("/transcript")) return jsonResponse({ entries: [] });
    return jsonResponse({});
  });

  await import("./chat").then((module) => module.mount(document.body, context()));
  const message = document.querySelector("#message") as HTMLTextAreaElement;

  message.value = "/";
  message.selectionStart = 1;
  message.selectionEnd = 1;
  message.dispatchEvent(new Event("input"));

  expect(document.querySelector(".composer-popover")).not.toBeNull();
  message.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  expect(document.querySelector(".composer-popover")).toBeNull();
});

test("slash command network error handled gracefully", async () => {
  vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.startsWith("/api/composer/suggestions")) {
      return { ok: false, status: 500 } as Response;
    }
    if (url.endsWith("/transcript")) return jsonResponse({ entries: [] });
    return jsonResponse({});
  });

  await import("./chat").then((module) => module.mount(document.body, context()));
  const message = document.querySelector("#message") as HTMLTextAreaElement;

  message.value = "/custom";
  message.selectionStart = 7;
  message.selectionEnd = 7;
  message.dispatchEvent(new Event("input"));

  // Input stays functional and not disabled
  expect(message.disabled).toBe(false);
});

test("scrolling up pauses auto-scroll", async () => {
  vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith("/transcript")) return jsonResponse({ entries: [] });
    return jsonResponse({});
  });

  await import("./chat").then((module) => module.mount(document.body, context()));
  const log = document.querySelector("#log") as HTMLElement;

  // Mock scroll properties
  Object.defineProperty(log, "scrollHeight", { value: 1000, configurable: true });
  Object.defineProperty(log, "clientHeight", { value: 400, configurable: true });
  Object.defineProperty(log, "scrollTop", { value: 200, writable: true, configurable: true });

  log.dispatchEvent(new Event("scroll"));

  // Scrolled up past 80px from bottom (1000 - 400 - 200 = 400px > 80px)
  const scrollBtn = document.querySelector("#scroll-bottom") as HTMLButtonElement;
  expect(scrollBtn.hidden).toBe(false);
});

test("floating scroll button appears when scrolled up", async () => {
  vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith("/transcript")) return jsonResponse({ entries: [] });
    return jsonResponse({});
  });

  await import("./chat").then((module) => module.mount(document.body, context()));
  const log = document.querySelector("#log") as HTMLElement;
  const scrollBtn = document.querySelector("#scroll-bottom") as HTMLButtonElement;

  expect(scrollBtn).not.toBeNull();
  expect(scrollBtn.hidden).toBe(true);

  Object.defineProperty(log, "scrollHeight", { value: 800, configurable: true });
  Object.defineProperty(log, "clientHeight", { value: 300, configurable: true });
  Object.defineProperty(log, "scrollTop", { value: 100, writable: true, configurable: true });
  log.dispatchEvent(new Event("scroll"));

  expect(scrollBtn.hidden).toBe(false);
});

test("clicking scroll button returns to bottom", async () => {
  vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith("/transcript")) return jsonResponse({ entries: [] });
    return jsonResponse({});
  });

  await import("./chat").then((module) => module.mount(document.body, context()));
  const log = document.querySelector("#log") as HTMLElement;
  const scrollBtn = document.querySelector("#scroll-bottom") as HTMLButtonElement;

  Object.defineProperty(log, "scrollHeight", { value: 1000, configurable: true });
  Object.defineProperty(log, "clientHeight", { value: 400, configurable: true });
  Object.defineProperty(log, "scrollTop", { value: 200, writable: true, configurable: true });
  log.dispatchEvent(new Event("scroll"));

  expect(scrollBtn.hidden).toBe(false);

  scrollBtn.click();
  expect(log.scrollTop).toBe(1000);
  expect(scrollBtn.hidden).toBe(true);
});

test("reaching bottom resumes auto-scroll", async () => {
  vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith("/transcript")) return jsonResponse({ entries: [] });
    return jsonResponse({});
  });

  await import("./chat").then((module) => module.mount(document.body, context()));
  const log = document.querySelector("#log") as HTMLElement;
  const scrollBtn = document.querySelector("#scroll-bottom") as HTMLButtonElement;

  Object.defineProperty(log, "scrollHeight", { value: 1000, configurable: true });
  Object.defineProperty(log, "clientHeight", { value: 400, configurable: true });
  Object.defineProperty(log, "scrollTop", { value: 200, writable: true, configurable: true });
  log.dispatchEvent(new Event("scroll"));
  expect(scrollBtn.hidden).toBe(false);

  // Scroll back to within 40px of bottom
  log.scrollTop = 580; // 1000 - 400 - 580 = 20px <= 40px
  log.dispatchEvent(new Event("scroll"));
  expect(scrollBtn.hidden).toBe(true);
});

test("composer saves draft to sessionStorage", async () => {
  vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith("/transcript")) return jsonResponse({ entries: [] });
    return jsonResponse({});
  });

  await import("./chat").then((module) => module.mount(document.body, context()));
  const message = document.querySelector("#message") as HTMLTextAreaElement;

  message.value = "Unsent draft text";
  message.dispatchEvent(new Event("input"));

  expect(sessionStorage.getItem(`clawhouse.draft.${SESSION}`)).toBe("Unsent draft text");
});

test("chat restores draft on mount", async () => {
  sessionStorage.setItem(`clawhouse.draft.${SESSION}`, "Previously saved draft");

  vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith("/transcript")) return jsonResponse({ entries: [] });
    return jsonResponse({});
  });

  await import("./chat").then((module) => module.mount(document.body, context()));
  const message = document.querySelector("#message") as HTMLTextAreaElement;

  expect(message.value).toBe("Previously saved draft");
});

test("submitting form clears saved draft", async () => {
  sessionStorage.setItem(`clawhouse.draft.${SESSION}`, "To be sent");

  vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.endsWith("/turns") && init?.method === "POST") {
      return streamResponse('event: done\ndata: {"status":"ok","reply":"ok"}\n\n');
    }
    if (url.endsWith("/transcript")) return jsonResponse({ entries: [] });
    return jsonResponse({});
  });

  await import("./chat").then((module) => module.mount(document.body, context()));
  const message = document.querySelector("#message") as HTMLTextAreaElement;
  expect(message.value).toBe("To be sent");

  document.querySelector("#composer")?.dispatchEvent(new Event("submit", { cancelable: true, bubbles: true }));

  expect(sessionStorage.getItem(`clawhouse.draft.${SESSION}`)).toBeNull();
});
