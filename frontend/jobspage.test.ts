import { afterEach, expect, test, vi } from "vitest";

import {
  mount,
  renderJobRow,
  visibilityNote,
  type JobRow,
} from "./jobspage.js";

const SCHEDULE: JobRow = {
  id: "schedule:abc",
  source: "schedule",
  name: "resumo de vendas",
  agent_id: "main",
  cron: "0 5 * * *",
  cron_human: "todo dia às 5h",
  next_run_at: "2099-01-01T08:00:00+00:00",
  last_run: {
    status: "done",
    started_at: "2026-10-14T08:00:00+00:00",
    session_id: "s1",
  },
  can_run: false,
  can_delete: true,
  session_id: "s1",
};

const DATABRICKS: JobRow = {
  id: "databricks:1",
  source: "databricks",
  name: "ETL",
  agent_id: null,
  cron: null,
  cron_human: null,
  next_run_at: null,
  last_run: {
    status: "SUCCESS",
    started_at: "2026-10-14T08:00:00+00:00",
    run_url: "https://x/run/1",
  },
  can_run: true,
  can_delete: false,
};

const noop = { run: async () => {}, remove: async () => {} };

afterEach(() => vi.unstubAllGlobals());

test("a schedule row shows the human cron, agent, session link and only delete", () => {
  const row = renderJobRow(SCHEDULE, noop);
  expect(row.querySelector(".job-when")?.textContent).toBe("todo dia às 5h");
  expect(row.querySelector(".job-agent")?.textContent).toBe("@main");
  expect(
    row.querySelector<HTMLAnchorElement>(".job-open")?.getAttribute("href"),
  ).toBe("/chat?session=s1");
  const labels = [...row.querySelectorAll(".job-action")].map(
    (b) => b.textContent,
  );
  expect(labels).toEqual(["Apagar"]);
});

test("a Databricks row links to the run and only offers run-now", () => {
  const row = renderJobRow(DATABRICKS, noop);
  const link = row.querySelector<HTMLAnchorElement>(".job-open");
  expect(link?.href).toBe("https://x/run/1");
  expect(link?.target).toBe("_blank");
  expect(row.querySelector(".job-when")?.textContent).toBe("Sem agenda");
  const labels = [...row.querySelectorAll(".job-action")].map(
    (b) => b.textContent,
  );
  expect(labels).toEqual(["Rodar agora"]);
});

test("run-now calls the action with the job", async () => {
  const run = vi.fn(async () => {});
  const row = renderJobRow(DATABRICKS, { ...noop, run });
  row.querySelector<HTMLButtonElement>(".job-action")?.click();
  expect(run).toHaveBeenCalledWith(DATABRICKS);
});

test("the ACL fallback is explained", () => {
  expect(visibilityNote({ jobs: [], databricks_visibility: "acl" })).toContain(
    "permissões",
  );
  expect(
    visibilityNote({ jobs: [], databricks_visibility: "user" }),
  ).toBeNull();
  expect(visibilityNote({ jobs: [], databricks_error: "x" })).toContain(
    "Não foi possível",
  );
});

test("mount lists jobs from /api/jobs", async () => {
  const fetchMock = vi.fn(async () => ({
    ok: true,
    json: async () => ({
      jobs: [SCHEDULE, DATABRICKS],
      databricks_visibility: "acl",
    }),
  }));
  vi.stubGlobal("fetch", fetchMock);
  const root = document.createElement("div");
  mount(root);
  await vi.waitFor(() =>
    expect(root.querySelectorAll(".job-row")).toHaveLength(2),
  );
  expect(fetchMock).toHaveBeenCalledWith("/api/jobs");
});
