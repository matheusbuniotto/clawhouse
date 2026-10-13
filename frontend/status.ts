import { el, relativeTime, type ActivityState } from "./dom.js";

interface AuthSnapshot {
  user_id: string;
  token_present: boolean;
  auth_type: string;
}

interface ConnectionSnapshot {
  workspace_host: string | null;
  serving_endpoint: string | null;
  store_type: string;
}

interface StatusSession {
  id: string;
  title: string;
  created_at: string;
  run_state: ActivityState;
}

interface ScheduleItem {
  id: string;
  session_id: string;
  cron_expression: string;
  prompt: string;
  status: string;
  next_run_at: string;
  created_at: string;
  last_run_at?: string | null;
}

interface StatusBody {
  auth: AuthSnapshot;
  connection: ConnectionSnapshot;
  sessions: StatusSession[];
  log_tail_url: string;
}

const FIELDS: ReadonlyArray<readonly [string, string]> = [
  ["User", "stat-user"],
  ["Auth mode", "stat-auth"],
  ["Token", "stat-token"],
  ["Workspace", "stat-workspace"],
  ["Model endpoint", "stat-model"],
  ["Storage", "stat-store"],
];

export function mount(root: HTMLElement): void {
  const connection = el("section", "status-section");
  connection.append(el("h2", "", "Connection & Identity"));
  const card = el("div", "status-card");
  const grid = el("dl", "status-grid");
  const values = new Map<string, HTMLElement>();
  for (const [label, id] of FIELDS) {
    grid.append(el("dt", "", label));
    const value = el("dd", "", "Loading…");
    value.id = id;
    values.set(id, value);
    grid.append(value);
  }
  card.append(grid);
  connection.append(card);

  const runs = el("section", "status-section");
  runs.append(el("h2", "", "Session Runs"));
  const sessionsList = el("ul", "sessions-list");
  sessionsList.id = "sessions-list";
  runs.append(sessionsList);

  const schedules = el("section", "status-section");
  schedules.append(el("h2", "", "Scheduled Automations"));
  const schedulesList = el("ul", "schedules-list");
  schedulesList.id = "schedules-list";
  schedules.append(schedulesList);

  const diagnostics = el("section", "status-section");
  diagnostics.append(el("h2", "", "Diagnostics & Logs"));
  const logCard = el("div", "status-card");
  const logRow = el("p", "log-tail-row");
  const logTailLink = el("a", "btn-link", "Log tail");
  logTailLink.id = "log-tail-link";
  logTailLink.href = "#";
  logTailLink.target = "_blank";
  logTailLink.rel = "noopener";
  logRow.append(logTailLink);
  logCard.append(logRow);
  diagnostics.append(logCard);

  const statusLine = el("p", "status");
  statusLine.id = "status";
  statusLine.setAttribute("role", "status");

  root.append(connection, runs, schedules, diagnostics, statusLine);

  function set(id: string, text: string): void {
    const node = values.get(id);
    if (node) node.textContent = text;
  }

  function renderAuthAndConnection(auth: AuthSnapshot, conn: ConnectionSnapshot): void {
    set("stat-user", auth.user_id || "Anonymous");
    set("stat-auth", auth.auth_type.toUpperCase());
    set(
      "stat-token",
      auth.token_present
        ? auth.auth_type === "dev"
          ? "Present (dev)"
          : "Present (forwarded)"
        : "Not present",
    );
    set("stat-workspace", conn.workspace_host || "Local environment");
    set("stat-model", conn.serving_endpoint || "Default endpoint");
    set("stat-store", conn.store_type === "memory" ? "In-Memory Store" : "Lakebase Postgres");
  }

  function renderSessions(items: StatusSession[]): void {
    sessionsList.replaceChildren();
    if (items.length === 0) {
      sessionsList.append(el("li", "empty", "No sessions yet."));
      return;
    }
    for (const item of items) {
      const row = el("li", "session-status-row");
      const link = el("a", "session-link", item.title || "Untitled session");
      link.setAttribute("data-nav", "");
      link.href = `/chat?session=${item.id}`;
      row.append(link);
      row.append(el("span", `status-badge ${item.run_state}`, item.run_state));
      row.append(el("span", "when", relativeTime(item.created_at)));
      sessionsList.append(row);
    }
  }

  function renderSchedules(items: ScheduleItem[]): void {
    schedulesList.replaceChildren();
    if (items.length === 0) {
      schedulesList.append(el("li", "empty", "No scheduled automations."));
      return;
    }
    for (const item of items) {
      const row = el("li", "schedule-status-row");
      const info = el("div", "schedule-info");
      const cronBadge = el("code", "schedule-cron", item.cron_expression);
      const promptSpan = el("span", "schedule-prompt", item.prompt);
      info.append(cronBadge, promptSpan);

      const meta = el("div", "schedule-meta");
      const statusBadge = el("span", `schedule-badge ${item.status}`, item.status);
      const nextRun = el("span", "when", `Next: ${relativeTime(item.next_run_at)}`);
      meta.append(statusBadge, nextRun);

      if (item.status === "active") {
        const cancelBtn = el("button", "btn-cancel-schedule", "Cancel");
        cancelBtn.type = "button";
        cancelBtn.addEventListener("click", async () => {
          cancelBtn.disabled = true;
          try {
            const res = await fetch(`/api/schedules/${item.id}`, { method: "DELETE" });
            if (res.ok) {
              void loadSchedules();
            }
          } catch {
            cancelBtn.disabled = false;
          }
        });
        meta.append(cancelBtn);
      }

      row.append(info, meta);
      schedulesList.append(row);
    }
  }

  async function loadSchedules(): Promise<void> {
    try {
      const resp = await fetch("/api/schedules");
      if (resp.ok) {
        const items = (await resp.json()) as ScheduleItem[];
        renderSchedules(items);
      }
    } catch {
      // Non-blocking
    }
  }

  async function load(): Promise<void> {
    try {
      const resp = await fetch("/api/status");
      if (!resp.ok) {
        statusLine.textContent = "The status could not be loaded.";
        return;
      }
      const data = (await resp.json()) as StatusBody;
      renderAuthAndConnection(data.auth, data.connection);
      renderSessions(data.sessions);
      if (data.log_tail_url) logTailLink.href = data.log_tail_url;
      void loadSchedules();
    } catch {
      statusLine.textContent = "Network error while loading status.";
    }
  }

  void load();
}
