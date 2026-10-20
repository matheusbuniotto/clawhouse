import { QueryClient } from "@tanstack/react-query";
import { createMemoryHistory, createRouter, RouterProvider } from "@tanstack/react-router";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { routeTree } from "@/routeTree.gen";
import type { Approval, Entry, Question } from "@/lib/api";

type Frame = { event: string; data: Record<string, unknown> };

const ASK = JSON.stringify({
  question: "How often?",
  options: ["Hourly", "Daily", "Weekly"],
  default: "Daily",
  multi: false,
});

function sse(frames: Frame[]): Response {
  const body = frames
    .map((frame) => `event: ${frame.event}\ndata: ${JSON.stringify(frame.data)}\n\n`)
    .join("");
  return new Response(body, { status: 200, headers: { "content-type": "text/event-stream" } });
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function pair(name: string, args = "{}", result = "ok"): Entry[] {
  return [
    { role: "tool_call", content: args, tool_name: name },
    { role: "tool_result", content: result, tool_name: name },
  ];
}

async function renderChat(
  opts: {
    entries?: Entry[];
    questions?: Question[];
    pending?: Approval[];
    turn?: Frame[];
    answer?: Response | "throw";
    decision?: Response | "throw";
  } = {},
) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = (init?.method ?? "GET").toUpperCase();
    if (url.includes("/api/questions/") && method === "POST") {
      if (opts.answer === "throw") throw new TypeError("Failed to fetch");
      return (
        opts.answer ??
        sse([
          { event: "token", data: { text: "after-answer" } },
          { event: "done", data: { status: "ok", reply: "after-answer" } },
        ])
      );
    }
    if (url.includes("/api/approvals/") && method === "POST") {
      if (opts.decision === "throw") throw new TypeError("Failed to fetch");
      return (
        opts.decision ??
        sse([
          { event: "token", data: { text: "after-decision" } },
          { event: "done", data: { status: "ok", reply: "after-decision" } },
        ])
      );
    }
    if (url.includes("/api/me")) return json({ user_id: "you" });
    if (url.includes("/api/models")) return json([{ id: "m", label: "Model", default: true }]);
    if (url.includes("/api/agents"))
      return json([
        { id: "main", name: "main", signature_emoji: "🦞", description: "", system_prompt: "" },
      ]);
    if (url.includes("/questions")) return json(opts.questions ?? []);
    if (url.includes("/transcript"))
      return json({ entries: opts.entries ?? [], run_state: "idle" });
    if (url.includes("/turns"))
      return sse(opts.turn ?? [{ event: "done", data: { status: "ok", reply: "" } }]);
    if (url.includes("/api/approvals")) return json({ pending: opts.pending ?? [], history: [] });
    if (url.includes("/api/sessions/sess"))
      return json({ id: "sess", title: "Chat", created_at: "2026-10-20T00:00:00Z" });
    if (url.includes("/api/sessions")) return json({ sessions: [] });
    return json({ error: "not found" }, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createRouter({
    routeTree,
    history: createMemoryHistory({ initialEntries: ["/?session=sess"] }),
    context: { queryClient },
  });
  await router.load();
  render(<RouterProvider router={router} />);
  await waitFor(() => {
    expect(fetchMock.mock.calls.some((call) => String(call[0]).includes("/transcript"))).toBe(true);
  });
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
  return fetchMock;
}

async function sendTurn() {
  const box = await screen.findByPlaceholderText("Message @main…");
  fireEvent.change(box, { target: { value: "hi" } });
  fireEvent.click(screen.getByRole("button", { name: "Send message" }));
}

function posted(fetchMock: ReturnType<typeof vi.fn>, part: string): RequestInit | undefined {
  const call = fetchMock.mock.calls.find(
    (item) =>
      String(item[0]).includes(part) && (item[1] as RequestInit | undefined)?.method === "POST",
  );
  return call?.[1] as RequestInit | undefined;
}

function question(id: string, extra: Partial<Question> = {}): Question {
  return {
    id,
    session_id: "sess",
    question: "How often?",
    options: ["Hourly", "Daily"],
    default: "Daily",
    multi: false,
    status: "pending",
    ...extra,
  };
}

describe("chat activity", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("two tool calls share one group", async () => {
    await renderChat({
      turn: [
        { event: "tool_call", data: { name: "lookup", arguments: "{}" } },
        { event: "tool_result", data: { name: "lookup", content: "1" } },
        { event: "tool_call", data: { name: "query", arguments: "{}" } },
        { event: "tool_result", data: { name: "query", content: "2" } },
        { event: "done", data: { status: "ok", reply: "" } },
      ],
    });
    await sendTurn();
    expect(await screen.findByText("2 calls")).toBeInTheDocument();
    expect(screen.getAllByText("Expand tool calls")).toHaveLength(1);
  });

  it("a tool group starts collapsed", async () => {
    await renderChat({ entries: pair("lookup", '{"q":"notes"}', "1") });
    expect(await screen.findByText("Expand tool calls")).toBeInTheDocument();
    expect(screen.queryByText('{"q":"notes"}')).toBeNull();
  });

  it("group summary reads Expand tool calls and the call count", async () => {
    await renderChat({ entries: pair("lookup") });
    expect(await screen.findByText("Expand tool calls")).toBeInTheDocument();
    expect(screen.getByText("1 call")).toBeInTheDocument();
    cleanup();
    await renderChat({ entries: [...pair("lookup"), ...pair("query")] });
    expect(await screen.findByText("2 calls")).toBeInTheDocument();
    expect(screen.getByText("Expand tool calls")).toBeInTheDocument();
  });

  it("expanding a tool group reads Hide tool calls", async () => {
    await renderChat({ entries: pair("lookup", '{"q":"notes"}') });
    fireEvent.click(await screen.findByText("Expand tool calls"));
    expect(screen.getByText("Hide tool calls")).toBeInTheDocument();
    expect(screen.getByText('{"q":"notes"}')).toBeInTheDocument();
  });

  it("a break between tool calls starts a second group", async () => {
    const stored: { kind: string; entries: Entry[] }[] = [
      {
        kind: "user message",
        entries: [
          ...pair("lookup"),
          { role: "user", content: "next", tool_name: null },
          ...pair("query"),
        ],
      },
      {
        kind: "assistant text",
        entries: [
          ...pair("lookup"),
          { role: "assistant", content: "between", tool_name: null },
          ...pair("query"),
        ],
      },
      {
        kind: "notice",
        entries: [
          ...pair("lookup"),
          { role: "notice", content: "note", tool_name: null },
          ...pair("query"),
        ],
      },
    ];
    for (const item of stored) {
      cleanup();
      await renderChat({ entries: item.entries });
      expect(await screen.findAllByText("Expand tool calls")).toHaveLength(2);
    }
    cleanup();
    await renderChat({
      turn: [
        { event: "tool_call", data: { name: "lookup", arguments: "{}" } },
        { event: "tool_result", data: { name: "lookup", content: "1" } },
        {
          event: "question",
          data: {
            question_id: "q-break",
            question: "Pick?",
            options: ["A", "B"],
            default: "A",
            multi: false,
          },
        },
        { event: "tool_call", data: { name: "query", arguments: "{}" } },
        { event: "tool_result", data: { name: "query", content: "2" } },
        { event: "done", data: { status: "ok", reply: "" } },
      ],
    });
    await sendTurn();
    expect(await screen.findAllByText("Expand tool calls")).toHaveLength(2);

    cleanup();
    await renderChat({
      turn: [
        { event: "tool_call", data: { name: "lookup", arguments: "{}" } },
        { event: "tool_result", data: { name: "lookup", content: "1" } },
        {
          event: "approval_required",
          data: { approval_id: "appr-break", name: "jobs_create", arguments: "{}" },
        },
        { event: "tool_call", data: { name: "query", arguments: "{}" } },
        { event: "tool_result", data: { name: "query", content: "2" } },
        { event: "done", data: { status: "pending_approval", reply: "" } },
      ],
    });
    await sendTurn();
    expect(await screen.findAllByText("Expand tool calls")).toHaveLength(2);
  });

  it("a running tool group reads Running", async () => {
    await renderChat({
      turn: [
        { event: "tool_call", data: { name: "query", arguments: "{}" } },
        { event: "done", data: { status: "ok", reply: "" } },
      ],
    });
    await sendTurn();
    expect(await screen.findByText("Running query...")).toBeInTheDocument();
  });

  it("a tool result leaves the running state", async () => {
    await renderChat({
      turn: [
        { event: "tool_call", data: { name: "query", arguments: "{}" } },
        { event: "tool_result", data: { name: "query", content: "done" } },
        { event: "done", data: { status: "ok", reply: "" } },
      ],
    });
    await sendTurn();
    await screen.findByText("1 call");
    expect(screen.queryByText(/Running/)).toBeNull();
    fireEvent.click(screen.getByText("Expand tool calls"));
    expect(screen.getByText("query").closest("[data-state]")).toHaveAttribute("data-state", "ok");
  });

  it("an error frame sets the running tool to error", async () => {
    await renderChat({
      turn: [
        { event: "tool_call", data: { name: "query", arguments: "{}" } },
        { event: "error", data: { error: "The turn failed." } },
      ],
    });
    await sendTurn();
    await screen.findByText("The turn failed.");
    fireEvent.click(screen.getByText("Expand tool calls"));
    expect(screen.getByText("query").closest("[data-state]")).toHaveAttribute(
      "data-state",
      "error",
    );
  });

  it("ask_user is not a tool row", async () => {
    await renderChat({
      turn: [
        { event: "tool_call", data: { name: "ask_user", arguments: ASK } },
        {
          event: "question",
          data: {
            question_id: "q1",
            question: "How often?",
            options: ["Hourly", "Daily"],
            default: "Daily",
            multi: false,
          },
        },
        { event: "done", data: { status: "pending_approval", reply: "" } },
      ],
    });
    await sendTurn();
    expect(await screen.findByText("How often?")).toBeInTheDocument();
    expect(screen.queryByText("ask_user")).toBeNull();
  });

  it("a question frame shows the question and one button per option", async () => {
    await renderChat({
      turn: [
        {
          event: "question",
          data: {
            question_id: "q1",
            question: "How often?",
            options: ["Hourly", "Daily"],
            default: null,
            multi: false,
          },
        },
        { event: "done", data: { status: "pending_approval", reply: "" } },
      ],
    });
    await sendTurn();
    expect(await screen.findByText("How often?")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Hourly" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Daily" })).toBeInTheDocument();
  });

  it("a question card does not show the arguments JSON", async () => {
    await renderChat({
      turn: [
        { event: "tool_call", data: { name: "ask_user", arguments: ASK } },
        {
          event: "question",
          data: {
            question_id: "q1",
            question: "How often?",
            options: ["Hourly", "Daily", "Weekly"],
            default: "Daily",
            multi: false,
          },
        },
        { event: "done", data: { status: "pending_approval", reply: "" } },
      ],
    });
    await sendTurn();
    expect(await screen.findByText("How often?")).toBeInTheDocument();
    expect(screen.queryByText(ASK)).toBeNull();
  });

  it("clicking Daily posts the answer and appends the resumed token", async () => {
    const fetchMock = await renderChat({
      turn: [
        {
          event: "question",
          data: {
            question_id: "q1",
            question: "How often?",
            options: ["Hourly", "Daily"],
            default: "Hourly",
            multi: false,
          },
        },
        { event: "done", data: { status: "pending_approval", reply: "" } },
      ],
    });
    await sendTurn();
    fireEvent.click(await screen.findByRole("button", { name: "Daily" }));
    expect(await screen.findByText("after-answer")).toBeInTheDocument();
    const init = posted(fetchMock, "/api/questions/q1/answer");
    expect(new Headers(init?.headers).get("accept")).toBe("text/event-stream");
    expect(JSON.parse(String(init?.body))).toEqual({ selected: ["Daily"] });
  });

  it("Send stays disabled until a multi option is toggled", async () => {
    await renderChat({
      turn: [
        {
          event: "question",
          data: {
            question_id: "q1",
            question: "How often?",
            options: ["Hourly", "Weekly"],
            default: null,
            multi: true,
          },
        },
        { event: "done", data: { status: "pending_approval", reply: "" } },
      ],
    });
    await sendTurn();
    expect(await screen.findByRole("button", { name: "Send" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Weekly" }));
    expect(screen.getByRole("button", { name: "Send" })).toBeEnabled();
  });

  it("Send posts Weekly then Hourly", async () => {
    const fetchMock = await renderChat({
      turn: [
        {
          event: "question",
          data: {
            question_id: "q1",
            question: "How often?",
            options: ["Hourly", "Daily", "Weekly"],
            default: "Daily",
            multi: true,
          },
        },
        { event: "done", data: { status: "pending_approval", reply: "" } },
      ],
    });
    await sendTurn();
    fireEvent.click(await screen.findByRole("button", { name: "Weekly" }));
    fireEvent.click(screen.getByRole("button", { name: "Hourly" }));
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await screen.findByText("after-answer");
    const init = posted(fetchMock, "/api/questions/q1/answer");
    expect(JSON.parse(String(init?.body))).toEqual({ selected: ["Weekly", "Hourly"] });
  });

  it("the default option button includes default", async () => {
    await renderChat({
      turn: [
        {
          event: "question",
          data: {
            question_id: "q1",
            question: "How often?",
            options: ["Hourly", "Daily"],
            default: "Daily",
            multi: false,
          },
        },
        { event: "done", data: { status: "pending_approval", reply: "" } },
      ],
    });
    await sendTurn();
    expect(await screen.findByRole("button", { name: /Daily/ })).toHaveTextContent("default");
    expect(screen.getByRole("button", { name: "Hourly" })).not.toHaveTextContent("default");
  });

  it("a non-200 answer shows Could not send the answer", async () => {
    await renderChat({
      answer: json({ detail: "no" }, 409),
      turn: [
        {
          event: "question",
          data: {
            question_id: "q1",
            question: "How often?",
            options: ["Hourly", "Daily"],
            default: "Hourly",
            multi: false,
          },
        },
        { event: "done", data: { status: "pending_approval", reply: "" } },
      ],
    });
    await sendTurn();
    fireEvent.click(await screen.findByRole("button", { name: "Daily" }));
    expect(await screen.findByText("Could not send the answer.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Daily" })).toBeEnabled();
    expect(screen.getByRole("button", { name: /Hourly/ })).toBeEnabled();
  });

  it("a thrown answer shows Network error while sending the answer", async () => {
    await renderChat({
      answer: "throw",
      turn: [
        {
          event: "question",
          data: {
            question_id: "q1",
            question: "How often?",
            options: ["Hourly", "Daily"],
            default: "Hourly",
            multi: false,
          },
        },
        { event: "done", data: { status: "pending_approval", reply: "" } },
      ],
    });
    await sendTurn();
    fireEvent.click(await screen.findByRole("button", { name: "Daily" }));
    expect(await screen.findByText("Network error while sending the answer.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Daily" })).toBeEnabled();
  });

  it("an unanswered question disables the composer", async () => {
    await renderChat({
      turn: [
        {
          event: "question",
          data: {
            question_id: "q1",
            question: "How often?",
            options: ["Hourly", "Daily"],
            default: "Daily",
            multi: false,
          },
        },
        { event: "done", data: { status: "pending_approval", reply: "" } },
      ],
    });
    await sendTurn();
    const box = await screen.findByPlaceholderText("Waiting for your answer.");
    expect(box).toBeDisabled();
  });

  it("a pending question loads as one card", async () => {
    await renderChat({
      entries: [{ role: "tool_call", content: ASK, tool_name: "ask_user" }],
      questions: [question("q-9")],
    });
    expect(await screen.findByText("How often?")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Hourly" })).toHaveLength(1);
    expect(screen.getAllByRole("button", { name: /Daily/ })).toHaveLength(1);
    expect(screen.queryByText("ask_user")).toBeNull();
  });

  it("a stored choice marks Daily", async () => {
    await renderChat({
      entries: [
        { role: "tool_call", content: ASK, tool_name: "ask_user" },
        { role: "tool_result", content: "The user chose: Daily", tool_name: "ask_user" },
      ],
    });
    const daily = await screen.findByRole("button", { name: /Daily/ });
    expect(daily).toBeDisabled();
    expect(daily).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Hourly" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Weekly" })).toBeDisabled();
  });

  it("a stored default marks Daily", async () => {
    await renderChat({
      entries: [
        { role: "tool_call", content: ASK, tool_name: "ask_user" },
        {
          role: "tool_result",
          content: 'No user in this run (scheduled job): picked the default option "Daily".',
          tool_name: "ask_user",
        },
      ],
    });
    const daily = await screen.findByRole("button", { name: /Daily/ });
    expect(daily).toBeDisabled();
    expect(daily).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Hourly" })).toHaveAttribute("aria-pressed", "false");
  });

  it("an approval card sits after the tool group", async () => {
    await renderChat({
      turn: [
        { event: "tool_call", data: { name: "jobs_create", arguments: '{"name":"my_job"}' } },
        {
          event: "approval_required",
          data: { approval_id: "appr-1", name: "jobs_create", arguments: '{"name":"my_job"}' },
        },
        { event: "done", data: { status: "pending_approval", reply: "" } },
      ],
    });
    await sendTurn();
    const approve = await screen.findByRole("button", { name: "Approve" });
    expect(screen.getByRole("button", { name: "Deny" })).toBeInTheDocument();
    expect(screen.getByText("jobs_create")).toBeInTheDocument();
    const group = screen.getByText("Expand tool calls").closest("[data-tool-group]");
    expect(group?.contains(approve)).toBe(false);
    expect(group?.compareDocumentPosition(approve) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("approval arguments start behind a closed Arguments disclosure", async () => {
    await renderChat({
      turn: [
        {
          event: "approval_required",
          data: { approval_id: "appr-1", name: "jobs_create", arguments: '{"name":"my_job"}' },
        },
        { event: "done", data: { status: "pending_approval", reply: "" } },
      ],
    });
    await sendTurn();
    const summary = await screen.findByText("Arguments");
    const details = summary.closest("details");
    expect(details).not.toBeNull();
    expect((details as HTMLDetailsElement).open).toBe(false);
    expect(details).toHaveTextContent('{"name":"my_job"}');
  });

  it("an unresolved approval blocks the composer", async () => {
    await renderChat({
      turn: [
        { event: "tool_call", data: { name: "jobs_create", arguments: "{}" } },
        {
          event: "approval_required",
          data: { approval_id: "appr-1", name: "jobs_create", arguments: "{}" },
        },
        { event: "done", data: { status: "pending_approval", reply: "" } },
      ],
    });
    await sendTurn();
    expect(await screen.findByText("Approval required for jobs_create")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Waiting for approval.")).toBeDisabled();
  });

  it("Approve posts an event stream and reads Approved", async () => {
    const fetchMock = await renderChat({
      turn: [
        {
          event: "approval_required",
          data: { approval_id: "appr-1", name: "jobs_create", arguments: "{}" },
        },
        { event: "done", data: { status: "pending_approval", reply: "" } },
      ],
    });
    await sendTurn();
    fireEvent.click(await screen.findByRole("button", { name: "Approve" }));
    expect(await screen.findByText("Approved jobs_create")).toBeInTheDocument();
    expect(screen.getByText("after-decision")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Deny" })).toBeNull();
    const init = posted(fetchMock, "/api/approvals/appr-1/approve");
    expect(new Headers(init?.headers).get("accept")).toBe("text/event-stream");
  });

  it("Deny posts an event stream and reads Denied", async () => {
    const fetchMock = await renderChat({
      turn: [
        {
          event: "approval_required",
          data: { approval_id: "appr-1", name: "jobs_create", arguments: "{}" },
        },
        { event: "done", data: { status: "pending_approval", reply: "" } },
      ],
    });
    await sendTurn();
    fireEvent.click(await screen.findByRole("button", { name: "Deny" }));
    expect(await screen.findByText("Denied jobs_create")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Deny" })).toBeNull();
    const init = posted(fetchMock, "/api/approvals/appr-1/deny");
    expect(new Headers(init?.headers).get("accept")).toBe("text/event-stream");
  });

  it("a non-200 approve shows Failed to approve tool call", async () => {
    await renderChat({
      decision: json({ detail: "no" }, 409),
      turn: [
        {
          event: "approval_required",
          data: { approval_id: "appr-1", name: "jobs_create", arguments: "{}" },
        },
        { event: "done", data: { status: "pending_approval", reply: "" } },
      ],
    });
    await sendTurn();
    fireEvent.click(await screen.findByRole("button", { name: "Approve" }));
    expect(await screen.findByText("Failed to approve tool call.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Deny" })).toBeEnabled();
  });

  it("a non-200 deny shows Failed to deny tool call", async () => {
    await renderChat({
      decision: json({ detail: "no" }, 409),
      turn: [
        {
          event: "approval_required",
          data: { approval_id: "appr-1", name: "jobs_create", arguments: "{}" },
        },
        { event: "done", data: { status: "pending_approval", reply: "" } },
      ],
    });
    await sendTurn();
    fireEvent.click(await screen.findByRole("button", { name: "Deny" }));
    expect(await screen.findByText("Failed to deny tool call.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Deny" })).toBeEnabled();
  });

  it("a thrown approve shows Network error while approving tool call", async () => {
    await renderChat({
      decision: "throw",
      turn: [
        {
          event: "approval_required",
          data: { approval_id: "appr-1", name: "jobs_create", arguments: "{}" },
        },
        { event: "done", data: { status: "pending_approval", reply: "" } },
      ],
    });
    await sendTurn();
    fireEvent.click(await screen.findByRole("button", { name: "Approve" }));
    expect(await screen.findByText("Network error while approving tool call.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Deny" })).toBeEnabled();
  });

  it("a thrown deny shows Network error while denying tool call", async () => {
    await renderChat({
      decision: "throw",
      turn: [
        {
          event: "approval_required",
          data: { approval_id: "appr-1", name: "jobs_create", arguments: "{}" },
        },
        { event: "done", data: { status: "pending_approval", reply: "" } },
      ],
    });
    await sendTurn();
    fireEvent.click(await screen.findByRole("button", { name: "Deny" }));
    expect(await screen.findByText("Network error while denying tool call.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Deny" })).toBeEnabled();
  });

  it("a pending approval for this session loads as one card", async () => {
    const pending: Approval[] = [
      {
        id: "appr-1",
        session_id: "sess",
        tool_name: "jobs_create",
        arguments: "{}",
        status: "pending",
        created_at: "2026-10-20T00:00:00Z",
        resolved_by: null,
      },
      {
        id: "appr-2",
        session_id: "other",
        tool_name: "write_file",
        arguments: "{}",
        status: "pending",
        created_at: "2026-10-20T00:00:00Z",
        resolved_by: null,
      },
    ];
    await renderChat({
      entries: [{ role: "tool_call", content: "{}", tool_name: "jobs_create" }],
      pending,
    });
    expect(await screen.findByRole("button", { name: "Approve" })).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Approve" })).toHaveLength(1);
    expect(screen.getByText("jobs_create")).toBeInTheDocument();
    expect(screen.queryByText("write_file")).toBeNull();
  });
});
