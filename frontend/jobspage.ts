/** Jobs screen (#97): app schedules and the Databricks jobs the user may see. */

import { el, relativeTime } from "./dom.js";

export interface JobLastRun {
  status: string;
  started_at: string;
  session_id?: string | null;
  run_url?: string | null;
}

export interface JobRow {
  id: string;
  source: "schedule" | "databricks";
  name: string;
  agent_id: string | null;
  cron: string | null;
  cron_human: string | null;
  next_run_at: string | null;
  last_run: JobLastRun | null;
  can_run: boolean;
  can_delete: boolean;
  session_id?: string | null;
}

export interface JobsBody {
  jobs: JobRow[];
  databricks_visibility?: "user" | "acl" | null;
  databricks_error?: string | null;
}

const SAFE_URL = /^https?:\/\//i;
const SOURCE_LABEL: Record<JobRow["source"], string> = {
  schedule: "Agendamento",
  databricks: "Databricks",
};

function lastRunCell(run: JobLastRun | null): HTMLElement {
  const cell = el("span", "job-last");
  if (!run) {
    cell.textContent = "Nunca rodou";
    return cell;
  }
  const badge = el("span", "job-run-status", run.status);
  badge.dataset.status = run.status.toLowerCase();
  cell.append(badge, el("span", "when", relativeTime(run.started_at)));
  if (run.session_id) {
    const link = el("a", "job-open", "Abrir sessão");
    link.href = `/chat?session=${encodeURIComponent(run.session_id)}`;
    link.setAttribute("data-nav", "");
    cell.append(link);
  } else if (run.run_url && SAFE_URL.test(run.run_url)) {
    const link = el("a", "job-open", "Abrir execução");
    link.href = run.run_url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    cell.append(link);
  }
  return cell;
}

export interface JobActions {
  run(job: JobRow): Promise<void>;
  remove(job: JobRow): Promise<void>;
}

function actionButton(
  label: string,
  act: () => Promise<void>,
): HTMLButtonElement {
  const button = el("button", "job-action", label);
  button.type = "button";
  button.onclick = async () => {
    button.disabled = true;
    try {
      await act();
    } finally {
      button.disabled = false;
    }
  };
  return button;
}

export function renderJobRow(job: JobRow, actions: JobActions): HTMLElement {
  const row = el("li", "job-row");
  row.dataset.id = job.id;
  row.dataset.source = job.source;
  const head = el("div", "job-head");
  head.append(
    el("span", "job-source", SOURCE_LABEL[job.source]),
    el("span", "job-title", job.name),
  );
  if (job.agent_id) head.append(el("span", "job-agent", `@${job.agent_id}`));
  const meta = el("div", "job-meta");
  meta.append(el("span", "job-when", job.cron_human ?? "Sem agenda"));
  if (job.cron) meta.lastElementChild?.setAttribute("title", job.cron);
  meta.append(
    el(
      "span",
      "job-next",
      job.next_run_at
        ? `Próxima: ${relativeTime(job.next_run_at)}`
        : "Sem próxima execução",
    ),
    lastRunCell(job.last_run),
  );
  const buttons = el("div", "job-actions");
  if (job.can_run)
    buttons.append(actionButton("Rodar agora", () => actions.run(job)));
  if (job.can_delete)
    buttons.append(actionButton("Apagar", () => actions.remove(job)));
  row.append(head, meta, buttons);
  return row;
}

export function visibilityNote(body: JobsBody): string | null {
  if (body.databricks_error)
    return "Não foi possível listar os jobs do Databricks.";
  if (body.databricks_visibility === "acl") {
    return "Jobs do Databricks filtrados pelas permissões de cada job para você e seus grupos.";
  }
  return null;
}

export function mount(root: HTMLElement): void {
  const section = el("section", "status-section jobs-screen");
  section.append(el("h2", "", "Jobs"));
  const note = el("p", "jobs-note");
  const list = el("ul", "jobs-list");
  const status = el("p", "status");
  status.setAttribute("role", "status");
  section.append(note, list, status);
  root.append(section);

  const actions: JobActions = {
    async run(job) {
      const response = await fetch(
        `/api/jobs/${encodeURIComponent(job.id)}/run`,
        { method: "POST" },
      );
      status.textContent = response.ok
        ? `"${job.name}" foi iniciado.`
        : "Não foi possível iniciar o job.";
      if (response.ok) void load();
    },
    async remove(job) {
      if (!confirm(`Apagar o agendamento "${job.name}"?`)) return;
      const response = await fetch(`/api/jobs/${encodeURIComponent(job.id)}`, {
        method: "DELETE",
      });
      status.textContent = response.ok
        ? "Agendamento apagado."
        : "Não foi possível apagar.";
      if (response.ok) void load();
    },
  };

  async function load(): Promise<void> {
    try {
      const response = await fetch("/api/jobs");
      if (!response.ok) {
        status.textContent = "Não foi possível carregar os jobs.";
        return;
      }
      const body = (await response.json()) as JobsBody;
      note.textContent = visibilityNote(body) ?? "";
      list.replaceChildren(
        ...body.jobs.map((job) => renderJobRow(job, actions)),
      );
      if (body.jobs.length === 0)
        list.append(el("li", "empty", "Nenhum job ainda."));
    } catch {
      status.textContent = "Erro de rede ao carregar os jobs.";
    }
  }

  void load();
}
