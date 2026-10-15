import { beforeEach, expect, test, vi } from "vitest";

import { agentSuggestions, mergeSuggestions } from "./mentions.js";
import type { ScreenContext } from "./shell.js";

const AGENTS = [
  { name: "main", description: "Clawhouse platform agent", signature_emoji: "🦀", is_platform: true },
  { name: "fraud", description: "Chargeback analyst", signature_emoji: "🕵️" },
  { name: "finops", description: "Cloud costs" },
];

test("prefix matches rank before description matches, keeping list order", () => {
  // "f" prefixes fraud and finops; main only matches through "platform" in its description.
  expect(agentSuggestions(AGENTS, "f").map((s) => s.insert_text)).toEqual([
    "@fraud",
    "@finops",
    "@main",
  ]);
  expect(agentSuggestions(AGENTS, "charge").map((s) => s.insert_text)).toEqual(["@fraud"]);
  expect(agentSuggestions(AGENTS, "").map((s) => s.insert_text)).toEqual([
    "@main",
    "@fraud",
    "@finops",
  ]);
  expect(agentSuggestions(AGENTS, "zzz")).toEqual([]);
});

test("labels carry the emoji, with a robot for agents without one", () => {
  const [fraud] = agentSuggestions(AGENTS, "fraud");
  expect(fraud).toEqual({
    label: "🕵️ @fraud",
    insert_text: "@fraud",
    detail: "Chargeback analyst",
    kind: "agent",
  });
  expect(agentSuggestions(AGENTS, "finops")[0].label).toBe("🤖 @finops");
});

test("server suggestions add files and tables but never duplicate agents", () => {
  const local = agentSuggestions(AGENTS, "m");
  const merged = mergeSuggestions(local, [
    { label: "main", insert_text: "@main", detail: "", kind: "agent" },
    { label: "MEMORY.md", insert_text: "@MEMORY.md", detail: "file", kind: "file" },
  ]);
  expect(merged.map((s) => s.insert_text)).toEqual(["@main", "@MEMORY.md"]);
});

// --- composer wiring ---

function jsonResponse(payload: unknown): Response {
  return { ok: true, json: async () => payload } as unknown as Response;
}

function context(): ScreenContext {
  return {
    url: new URL("http://localhost/chat?session=11111111-1111-4111-8111-111111111111"),
    navigate: vi.fn(),
  };
}

beforeEach(() => {
  vi.unstubAllGlobals();
  sessionStorage.clear();
  document.body.innerHTML = "";
});

test("typing @ shows agents at once and Enter inserts the handle", async () => {
  vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url === "/api/agents") return jsonResponse(AGENTS);
    if (url.endsWith("/transcript")) return jsonResponse({ entries: [] });
    if (url.startsWith("/api/composer/suggestions")) return jsonResponse({ suggestions: [] });
    return jsonResponse({ models: [] });
  });
  await import("./chat").then((module) => module.mount(document.body, context()));
  await vi.waitFor(() => expect(document.querySelector(".empty")).not.toBeNull());

  const input = document.querySelector("#message") as HTMLTextAreaElement;
  input.value = "@fr";
  input.setSelectionRange(3, 3);
  input.dispatchEvent(new Event("input"));

  // No debounce wait: the agent list is local.
  const items = [...document.querySelectorAll(".composer-popover-item .popover-item-label")];
  expect(items.map((n) => n.textContent)).toEqual(["🕵️ @fraud"]);

  input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", cancelable: true }));
  expect(input.value).toBe("@fraud ");
  expect(document.querySelector(".composer-popover")).toBeNull();
});
