interface ApprovalItem {
  id: string;
  session_id: string;
  tool_name: string;
  arguments: string;
  status: string;
  created_at: string;
  resolved_by: string | null;
}

interface ApprovalsBody {
  approvals?: ApprovalItem[];
  pending?: ApprovalItem[];
  history?: ApprovalItem[];
}

const pendingListNode = document.querySelector<HTMLUListElement>("#pending-list");
const historyListNode = document.querySelector<HTMLUListElement>("#history-list");
const statusNode = document.querySelector<HTMLElement>("#status");

if (!pendingListNode || !historyListNode || !statusNode) {
  throw new Error("approvals page is missing a required element");
}

const pendingList = pendingListNode;
const historyList = historyListNode;
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

function renderPending(items: ApprovalItem[]): void {
  pendingList.replaceChildren();
  if (items.length === 0) {
    pendingList.append(el("li", "empty", "No pending approvals."));
    return;
  }
  for (const item of items) {
    const card = el("li", "approval-card");

    const header = el("div", "approval-header");
    header.append(el("strong", "tool-name", item.tool_name));
    header.append(el("span", "when", new Date(item.created_at).toLocaleString()));
    card.append(header);

    const sessionLink = el("a", "session-link");
    sessionLink.href = `/chat?session=${item.session_id}`;
    sessionLink.textContent = `Session: ${item.session_id}`;
    card.append(sessionLink);

    const argsPre = el("pre", "args-json", item.arguments);
    card.append(argsPre);

    const actions = el("div", "approval-actions");
    const approveBtn = el("button", "btn-approve", "Approve");
    const denyBtn = el("button", "btn-deny", "Deny");

    approveBtn.addEventListener("click", async () => {
      approveBtn.disabled = true;
      denyBtn.disabled = true;
      statusLine.textContent = `Approving ${item.tool_name}…`;
      const res = await fetch(`/api/approvals/${item.id}/approve`, { method: "POST" });
      if (res.ok) {
        statusLine.textContent = `Approved ${item.tool_name}.`;
        await load();
      } else {
        statusLine.textContent = "Failed to approve tool call.";
        approveBtn.disabled = false;
        denyBtn.disabled = false;
      }
    });

    denyBtn.addEventListener("click", async () => {
      approveBtn.disabled = true;
      denyBtn.disabled = true;
      statusLine.textContent = `Denying ${item.tool_name}…`;
      const res = await fetch(`/api/approvals/${item.id}/deny`, { method: "POST" });
      if (res.ok) {
        statusLine.textContent = `Denied ${item.tool_name}.`;
        await load();
      } else {
        statusLine.textContent = "Failed to deny tool call.";
        approveBtn.disabled = false;
        denyBtn.disabled = false;
      }
    });

    actions.append(approveBtn, denyBtn);
    card.append(actions);
    pendingList.append(card);
  }
}

function renderHistory(items: ApprovalItem[]): void {
  historyList.replaceChildren();
  if (items.length === 0) {
    historyList.append(el("li", "empty", "No approval history."));
    return;
  }
  for (const item of items) {
    const card = el("li", "approval-history-row");
    const title = el("strong", "tool-name", item.tool_name);
    const badge = el("span", `status-badge ${item.status}`, item.status);
    const when = el("span", "when", new Date(item.created_at).toLocaleString());
    const resolver = item.resolved_by ? el("span", "resolver", `by ${item.resolved_by}`) : null;

    card.append(title, badge, when);
    if (resolver) card.append(resolver);
    historyList.append(card);
  }
}

async function load(): Promise<void> {
  const resp = await fetch("/api/approvals");
  if (!resp.ok) {
    statusLine.textContent = "The approvals could not be loaded.";
    return;
  }
  const body = (await resp.json()) as ApprovalsBody;
  renderPending(body.pending ?? []);
  renderHistory(body.history ?? []);
}

void load();
export {};
