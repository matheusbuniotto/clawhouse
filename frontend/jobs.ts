/** Lakeflow job tool results: run cards with a state badge, and job lists. */

import { el, rawJsonDisclosure } from "./dom.js";

export type JobBadgeState = "pending" | "running" | "success" | "failed";

interface JobRun {
  jobId?: number;
  runId: number;
  lifeCycle?: string;
  result?: string;
  durationMs?: number;
  url?: string;
}

interface JobRow {
  jobId?: number;
  name: string;
}

export type JobView = { kind: "run"; run: JobRun } | { kind: "list"; jobs: JobRow[] };

const IN_FLIGHT: Record<string, JobBadgeState> = {
  PENDING: "pending",
  QUEUED: "pending",
  BLOCKED: "pending",
  WAITING_FOR_RETRY: "pending",
  RUNNING: "running",
  TERMINATING: "running",
};

const SAFE_URL = /^https?:\/\//i;

function asNumber(value: unknown): number | undefined {
  return typeof value === "number" ? value : undefined;
}

function asString(value: unknown): string | undefined {
  return typeof value === "string" && value !== "" ? value : undefined;
}

export function tryParseJobView(text: string): JobView | null {
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch {
    return null;
  }
  if (typeof data !== "object" || data === null) return null;
  const obj = data as Record<string, unknown>;
  if (Array.isArray(obj.jobs)) {
    const jobs = (obj.jobs as Record<string, unknown>[]).map((job) => ({
      jobId: asNumber(job.job_id),
      name: asString(job.name) ?? "(unnamed job)",
    }));
    return { kind: "list", jobs };
  }
  const runId = asNumber(obj.run_id);
  if (runId === undefined) return null;
  return {
    kind: "run",
    run: {
      runId,
      jobId: asNumber(obj.job_id),
      lifeCycle: asString(obj.life_cycle_state),
      result: asString(obj.result_state),
      durationMs: asNumber(obj.duration_ms),
      url: asString(obj.url),
    },
  };
}

export function badgeState(lifeCycle: string | undefined, result: string | undefined): JobBadgeState {
  if (lifeCycle && lifeCycle in IN_FLIGHT) return IN_FLIGHT[lifeCycle];
  return result === "SUCCESS" ? "success" : "failed";
}

function formatDuration(ms: number): string {
  const seconds = ms / 1000;
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
}

function chip(text: string): HTMLElement {
  return el("span", "job-chip", text);
}

function renderRun(run: JobRun): HTMLElement {
  const card = el("div", "job-card");
  if (run.lifeCycle || run.result) {
    const badge = el("span", "job-badge", run.result ?? run.lifeCycle);
    badge.dataset.state = badgeState(run.lifeCycle, run.result);
    card.append(badge);
  }
  if (run.jobId !== undefined) card.append(chip(`Job ${run.jobId}`));
  card.append(chip(`Run ${run.runId}`));
  if (run.durationMs !== undefined) card.append(chip(formatDuration(run.durationMs)));
  if (run.url && SAFE_URL.test(run.url)) {
    const link = el("a", "job-link", "Open run");
    link.href = run.url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    card.append(link);
  }
  return card;
}

function renderList(jobs: JobRow[]): HTMLElement {
  const list = el("div", "job-list");
  for (const job of jobs) {
    const row = el("div", "job-card");
    row.append(el("span", "job-name", job.name));
    if (job.jobId !== undefined) row.append(chip(`Job ${job.jobId}`));
    list.append(row);
  }
  return list;
}

export function renderJobView(view: JobView, rawJson: string): HTMLElement {
  const wrap = el("div", "job-result");
  wrap.append(view.kind === "run" ? renderRun(view.run) : renderList(view.jobs));
  wrap.append(rawJsonDisclosure(rawJson));
  return wrap;
}
