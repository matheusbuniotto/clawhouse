import { beforeEach, describe, expect, it, test, vi } from "vitest";

import {
  chosenFromResult,
  parseProgress,
  renderAnsweredQuestion,
  renderQuestionCard,
  upsertProgressCard,
} from "./cards.js";
import type { ScreenContext } from "./shell.js";

function jsonResponse(payload: unknown, ok = true): Response {
  return {
    ok,
    status: ok ? 200 : 422,
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

beforeEach(() => {
  vi.unstubAllGlobals();
  sessionStorage.clear();
  document.body.innerHTML = "";
});

const QUESTION = {
  id: "q-1",
  question: "Which month?",
  options: ["Sept", "Oct"],
  default: "Oct",
  multi: false,
};

test("one click answers a single-choice question through the answer endpoint", async () => {
  const calls: { url: string; body: unknown }[] = [];
  vi.stubGlobal(
    "fetch",
    async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ url: String(input), body: JSON.parse(String(init?.body)) });
      return jsonResponse({
        status: "ok",
        reply: "Using September.",
        pending: [],
      });
    },
  );
  const onAnswered = vi.fn();
  const card = renderQuestionCard(QUESTION, onAnswered);
  document.body.append(card);

  const preferred = card.querySelector<HTMLElement>(".question-option.default");
  expect(preferred?.dataset.option).toBe("Oct");
  expect(preferred?.querySelector(".question-default-tag")?.textContent).toBe(
    "padrão",
  );
  (card.querySelector('[data-option="Sept"]') as HTMLButtonElement).click();

  await vi.waitFor(() => expect(onAnswered).toHaveBeenCalled());
  expect(calls).toEqual([
    { url: "/api/questions/q-1/answer", body: { selected: ["Sept"] } },
  ]);
  expect(onAnswered).toHaveBeenCalledWith({
    status: "ok",
    reply: "Using September.",
    pending: [],
  });
  expect(card.dataset.state).toBe("answered");
  expect(card.querySelector(".chosen")?.textContent).toBe("Sept");
  expect(
    [...card.querySelectorAll("button")].every(
      (b) => (b as HTMLButtonElement).disabled,
    ),
  ).toBe(true);
});

test("a multi-choice question toggles options and sends on Enviar", async () => {
  const bodies: unknown[] = [];
  vi.stubGlobal(
    "fetch",
    async (_input: RequestInfo | URL, init?: RequestInit) => {
      bodies.push(JSON.parse(String(init?.body)));
      return jsonResponse({ status: "ok", reply: "", pending: [] });
    },
  );
  const card = renderQuestionCard(
    {
      id: "q-2",
      question: "Which regions?",
      options: ["BR", "US", "EU"],
      multi: true,
    },
    vi.fn(),
  );
  document.body.append(card);
  const submit = card.querySelector(".question-submit") as HTMLButtonElement;
  expect(submit.disabled).toBe(true);

  (card.querySelector('[data-option="BR"]') as HTMLButtonElement).click();
  (card.querySelector('[data-option="EU"]') as HTMLButtonElement).click();
  (card.querySelector('[data-option="BR"]') as HTMLButtonElement).click();
  (card.querySelector('[data-option="US"]') as HTMLButtonElement).click();
  submit.click();

  await vi.waitFor(() => expect(card.dataset.state).toBe("answered"));
  expect(bodies).toEqual([{ selected: ["EU", "US"] }]);
});

test("a rejected answer re-enables the buttons and says so", async () => {
  vi.stubGlobal("fetch", async () => jsonResponse({ detail: "nope" }, false));
  const card = renderQuestionCard(QUESTION, vi.fn());
  (card.querySelector('[data-option="Oct"]') as HTMLButtonElement).click();

  await vi.waitFor(() =>
    expect(card.querySelector(".question-note")?.textContent).toBe(
      "Não foi possível enviar a resposta.",
    ),
  );
  expect(
    (card.querySelector('[data-option="Oct"]') as HTMLButtonElement).disabled,
  ).toBe(false);
});

test("a reloaded question shows the choice, including a job's default", () => {
  const args = JSON.stringify({
    question: "Which month?",
    options: ["Sept", "Oct"],
    default: "Oct",
  });
  const clicked = renderAnsweredQuestion(
    args,
    "The user chose: Sept",
  ) as HTMLElement;
  expect(clicked.querySelector(".chosen")?.textContent).toBe("Sept");

  const headless = renderAnsweredQuestion(
    args,
    'No user in this run (scheduled job): picked the default option "Oct".',
  ) as HTMLElement;
  expect(headless.querySelector<HTMLElement>(".chosen")?.dataset.option).toBe(
    "Oct",
  );
  expect(headless.textContent).toContain("seguiu a opção padrão");

  expect(
    chosenFromResult("The user chose: Sept, Oct", ["Sept", "Oct"]),
  ).toEqual(["Sept", "Oct"]);
  expect(renderAnsweredQuestion("not json", "x")).toBeNull();
});

// --- chat wiring ---

function context(): ScreenContext {
  return {
    url: new URL(
      "http://localhost/chat?session=11111111-1111-4111-8111-111111111111",
    ),
    navigate: vi.fn(),
  };
}

test("a question frame becomes a card, not a tool row, and the reply lands below", async () => {
  const frames = [
    'event: tool_call\ndata: {"name":"ask_user","arguments":"{}"}\n\n',
    'event: question\ndata: {"question_id":"q-1","question":"Which month?","options":["Sept","Oct"],"default":"Oct","multi":false}\n\n',
    'event: done\ndata: {"status":"pending_approval","reply":"","approval_id":"q-1"}\n\n',
  ].join("");
  vi.stubGlobal(
    "fetch",
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/turns") && init?.method === "POST")
        return streamResponse(frames);
      if (url.endsWith("/transcript")) return jsonResponse({ entries: [] });
      if (url.endsWith("/questions")) return jsonResponse([]);
      if (url === "/api/questions/q-1/answer") {
        return jsonResponse({
          status: "ok",
          reply: "September it is.",
          pending: [],
        });
      }
      return jsonResponse({ models: [] });
    },
  );

  await import("./chat").then((module) =>
    module.mount(document.body, context()),
  );
  await vi.waitFor(() =>
    expect(document.querySelector(".empty")).not.toBeNull(),
  );
  (document.querySelector("#message") as HTMLTextAreaElement).value = "report";
  document
    .querySelector("#composer")
    ?.dispatchEvent(new Event("submit", { cancelable: true, bubbles: true }));

  await vi.waitFor(() =>
    expect(document.querySelector(".question-card")).not.toBeNull(),
  );
  expect(document.querySelector(".tool-row")).toBeNull();
  await vi.waitFor(() =>
    expect(document.querySelector("#status")?.textContent).toBe(
      "Esperando sua resposta na pergunta acima.",
    ),
  );
  // The pending question holds the composer until it is answered.
  expect(
    (document.querySelector("#message") as HTMLTextAreaElement).disabled,
  ).toBe(true);
  expect(
    (document.querySelector("button.send") as HTMLButtonElement).disabled,
  ).toBe(true);

  (document.querySelector('[data-option="Sept"]') as HTMLButtonElement).click();
  await vi.waitFor(() =>
    expect(document.querySelector(".assistant p")?.textContent).toBe(
      "September it is.",
    ),
  );
  expect(document.querySelector("#status")?.textContent).toBe("");
  expect(
    (document.querySelector("#message") as HTMLTextAreaElement).disabled,
  ).toBe(false);
});

test("reload shows answered questions read-only and pending ones live", async () => {
  const args = JSON.stringify({
    question: "Which month?",
    options: ["Sept", "Oct"],
  });
  const entries = [
    { role: "user", content: "report", tool_name: null, agent_id: "main" },
    {
      role: "tool_call",
      content: args,
      tool_name: "ask_user",
      agent_id: "main",
    },
    {
      role: "tool_result",
      content: "The user chose: Oct",
      tool_name: "ask_user",
      agent_id: "main",
    },
    { role: "assistant", content: "done", tool_name: null, agent_id: "main" },
    { role: "user", content: "again", tool_name: null, agent_id: "main" },
    {
      role: "tool_call",
      content: args,
      tool_name: "ask_user",
      agent_id: "main",
    },
  ];
  vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith("/transcript")) return jsonResponse({ entries });
    if (url.endsWith("/questions"))
      return jsonResponse([{ ...QUESTION, id: "q-9" }]);
    return jsonResponse({ models: [] });
  });

  await import("./chat").then((module) =>
    module.mount(document.body, context()),
  );
  await vi.waitFor(() =>
    expect(document.querySelectorAll(".question-card")).toHaveLength(2),
  );

  const [answered, live] = [
    ...document.querySelectorAll<HTMLElement>(".question-card"),
  ];
  expect(answered.dataset.state).toBe("answered");
  expect(answered.querySelector(".chosen")?.textContent).toBe("Oct");
  expect(live.dataset.state).toBe("pending");
  expect(live.dataset.questionId).toBe("q-9");
  expect(document.querySelector(".tool-row")).toBeNull();
});

describe("progress card", () => {
  it("parses a stored call and rejects junk", () => {
    expect(
      parseProgress('{"task_id":"t","steps":[{"label":"a","status":"done"}]}'),
    ).toEqual({
      task_id: "t",
      steps: [{ label: "a", status: "done" }],
    });
    expect(parseProgress("nope")).toBeNull();
    expect(
      parseProgress('{"task_id":"t","steps":[{"label":"a","status":"?"}]}'),
    ).toBeNull();
  });

  it("keeps one card per task_id and updates it in place", () => {
    const box = document.createElement("div");
    const first = upsertProgressCard(box, {
      task_id: "t1",
      steps: [
        { label: "Ler", status: "running" },
        { label: "Gerar", status: "pending" },
      ],
    });
    box.append(document.createElement("p"));
    const again = upsertProgressCard(box, {
      task_id: "t1",
      steps: [
        { label: "Ler", status: "done" },
        { label: "Gerar", status: "running" },
      ],
    });
    expect(again).toBe(first);
    expect(box.querySelectorAll(".progress-card")).toHaveLength(1);
    expect(box.firstElementChild).toBe(first);
    expect(first.querySelector(".progress-count")?.textContent).toBe(
      "1/2 concluídos",
    );
    const states = [
      ...first.querySelectorAll<HTMLElement>(".progress-step"),
    ].map((li) => li.dataset.status);
    expect(states).toEqual(["done", "running"]);
  });

  it("gives a different task its own card", () => {
    const box = document.createElement("div");
    upsertProgressCard(box, { task_id: "a", steps: [] });
    upsertProgressCard(box, { task_id: "b", steps: [] });
    expect(box.querySelectorAll(".progress-card")).toHaveLength(2);
  });
});
