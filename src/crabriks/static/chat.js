import { el, svgEl } from "./dom.js";
import { appendToolActivity, markRunningToolsError, renderAssistantTurn, renderInlineApproval, renderUserTurn, } from "./transcript.js";
const SESSION_KEY = "crabriks.session";
const MODEL_KEY = "crabriks.model";
export function mount(root, ctx) {
    const transcript = el("section", "log");
    transcript.id = "log";
    transcript.setAttribute("aria-live", "polite");
    const form = document.createElement("form");
    form.id = "composer";
    form.className = "composer";
    const input = document.createElement("textarea");
    input.id = "message";
    input.rows = 1;
    input.placeholder = "Message the agent";
    input.required = true;
    const toolbar = el("div", "composer-toolbar");
    const modelLabel = el("label", "sr", "Model");
    modelLabel.htmlFor = "model";
    const modelPicker = document.createElement("select");
    modelPicker.id = "model";
    modelPicker.className = "model-pill";
    // Context-window meter: a ring showing the input tokens sent to the model.
    const meter = el("div", "ctx-meter");
    meter.id = "ctx-meter";
    meter.dataset.level = "ok";
    const ringCircumference = 2 * Math.PI * 15.5;
    const ringFill = svgEl("circle", {
        class: "ctx-fill",
        cx: "18",
        cy: "18",
        r: "15.5",
        "stroke-dasharray": String(ringCircumference),
        "stroke-dashoffset": String(ringCircumference),
    });
    const ring = svgEl("svg", { class: "ctx-ring", viewBox: "0 0 36 36", "aria-hidden": "true" });
    ring.append(svgEl("circle", { class: "ctx-track", cx: "18", cy: "18", r: "15.5" }), ringFill);
    const meterLabel = el("span", "ctx-label", "0");
    meter.append(ring, meterLabel);
    const abortButton = el("button", "abort", "Stop");
    abortButton.id = "abort";
    abortButton.type = "button";
    abortButton.hidden = true;
    const sendButton = el("button", "send", "Send");
    sendButton.type = "submit";
    toolbar.append(modelLabel, modelPicker, meter, abortButton, sendButton);
    const statusLine = el("p", "status");
    statusLine.id = "status";
    statusLine.setAttribute("role", "status");
    form.append(input, toolbar, statusLine);
    root.append(transcript, form);
    let draft = null;
    let draftText = "";
    let controller = null;
    let contextTokens = 0;
    let contextWindow = null;
    function formatTokens(value) {
        if (value >= 1_000_000)
            return `${(value / 1_000_000).toFixed(1)}m`;
        if (value >= 1_000)
            return `${Math.round(value / 1000)}k`;
        return String(value);
    }
    // Absolute pressure thresholds for the sent-context size.
    function usageLevel(tokens) {
        if (tokens >= 300_000)
            return "danger";
        if (tokens >= 250_000)
            return "orange";
        if (tokens >= 150_000)
            return "warn";
        return "ok";
    }
    function renderMeter() {
        // The ring fills against the model's context window; 300k is a sane gauge
        // when the window is unknown. Colour is absolute, per the product call.
        const denominator = contextWindow ?? 300_000;
        const ratio = denominator > 0 ? Math.min(1, contextTokens / denominator) : 0;
        meter.dataset.level = usageLevel(contextTokens);
        ringFill.setAttribute("stroke-dashoffset", String(ringCircumference * (1 - ratio)));
        meterLabel.textContent = formatTokens(contextTokens);
        const detail = contextWindow
            ? `${contextTokens.toLocaleString()} / ${contextWindow.toLocaleString()} input tokens`
            : `${contextTokens.toLocaleString()} input tokens; context window unknown`;
        meter.title = detail;
        meter.setAttribute("aria-label", `Context: ${detail}`);
    }
    renderMeter();
    function sessionId() {
        const fromUrl = ctx.url.searchParams.get("session");
        if (fromUrl) {
            sessionStorage.setItem(SESSION_KEY, fromUrl);
            return fromUrl;
        }
        const existing = sessionStorage.getItem(SESSION_KEY);
        if (existing)
            return existing;
        const created = crypto.randomUUID();
        sessionStorage.setItem(SESSION_KEY, created);
        return created;
    }
    function showEmpty() {
        transcript.replaceChildren(el("p", "empty", "This session is empty."));
    }
    function renderEntry(entry) {
        if (entry.role === "user") {
            transcript.append(renderUserTurn(entry.content));
            return;
        }
        if (entry.role === "assistant") {
            transcript.append(renderAssistantTurn(entry.content));
            return;
        }
        const name = entry.tool_name ?? "tool";
        if (entry.role === "tool_call") {
            appendToolActivity(transcript, { event: "tool_call", name, arguments: entry.content });
            return;
        }
        appendToolActivity(transcript, { event: "tool_result", name, content: entry.content });
    }
    function renderTranscript(entries) {
        dropDraft();
        transcript.replaceChildren();
        if (entries.length === 0) {
            showEmpty();
            return;
        }
        for (const entry of entries)
            renderEntry(entry);
        transcript.scrollTop = transcript.scrollHeight;
    }
    function showThinking() {
        transcript.querySelector(".empty")?.remove();
        if (draft)
            return draft;
        draft = el("article", "assistant draft thinking");
        draft.dataset.draft = "true";
        draft.setAttribute("aria-busy", "true");
        const label = el("span", "thinking-indicator", "Thinking");
        const dots = el("span", "thinking-dots");
        dots.append(el("span"), el("span"), el("span"));
        label.append(dots);
        draft.append(label);
        transcript.append(draft);
        transcript.scrollTop = transcript.scrollHeight;
        draftText = "";
        return draft;
    }
    function ensureDraft() {
        transcript.querySelector(".empty")?.remove();
        if (draft) {
            if (draft.classList.contains("thinking")) {
                draft.classList.remove("thinking");
                draft.removeAttribute("aria-busy");
                draft.replaceChildren();
            }
            return draft;
        }
        draft = el("article", "assistant draft");
        draft.dataset.draft = "true";
        transcript.append(draft);
        draftText = "";
        return draft;
    }
    function dropDraft() {
        draft?.remove();
        draft = null;
        draftText = "";
    }
    function commitReply(reply) {
        const text = reply || draftText;
        dropDraft();
        transcript.append(renderAssistantTurn(text));
    }
    function grow() {
        input.style.height = "auto";
        input.style.height = `${input.scrollHeight}px`;
    }
    function setBusy(busy) {
        input.disabled = busy;
        sendButton.disabled = busy;
        modelPicker.disabled = busy;
        abortButton.hidden = !busy;
    }
    function setStatus(text) {
        statusLine.textContent = text;
    }
    async function loadModels() {
        const response = await fetch("/api/models");
        if (!response.ok)
            return;
        const body = (await response.json());
        const saved = sessionStorage.getItem(MODEL_KEY);
        modelPicker.replaceChildren();
        for (const option of body.models) {
            const node = document.createElement("option");
            node.value = option.id;
            node.textContent = option.label;
            modelPicker.append(node);
        }
        const wanted = saved && body.models.some((option) => option.id === saved)
            ? saved
            : body.models.find((option) => option.default)?.id;
        if (wanted)
            modelPicker.value = wanted;
    }
    async function loadTranscript() {
        const response = await fetch(`/api/sessions/${sessionId()}/transcript`);
        if (!response.ok) {
            setStatus("The transcript could not be loaded.");
            return;
        }
        const body = (await response.json());
        renderTranscript(body.entries ?? []);
    }
    function parseFrame(raw) {
        let event = "message";
        const data = [];
        for (const line of raw.split("\n")) {
            if (line.startsWith("event:"))
                event = line.slice(6).trim();
            else if (line.startsWith("data:"))
                data.push(line.slice(5).trim());
        }
        if (data.length === 0)
            return null;
        return { event, data: data.join("\n") };
    }
    function onFrame(frame) {
        const payload = JSON.parse(frame.data);
        if (frame.event === "token" && payload.text) {
            draftText += payload.text;
            ensureDraft().textContent = draftText;
            transcript.scrollTop = transcript.scrollHeight;
            return;
        }
        if (frame.event === "tool_call") {
            if (draft?.classList.contains("thinking")) {
                dropDraft();
            }
            appendToolActivity(transcript, {
                event: "tool_call",
                name: payload.name ?? "tool",
                arguments: payload.arguments ?? "",
            });
            transcript.scrollTop = transcript.scrollHeight;
            return;
        }
        if (frame.event === "approval_required") {
            if (draft?.classList.contains("thinking")) {
                dropDraft();
            }
            renderInlineApproval(transcript, payload.approval_id ?? "", payload.name ?? "tool", (reply) => {
                if (reply) {
                    transcript.append(renderAssistantTurn(reply));
                    transcript.scrollTop = transcript.scrollHeight;
                }
                setStatus("");
            }, payload.arguments);
            transcript.scrollTop = transcript.scrollHeight;
            return;
        }
        if (frame.event === "tool_result") {
            appendToolActivity(transcript, {
                event: "tool_result",
                name: payload.name ?? "tool",
                content: payload.content ?? "",
            });
            if (!draft)
                showThinking();
            transcript.scrollTop = transcript.scrollHeight;
            return;
        }
        if (frame.event === "usage") {
            contextTokens = payload.input_tokens ?? 0;
            contextWindow = payload.context_window ?? null;
            renderMeter();
            return;
        }
        if (frame.event === "done") {
            commitReply(payload.reply ?? "");
            if (payload.status === "pending_approval") {
                setStatus("Action paused waiting for approval above.");
            }
            else {
                setStatus("");
            }
            return;
        }
        if (frame.event === "error") {
            const failure = payload.error ?? "The turn failed before a reply was completed.";
            markRunningToolsError(transcript, failure);
            dropDraft();
            setStatus(failure);
        }
    }
    async function readSse(response) {
        const reader = response.body?.getReader();
        if (!reader)
            return false;
        const decoder = new TextDecoder();
        let buffer = "";
        let finished = false;
        for (;;) {
            const chunk = await reader.read();
            if (chunk.done)
                break;
            buffer += decoder.decode(chunk.value, { stream: true });
            const frames = buffer.split("\n\n");
            buffer = frames.pop() ?? "";
            for (const raw of frames) {
                const frame = parseFrame(raw);
                if (!frame)
                    continue;
                onFrame(frame);
                if (frame.event === "done" || frame.event === "error")
                    finished = true;
            }
        }
        return finished;
    }
    async function sendMessage(text) {
        setBusy(true);
        setStatus("");
        controller = new AbortController();
        const signal = controller.signal;
        let finished = false;
        // Immediately render user message and thinking indicator for responsive chat feel
        transcript.querySelector(".empty")?.remove();
        transcript.append(renderUserTurn(text));
        showThinking();
        transcript.scrollTop = transcript.scrollHeight;
        try {
            const agent = ctx.url.searchParams.get("agent") || null;
            const response = await fetch(`/api/sessions/${sessionId()}/turns`, {
                method: "POST",
                headers: { "content-type": "application/json" },
                body: JSON.stringify({
                    message: text,
                    model: modelPicker.value || null,
                    agent,
                }),
                signal,
            });
            if (response.status === 409) {
                dropDraft();
                const body = (await response.json());
                setStatus(body.error ?? "A turn is already running for this session.");
                return;
            }
            if (!response.ok) {
                dropDraft();
                setStatus("The turn could not be started.");
                return;
            }
            finished = await readSse(response);
        }
        catch {
            dropDraft();
            if (!signal.aborted)
                setStatus("The turn could not be started.");
        }
        finally {
            if (!finished && !signal.aborted) {
                dropDraft();
                setStatus("The turn failed before a reply was completed.");
            }
            controller = null;
            setBusy(false);
            input.focus();
        }
    }
    // Autocomplete popover state
    let popover = null;
    let suggestions = [];
    let selectedIndex = -1;
    let debounceTimer = null;
    let suggestionsAbort = null;
    let activeTrigger = null;
    function closePopover() {
        if (debounceTimer)
            clearTimeout(debounceTimer);
        if (suggestionsAbort)
            suggestionsAbort.abort();
        debounceTimer = null;
        suggestionsAbort = null;
        if (popover) {
            popover.remove();
            popover = null;
        }
        suggestions = [];
        selectedIndex = -1;
        activeTrigger = null;
    }
    function renderPopover() {
        if (!popover) {
            popover = el("ul", "composer-popover");
            popover.setAttribute("role", "listbox");
            form.append(popover);
        }
        popover.replaceChildren();
        if (suggestions.length === 0) {
            closePopover();
            return;
        }
        suggestions.forEach((item, idx) => {
            const li = el("li", `composer-popover-item${idx === selectedIndex ? " active" : ""}`);
            li.setAttribute("role", "option");
            li.setAttribute("aria-selected", idx === selectedIndex ? "true" : "false");
            const label = el("span", "popover-item-label", item.label);
            const detail = el("span", "popover-item-detail", item.detail);
            const kind = el("span", "popover-item-kind", item.kind);
            li.append(label, detail, kind);
            li.addEventListener("mousedown", (e) => {
                e.preventDefault();
                applySuggestion(item);
            });
            popover?.append(li);
        });
    }
    function applySuggestion(item) {
        if (!activeTrigger)
            return;
        const value = input.value;
        const before = value.slice(0, activeTrigger.start);
        const after = value.slice(activeTrigger.end);
        input.value = before + item.insert_text + " " + after;
        const newCursor = activeTrigger.start + item.insert_text.length + 1;
        input.setSelectionRange(newCursor, newCursor);
        closePopover();
        input.focus();
        grow();
    }
    let requestSeq = 0;
    async function fetchSuggestions(seq, type, query, start, end) {
        if (suggestionsAbort)
            suggestionsAbort.abort();
        suggestionsAbort = new AbortController();
        try {
            const res = await fetch(`/api/composer/suggestions?type=${encodeURIComponent(type)}&query=${encodeURIComponent(query)}`, { signal: suggestionsAbort.signal });
            if (!res.ok)
                return;
            // Guard against stale response using request sequence and active trigger bounds
            if (seq !== requestSeq ||
                !activeTrigger ||
                activeTrigger.type !== type ||
                activeTrigger.query !== query ||
                activeTrigger.start !== start ||
                activeTrigger.end !== end) {
                return;
            }
            const data = (await res.json());
            // Re-check sequence and trigger after asynchronous JSON parsing
            if (seq !== requestSeq ||
                !activeTrigger ||
                activeTrigger.type !== type ||
                activeTrigger.query !== query ||
                activeTrigger.start !== start ||
                activeTrigger.end !== end) {
                return;
            }
            suggestions = data.suggestions ?? [];
            selectedIndex = suggestions.length > 0 ? 0 : -1;
            renderPopover();
        }
        catch {
            // aborted or network error
        }
    }
    function inspectTrigger() {
        const cursor = input.selectionStart;
        const textBefore = input.value.slice(0, cursor);
        const match = /(?:^|\s)([@\/])([^\s]*)$/.exec(textBefore);
        if (!match) {
            closePopover();
            return;
        }
        const type = match[1];
        const query = match[2];
        const triggerStart = cursor - query.length - 1;
        activeTrigger = { type, query, start: triggerStart, end: cursor };
        // Immediately cancel in-flight request, clear previous suggestions and popover
        requestSeq += 1;
        const currentSeq = requestSeq;
        if (suggestionsAbort) {
            suggestionsAbort.abort();
            suggestionsAbort = null;
        }
        suggestions = [];
        selectedIndex = -1;
        if (popover) {
            popover.remove();
            popover = null;
        }
        if (debounceTimer)
            clearTimeout(debounceTimer);
        debounceTimer = setTimeout(() => {
            void fetchSuggestions(currentSeq, type, query, triggerStart, cursor);
        }, 250);
    }
    abortButton.addEventListener("click", () => {
        controller?.abort();
        controller = null;
        setBusy(false);
    });
    form.addEventListener("submit", (event) => {
        event.preventDefault();
        closePopover();
        const text = input.value.trim();
        if (!text)
            return;
        input.value = "";
        grow();
        void sendMessage(text);
    });
    input.addEventListener("input", () => {
        grow();
        inspectTrigger();
    });
    input.addEventListener("keydown", (event) => {
        if (popover && suggestions.length > 0) {
            if (event.key === "ArrowDown") {
                event.preventDefault();
                selectedIndex = (selectedIndex + 1) % suggestions.length;
                renderPopover();
                return;
            }
            if (event.key === "ArrowUp") {
                event.preventDefault();
                selectedIndex = (selectedIndex - 1 + suggestions.length) % suggestions.length;
                renderPopover();
                return;
            }
            if (event.key === "Enter" || event.key === "Tab") {
                if (selectedIndex >= 0 && selectedIndex < suggestions.length) {
                    event.preventDefault();
                    applySuggestion(suggestions[selectedIndex]);
                    return;
                }
            }
            if (event.key === "Escape") {
                event.preventDefault();
                closePopover();
                return;
            }
        }
        if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            form.requestSubmit();
        }
    });
    modelPicker.addEventListener("change", () => {
        sessionStorage.setItem(MODEL_KEY, modelPicker.value);
        // The new model's window is unknown until its first turn reports usage.
        contextWindow = null;
        renderMeter();
    });
    async function checkHatchDraft() {
        try {
            const [hatchRes, sessionsRes] = await Promise.all([
                fetch("/api/hatch"),
                fetch("/api/sessions"),
            ]);
            if (!hatchRes.ok || !sessionsRes.ok)
                return;
            const hatchData = (await hatchRes.json());
            const sessionsData = (await sessionsRes.json());
            const hasSessions = (sessionsData.sessions?.length ?? 0) > 0;
            if (!hatchData.hatched && !hasSessions && !input.value) {
                input.value = "Wake up, my friend!";
                grow();
            }
        }
        catch {
            // ignore network errors
        }
    }
    void loadModels();
    void loadTranscript();
    void checkHatchDraft();
}
