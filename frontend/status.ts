import { el, relativeTime } from "./dom.js";

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
  run_state: string;
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

  root.append(connection, runs, diagnostics, statusLine);

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
    } catch {
      statusLine.textContent = "Network error while loading status.";
    }
  }

  void load();
}
