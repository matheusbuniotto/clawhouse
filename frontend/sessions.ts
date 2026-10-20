import {
  UNTITLED,
  clearSession,
  editTitle,
  el,
  relativeTime,
  renameSession,
} from "./dom.js";

interface Session {
  id: string;
  title: string;
  created_at: string;
}

export function mount(root: HTMLElement): void {
  const toolbar = el("div", "sessions-toolbar");
  const search = el("input", "sessions-search");
  search.id = "sessions-search";
  search.type = "search";
  search.placeholder = "Filter sessions by title or date…";
  search.setAttribute("aria-label", "Filter sessions");
  const count = el("span", "sessions-count", "0 sessions");
  count.id = "sessions-count";
  toolbar.append(search, count);

  const list = el("ul", "sessions");
  list.id = "sessions";
  root.append(toolbar, list);

  function updateFilter(): void {
    const query = search.value.trim().toLowerCase();
    const rows = [...list.querySelectorAll<HTMLElement>(".session")];
    let visible = 0;
    for (const row of rows) {
      const hay = (row.dataset.filter ?? "").toLowerCase();
      const match = query === "" || hay.includes(query);
      row.hidden = !match;
      if (match) visible += 1;
    }
    count.textContent =
      visible === 1 ? "1 session" : `${visible} sessions`;
  }

  const searchError = el("p", "sessions-error", "Search failed");
  searchError.hidden = true;
  toolbar.append(searchError);

  let searchTimer: ReturnType<typeof setTimeout> | null = null;
  let searchAbort: AbortController | null = null;

  search.addEventListener("input", () => {
    const query = search.value.trim();
    if (searchTimer) clearTimeout(searchTimer);
    if (searchAbort) {
      searchAbort.abort();
      searchAbort = null;
    }
    if (query.length < 2) {
      searchError.hidden = true;
      updateFilter();
      return;
    }
    searchTimer = setTimeout(() => {
      void searchSessions(query);
    }, 40);
  });

  async function searchSessions(query: string): Promise<void> {
    searchAbort = new AbortController();
    try {
      const response = await fetch(
        `/api/search?q=${encodeURIComponent(query)}`,
        { signal: searchAbort.signal },
      );
      if (!response.ok) throw new Error(String(response.status));
      const body = (await response.json()) as {
        results: { session_id: string; role: string; excerpt: string; created_at: string }[];
      };
      searchError.hidden = true;
      list.replaceChildren();
      if (body.results.length === 0) {
        list.append(el("li", "empty", "No matching transcript entries."));
        return;
      }
      for (const hit of body.results) {
        const row = el("li", "session");
        const link = el("a", "session-link", hit.excerpt);
        link.href = `/chat?session=${hit.session_id}`;
        row.append(link);
        list.append(row);
      }
    } catch (err: unknown) {
      if (err instanceof DOMException && err.name === "AbortError") {
        return;
      }
      searchError.hidden = false;
    }
  }

  function render(items: Session[]): void {
    list.replaceChildren();
    if (items.length === 0) {
      count.textContent = "0 sessions";
      list.append(el("li", "empty", "No sessions yet. Start one."));
      return;
    }
    for (const item of items) {
      let currentTitle = item.title;
      const whenText = relativeTime(item.created_at);
      const row = el("li", "session");
      row.dataset.id = item.id;
      row.dataset.filter = `${currentTitle || UNTITLED} ${whenText} ${item.created_at}`;

      const link = el("a", "session-link", currentTitle || UNTITLED);
      link.setAttribute("data-nav", "");
      link.href = `/chat?session=${item.id}`;

      const meta = el("div", "session-meta");
      const when = el("span", "when", whenText);

      const renameBtn = el("button", "btn-rename-session", "Rename");
      renameBtn.type = "button";
      renameBtn.setAttribute(
        "aria-label",
        `Rename session ${currentTitle || item.id}`,
      );
      renameBtn.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        if (link.hidden) return;
        editTitle(link, currentTitle, async (newTitle) => {
          const saved = await renameSession(item.id, newTitle);
          if (saved !== null) {
            currentTitle = saved;
            row.dataset.filter = `${currentTitle || UNTITLED} ${whenText} ${item.created_at}`;
          }
          return saved;
        });
      });

      const clearBtn = el("button", "btn-clear-session", "Clear");
      clearBtn.type = "button";
      clearBtn.setAttribute(
        "aria-label",
        `Clear session ${currentTitle || item.id}`,
      );
      clearBtn.addEventListener("click", async (e) => {
        e.preventDefault();
        e.stopPropagation();
        if (!confirm(`Clear transcript for "${currentTitle || UNTITLED}"?`))
          return;
        if (await clearSession(item.id)) {
          row.dataset.cleared = "true";
          clearBtn.textContent = "Cleared";
        }
      });

      const delBtn = el("button", "btn-delete-session", "Delete");
      delBtn.type = "button";
      delBtn.setAttribute(
        "aria-label",
        `Delete session ${currentTitle || item.id}`,
      );
      delBtn.addEventListener("click", async (e) => {
        e.preventDefault();
        e.stopPropagation();
        if (!confirm(`Delete "${currentTitle || UNTITLED}"?`)) return;
        try {
          const res = await fetch(`/api/sessions/${item.id}`, {
            method: "DELETE",
          });
          if (res.ok || res.status === 204) {
            row.remove();
            updateFilter();
            if (list.children.length === 0) {
              list.append(el("li", "empty", "No sessions yet. Start one."));
            }
            window.dispatchEvent(
              new CustomEvent("clawhouse:session-deleted", {
                detail: { id: item.id },
              }),
            );
          }
        } catch {
          // ignore network failure
        }
      });

      meta.append(when, renameBtn, clearBtn, delBtn);
      row.append(link, meta);
      list.append(row);
    }
    updateFilter();
  }

  async function load(): Promise<void> {
    const response = await fetch("/api/sessions");
    if (!response.ok) {
      list.append(el("li", "empty", "The sessions could not be loaded."));
      return;
    }
    const body = (await response.json()) as { sessions: Session[] };
    render(body.sessions);
  }

  void load();
}
