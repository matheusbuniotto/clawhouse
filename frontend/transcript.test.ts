import { expect, test, vi } from "vitest";

import {
  appendToolActivity,
  markRunningToolsError,
  renderAssistantTurn,
  renderInlineApproval,
  renderMarkdown,
  renderUserTurn,
} from "./transcript";

function mount(source: string): HTMLElement {
  const host = document.createElement("div");
  host.append(renderMarkdown(source));
  return host;
}

test("renders headings and paragraphs", () => {
  const host = mount("# Title\n\nBody text.\n\n## Sub");

  expect([...host.children].map((node) => node.tagName)).toEqual(["H1", "P", "H2"]);
  expect(host.querySelector("h1")?.textContent).toBe("Title");
  expect(host.querySelector("p")?.textContent).toBe("Body text.");
  expect(host.querySelector("h2")?.textContent).toBe("Sub");
});

test("renders ordered and unordered lists with inline code", () => {
  const host = mount("- one\n- two\n\n1. first\n2. second\n\nUse `npm` here.");

  expect([...host.children].map((node) => node.tagName)).toEqual(["UL", "OL", "P"]);
  expect([...host.querySelectorAll("ul li")].map((node) => node.textContent)).toEqual([
    "one",
    "two",
  ]);
  expect([...host.querySelectorAll("ol li")].map((node) => node.textContent)).toEqual([
    "first",
    "second",
  ]);
  expect(host.querySelector("p code")?.textContent).toBe("npm");
  expect(host.querySelector("p")?.textContent).toBe("Use npm here.");
});

test("renders blockquotes and links, refusing unsafe link schemes", () => {
  const host = mount("> quoted line\n\nSee [docs](/docs) and [bad](javascript:steal).");

  expect(host.querySelector("blockquote")?.textContent).toBe("quoted line");
  const anchors = host.querySelectorAll("a");
  expect(anchors).toHaveLength(1);
  expect(anchors[0].textContent).toBe("docs");
  expect(anchors[0].getAttribute("href")).toBe("/docs");
  expect(host.querySelector("p")?.textContent).toBe("See docs and bad.");
});

test("escapes raw HTML and event handlers from model output", () => {
  const source = '<img src=x onerror="alert(1)"> <script>alert(1)</script>';
  const host = mount(source);

  expect(host.querySelector("img")).toBeNull();
  expect(host.querySelector("script")).toBeNull();
  expect(host.textContent).toBe(source);
});

test("renders fenced code blocks with a working copy control", async () => {
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });

  const host = mount("```ts\nconst x = 1;\n```");

  const block = host.querySelector(".code-block") as HTMLElement;
  expect(block.querySelector(".code-lang")?.textContent).toBe("ts");
  expect(block.querySelector("pre code")?.textContent).toBe("const x = 1;");
  const copy = block.querySelector(".code-copy") as HTMLButtonElement;
  expect(copy.textContent).toBe("Copy");

  copy.click();
  await vi.waitFor(() => expect(copy.textContent).toBe("Copied"));
  expect(writeText).toHaveBeenCalledTimes(1);
  expect(writeText).toHaveBeenCalledWith("const x = 1;");
});

test("highlights fenced code with token classes while preserving the text", () => {
  const host = mount('```json\n{"a": 1}\n```');

  const code = host.querySelector("pre code") as HTMLElement;
  expect(code.textContent).toBe('{"a": 1}');
  expect(code.querySelector(".tok-key")?.textContent).toBe('"a"');
  expect(code.querySelector(".tok-number")?.textContent).toBe("1");
});

test("renders pipe tables with a header row", () => {
  const host = mount("| Name | Qty |\n| --- | --- |\n| Nails | 4 |\n| Bolts | 2 |");

  const table = host.querySelector("table") as HTMLTableElement;
  expect([...table.querySelectorAll("thead th")].map((cell) => cell.textContent)).toEqual([
    "Name",
    "Qty",
  ]);
  expect(
    [...table.querySelectorAll("tbody tr")].map((row) =>
      [...row.querySelectorAll("td")].map((cell) => cell.textContent),
    ),
  ).toEqual([
    ["Nails", "4"],
    ["Bolts", "2"],
  ]);
});

test("user turns keep a tinted bubble, assistant turns have no bubble", () => {
  const user = renderUserTurn('<b>hi</b>');
  expect(user.tagName).toBe("P");
  expect(user.className).toBe("bubble user");
  expect(user.textContent).toBe("<b>hi</b>");
  expect(user.querySelector("b")).toBeNull();

  const assistant = renderAssistantTurn("# Hi\n\ntext");
  expect(assistant.className).toBe("assistant");
  expect(assistant.querySelector("h1")?.textContent).toBe("Hi");
  expect(assistant.querySelector(".bubble")).toBeNull();
});

test("a tool call becomes a collapsible row with a running chip and summary", () => {
  const host = document.createElement("div");
  appendToolActivity(host, { event: "tool_call", name: "lookup", arguments: '{"q":"notes"}' });

  const row = host.querySelector(".tool-row") as HTMLDetailsElement;
  expect(row.tagName).toBe("DETAILS");
  expect(row.dataset.state).toBe("running");
  expect(row.open).toBe(false);
  expect(row.querySelector(".tool-name")?.textContent).toBe("lookup");
  const chip = row.querySelector(".tool-status") as HTMLElement;
  expect(chip.textContent).toBe("Running");
  expect(chip.dataset.state).toBe("running");
  expect(row.querySelector(".tool-summary")).toBeNull();
  expect(row.querySelector(".tool-input")?.textContent).toBe('{"q":"notes"}');
  expect(row.querySelector(".tool-output")).toBeNull();

  row.open = true;
  expect(row.open).toBe(true);
  expect(row.querySelector(".tool-body")?.contains(row.querySelector(".tool-input"))).toBe(true);
});

test("a tool result completes the same row with an OK chip and output", () => {
  const host = document.createElement("div");
  appendToolActivity(host, { event: "tool_call", name: "lookup", arguments: "{}" });
  appendToolActivity(host, { event: "tool_result", name: "lookup", content: "42" });

  expect(host.querySelectorAll(".tool-row")).toHaveLength(1);
  const row = host.querySelector(".tool-row") as HTMLElement;
  expect(row.dataset.state).toBe("ok");
  const chip = row.querySelector(".tool-status") as HTMLElement;
  expect(chip.textContent).toBe("OK");
  expect(chip.dataset.state).toBe("ok");
  expect(row.querySelector(".tool-output")?.textContent).toBe("42");
});

test("a failed call marks the running row with an Error chip", () => {
  const host = document.createElement("div");
  appendToolActivity(host, { event: "tool_call", name: "lookup", arguments: "{}" });
  markRunningToolsError(host, "boom");

  const row = host.querySelector(".tool-row") as HTMLElement;
  expect(row.dataset.state).toBe("error");
  expect(row.querySelector(".tool-status")?.textContent).toBe("Error");
  expect(row.querySelector(".tool-output")?.textContent).toBe("boom");
});

test("tool input and output are never parsed as HTML", () => {
  const host = document.createElement("div");
  appendToolActivity(host, { event: "tool_call", name: "x", arguments: "<img src=x onerror=1>" });
  appendToolActivity(host, { event: "tool_result", name: "x", content: "<script>alert(1)</script>" });

  expect(host.querySelector("img")).toBeNull();
  expect(host.querySelector("script")).toBeNull();
  expect(host.querySelector(".tool-input")?.textContent).toBe("<img src=x onerror=1>");
  expect(host.querySelector(".tool-output")?.textContent).toBe("<script>alert(1)</script>");
});

test("renders tabular result when tool output contains columns and rows", () => {
  const host = document.createElement("div");
  const data = JSON.stringify({
    columns: ["id", "val"],
    rows: [[1, "apple"], [2, "banana"]],
    row_count: 2,
  });
  appendToolActivity(host, { event: "tool_call", name: "query", arguments: "{}" });
  appendToolActivity(host, { event: "tool_result", name: "query", content: data });

  const table = host.querySelector(".tabular-table");
  expect(table).not.toBeNull();
  expect(host.querySelector(".tabular-count")?.textContent).toBe("2 rows");
  const headers = [...host.querySelectorAll(".tabular-table th")].map((th) => th.textContent);
  expect(headers).toEqual(["id", "val"]);
  const cells = [...host.querySelectorAll(".tabular-table td")].map((td) => td.textContent);
  expect(cells).toEqual(["1", "apple", "2", "banana"]);
});

function renderToolResult(content: unknown): HTMLElement {
  const host = document.createElement("div");
  appendToolActivity(host, { event: "tool_call", name: "jobs_get_run", arguments: "{}" });
  appendToolActivity(host, {
    event: "tool_result",
    name: "jobs_get_run",
    content: JSON.stringify(content),
  });
  return host;
}

test("renders a finished job run as a card with a success badge and id chips", () => {
  const host = renderToolResult({
    run_id: 77,
    job_id: 5,
    life_cycle_state: "TERMINATED",
    result_state: "SUCCESS",
    duration_ms: 3500,
    url: "https://example.cloud.databricks.com/#job/5/run/77",
  });

  const badge = host.querySelector<HTMLElement>(".job-badge");
  expect(badge?.textContent).toBe("SUCCESS");
  expect(badge?.dataset.state).toBe("success");
  const chips = [...host.querySelectorAll(".job-chip")].map((chip) => chip.textContent);
  expect(chips).toEqual(["Job 5", "Run 77", "3.5s"]);
  const link = host.querySelector<HTMLAnchorElement>(".job-link");
  expect(link?.href).toBe("https://example.cloud.databricks.com/#job/5/run/77");
  expect(link?.rel).toBe("noopener noreferrer");
});

test("a terminated run that did not succeed gets a failed badge", () => {
  const host = renderToolResult({
    run_id: 78,
    job_id: 5,
    life_cycle_state: "TERMINATED",
    result_state: "FAILED",
  });

  const badge = host.querySelector<HTMLElement>(".job-badge");
  expect(badge?.textContent).toBe("FAILED");
  expect(badge?.dataset.state).toBe("failed");
});

test("in-flight runs show their life cycle state", () => {
  const pending = renderToolResult({ run_id: 1, job_id: 5, life_cycle_state: "PENDING" });
  const running = renderToolResult({ run_id: 2, job_id: 5, life_cycle_state: "RUNNING" });

  expect(pending.querySelector<HTMLElement>(".job-badge")?.dataset.state).toBe("pending");
  expect(pending.querySelector(".job-badge")?.textContent).toBe("PENDING");
  expect(running.querySelector<HTMLElement>(".job-badge")?.dataset.state).toBe("running");
  expect(running.querySelector(".job-badge")?.textContent).toBe("RUNNING");
});

test("a freshly triggered run shows id chips without a badge", () => {
  const host = renderToolResult({ run_id: 901, job_id: 5 });

  expect(host.querySelector(".job-badge")).toBeNull();
  const chips = [...host.querySelectorAll(".job-chip")].map((chip) => chip.textContent);
  expect(chips).toEqual(["Job 5", "Run 901"]);
});

test("renders a job list as one row per job", () => {
  const host = renderToolResult({
    jobs: [
      { job_id: 5, name: "nightly", creator: "a@x.com" },
      { job_id: 6, name: "hourly", creator: "b@x.com" },
    ],
    job_count: 2,
  });

  const names = [...host.querySelectorAll(".job-name")].map((n) => n.textContent);
  expect(names).toEqual(["nightly", "hourly"]);
  const ids = [...host.querySelectorAll(".job-chip")].map((chip) => chip.textContent);
  expect(ids).toEqual(["Job 5", "Job 6"]);
});

test("a run url that is not http(s) is not linked", () => {
  const host = renderToolResult({ run_id: 1, job_id: 5, url: "javascript:alert(1)" });

  expect(host.querySelector(".job-link")).toBeNull();
});

test("job cards keep the raw JSON available", () => {
  const host = renderToolResult({ run_id: 901, job_id: 5 });

  expect(host.querySelector(".tabular-raw pre")?.textContent).toBe(
    JSON.stringify({ run_id: 901, job_id: 5 }),
  );
});

test("a created or edited job shows its id chip", () => {
  const created = renderToolResult({ job_id: 42, name: "etl" });
  const edited = renderToolResult({ job_id: 5, updated: true });

  expect([...created.querySelectorAll(".job-chip")].map((c) => c.textContent)).toEqual(["Job 42"]);
  expect(created.querySelector(".job-name")?.textContent).toBe("etl");
  expect([...edited.querySelectorAll(".job-chip")].map((c) => c.textContent)).toEqual(["Job 5"]);
});

test("renders inline approval card and handles approval resolution", async () => {
  const container = document.createElement("div");
  appendToolActivity(container, { event: "tool_call", name: "jobs_create" });

  const toolRow = container.querySelector<HTMLDetailsElement>(".tool-row");
  expect(toolRow?.dataset.state).toBe("running");

  let resolvedReply: string | undefined;
  const onResolved = (reply?: string) => {
    resolvedReply = reply;
  };

  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({ status: "approved", reply: "Created job" }),
  });
  vi.stubGlobal("fetch", fetchMock);

  renderInlineApproval(container, "appr-123", "jobs_create", onResolved);

  expect(toolRow?.dataset.state).toBe("pending");
  expect(toolRow?.querySelector(".tool-status")?.textContent).toBe("Approval Needed");
  expect(container.querySelector(".approval-action-bar")).not.toBeNull();
  expect(container.querySelector(".approval-msg")?.textContent).toContain(
    "Approval required to execute jobs_create",
  );

  const approveBtn = container.querySelector<HTMLButtonElement>(".btn-approve");
  approveBtn?.click();

  await Promise.resolve();
  await Promise.resolve();

  expect(fetchMock).toHaveBeenCalledWith("/api/approvals/appr-123/approve", { method: "POST" });
  expect(resolvedReply).toBe("Created job");
  expect(toolRow?.dataset.state).toBe("ok");
  expect(container.querySelector(".approval-msg")?.textContent).toContain("✓ Approved jobs_create");

  vi.unstubAllGlobals();
});

const SHEET_ID = "1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789";

test("a create sheet approval card shows the question, exact rows, and warning", () => {
  const container = document.createElement("div");
  renderInlineApproval(
    container,
    "appr-sheet-1",
    "create_google_sheet",
    () => {},
    JSON.stringify({
      title: "Top Products",
      rows: [
        ["product", "sales"],
        ["Widget", 100],
      ],
    }),
  );

  const card = container.querySelector(".approval-action-bar");
  expect(card).not.toBeNull();
  expect(card?.querySelector(".approval-msg")?.textContent).toBe(
    'Create the spreadsheet "Top Products" in your Google Drive?',
  );
  expect(card?.textContent).toContain("2 rows × 2 columns");
  expect(card?.textContent).toContain("leave Databricks");
  expect(card?.querySelector(".approval-preview")?.textContent).toBe(
    "product\tsales\nWidget\t100",
  );
});

test("an update sheet approval links the spreadsheet and bounds the preview", () => {
  const container = document.createElement("div");
  renderInlineApproval(
    container,
    "appr-sheet-2",
    "update_google_sheet",
    () => {},
    JSON.stringify({
      spreadsheet_id: SHEET_ID,
      tab: "Página1",
      first_column: "B",
      first_row: 4,
      rows: [["x", "y"]],
    }),
  );

  const card = container.querySelector(".approval-action-bar");
  expect(card?.querySelector(".approval-msg")?.textContent).toBe(
    'Overwrite 1 rows on tab "Página1" starting at B4?',
  );
  expect(card?.textContent).toContain("leave Databricks");
  const link = card?.querySelector("a");
  expect(link?.getAttribute("href")).toBe(`https://docs.google.com/spreadsheets/d/${SHEET_ID}`);

  const bad = document.createElement("div");
  renderInlineApproval(
    bad,
    "appr-bad",
    "update_google_sheet",
    () => {},
    JSON.stringify({ spreadsheet_id: "../../evil", tab: "Página1", rows: [["x"]] }),
  );
  expect(bad.querySelector("a")).toBeNull();
});

test("a sheets result links only a docs.google.com spreadsheet url", () => {
  const container = document.createElement("div");
  appendToolActivity(container, {
    event: "tool_call",
    name: "create_google_sheet",
    arguments: "{}",
  });
  appendToolActivity(container, {
    event: "tool_result",
    content: JSON.stringify({
      written: true,
      url: `https://docs.google.com/spreadsheets/d/${SHEET_ID}`,
    }),
  });
  expect(container.querySelector("a")?.getAttribute("href")).toBe(
    `https://docs.google.com/spreadsheets/d/${SHEET_ID}`,
  );

  const evil = document.createElement("div");
  appendToolActivity(evil, {
    event: "tool_call",
    name: "create_google_sheet",
    arguments: "{}",
  });
  appendToolActivity(evil, {
    event: "tool_result",
    content: JSON.stringify({ written: true, url: "https://evil.test/x" }),
  });
  expect(evil.querySelector(".approval-link")).toBeNull();
});

test("renders assistant copy action button", () => {
  const node = renderAssistantTurn("# Header\n\nSome answer");
  const copyBtn = node.querySelector(".assistant-action-btn.copy-btn");
  expect(copyBtn).not.toBeNull();
  expect(copyBtn?.getAttribute("aria-label")).toBe("Copy markdown");
});

test("clicking copy button writes to clipboard", async () => {
  const writeText = vi.fn().mockResolvedValue(undefined);
  vi.stubGlobal("navigator", { clipboard: { writeText } });

  const text = "# Header\n\nSome answer";
  const node = renderAssistantTurn(text);
  const copyBtn = node.querySelector(".assistant-action-btn.copy-btn") as HTMLButtonElement;
  copyBtn.click();

  expect(writeText).toHaveBeenCalledWith(text);
});

test("displays copied confirmation text", async () => {
  const writeText = vi.fn().mockResolvedValue(undefined);
  vi.stubGlobal("navigator", { clipboard: { writeText } });

  const node = renderAssistantTurn("test content");
  const copyBtn = node.querySelector(".assistant-action-btn.copy-btn") as HTMLButtonElement;
  copyBtn.click();

  await vi.waitFor(() => {
    expect(copyBtn.textContent).toContain("Copied!");
    expect(copyBtn.classList.contains("copied")).toBe(true);
  });
});

test("handles clipboard rejection gracefully", async () => {
  const writeText = vi.fn().mockRejectedValue(new Error("Permission denied"));
  vi.stubGlobal("navigator", { clipboard: { writeText } });

  const node = renderAssistantTurn("test content");
  const copyBtn = node.querySelector(".assistant-action-btn.copy-btn") as HTMLButtonElement;
  copyBtn.click();

  await vi.waitFor(() => {
    expect(copyBtn.textContent).toContain("Failed to copy");
  });
});

test("run_python_analysis renders result_state duration_ms and logs", () => {
  const host = document.createElement("div");
  appendToolActivity(host, {
    event: "tool_result",
    name: "run_python_analysis",
    content: JSON.stringify({
      result_state: "SUCCESS",
      duration_ms: 2000,
      logs: "revenue by region",
    }),
  });
  expect(host.textContent).toContain("SUCCESS");
  expect(host.textContent).toContain("2000");
  expect(host.textContent).toContain("revenue by region");
});

test("run_python_analysis failure renders error and run_page_url", () => {
  const host = document.createElement("div");
  appendToolActivity(host, {
    event: "tool_result",
    name: "run_python_analysis",
    content: JSON.stringify({
      result_state: "FAILED",
      error: "boom",
      run_page_url: "https://example.cloud.databricks.com/run/9",
    }),
  });
  expect(host.querySelector(".analysis-error")?.textContent).toBe("boom");
  expect(host.querySelector("a")?.getAttribute("href")).toBe(
    "https://example.cloud.databricks.com/run/9",
  );

  const timed = document.createElement("div");
  appendToolActivity(timed, {
    event: "tool_result",
    name: "run_python_analysis",
    content: JSON.stringify({
      status: "TIMED_OUT_WAITING",
      run_page_url: "https://example.cloud.databricks.com/run/11",
    }),
  });
  expect(timed.textContent).toContain("TIMED_OUT_WAITING");
  expect(timed.querySelector("a")?.getAttribute("href")).toBe(
    "https://example.cloud.databricks.com/run/11",
  );
});
