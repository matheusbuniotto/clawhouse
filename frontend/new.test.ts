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

test("links to /agents instead of rendering inline agent creation or deletion forms", async () => {
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

  expect(document.querySelector("#start")).not.toBeNull();
  expect(document.querySelector(".create-agent-form")).toBeNull();
  expect(document.querySelector(".custom-agents-list")).toBeNull();

  const manageLink = document.querySelector('a[href="/agents"][data-nav]') as HTMLAnchorElement;
  expect(manageLink).not.toBeNull();
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
