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

const statUserNode = document.querySelector<HTMLElement>("#stat-user");
const statAuthNode = document.querySelector<HTMLElement>("#stat-auth");
const statTokenNode = document.querySelector<HTMLElement>("#stat-token");
const statWorkspaceNode = document.querySelector<HTMLElement>("#stat-workspace");
const statModelNode = document.querySelector<HTMLElement>("#stat-model");
const statStoreNode = document.querySelector<HTMLElement>("#stat-store");
const sessionsListNode = document.querySelector<HTMLUListElement>("#sessions-list");
const logTailLinkNode = document.querySelector<HTMLAnchorElement>("#log-tail-link");
const statusNode = document.querySelector<HTMLElement>("#status");

if (
  !statUserNode ||
  !statAuthNode ||
  !statTokenNode ||
  !statWorkspaceNode ||
  !statModelNode ||
  !statStoreNode ||
  !sessionsListNode ||
  !logTailLinkNode ||
  !statusNode
) {
  throw new Error("status page is missing a required element");
}

const statUser = statUserNode;
const statAuth = statAuthNode;
const statToken = statTokenNode;
const statWorkspace = statWorkspaceNode;
const statModel = statModelNode;
const statStore = statStoreNode;
const sessionsList = sessionsListNode;
const logTailLink = logTailLinkNode;
const statusLine = statusNode;

function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  className: string,
  text?: string,
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function renderAuthAndConnection(auth: AuthSnapshot, connection: ConnectionSnapshot): void {
  statUser.textContent = auth.user_id || "Anonymous";
  statAuth.textContent = auth.auth_type.toUpperCase();
  statToken.textContent = auth.token_present
    ? auth.auth_type === "dev"
      ? "Present (dev)"
      : "Present (forwarded)"
    : "Not present";
  statWorkspace.textContent = connection.workspace_host || "Local environment";
  statModel.textContent = connection.serving_endpoint || "Default endpoint";
  statStore.textContent =
    connection.store_type === "memory" ? "In-Memory Store" : "Lakebase Postgres";
}

function renderSessions(items: StatusSession[]): void {
  sessionsList.replaceChildren();
  if (items.length === 0) {
    sessionsList.append(el("li", "empty", "No sessions yet."));
    return;
  }
  for (const item of items) {
    const row = el("li", "session-status-row");

    const link = document.createElement("a");
    link.className = "session-link";
    link.href = `/chat?session=${item.id}`;
    link.textContent = item.title || "Untitled session";

    const badge = el("span", `status-badge ${item.run_state}`, item.run_state);
    const when = el("span", "when", new Date(item.created_at).toLocaleString());

    row.append(link, badge, when);
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
    if (data.log_tail_url) {
      logTailLink.href = data.log_tail_url;
    }
  } catch {
    statusLine.textContent = "Network error while loading status.";
  }
}

void load();
export {};
