interface Session {
  id: string;
  title: string;
  created_at: string;
}

const list = document.querySelector<HTMLUListElement>("#sessions");
const statusNode = document.querySelector<HTMLElement>("#status");

if (!list || !statusNode) {
  throw new Error("sessions page is missing a required element");
}

const sessions = list;
const statusLine = statusNode;

function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  className: string,
  text?: string,
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function render(items: Session[]): void {
  sessions.replaceChildren();
  if (items.length === 0) {
    sessions.append(el("li", "empty", "No sessions yet. Start one."));
    return;
  }
  for (const item of items) {
    const row = el("li", "session");
    const link = document.createElement("a");
    link.className = "session-link";
    link.href = `/chat?session=${item.id}`;
    link.textContent = item.title || "Untitled session";
    row.append(link);
    row.append(el("span", "when", new Date(item.created_at).toLocaleString()));
    sessions.append(row);
  }
}

async function load(): Promise<void> {
  const response = await fetch("/api/sessions");
  if (!response.ok) {
    statusLine.textContent = "The sessions could not be loaded.";
    return;
  }
  const body = (await response.json()) as { sessions: Session[] };
  render(body.sessions);
}

void load();
