import { el } from "./dom.js";
import { appendToolActivity, markRunningToolsError, renderAssistantTurn, renderUserTurn, } from "./transcript.js";
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
    const abortButton = el("button", "abort", "Stop");
    abortButton.id = "abort";
    abortButton.type = "button";
    abortButton.hidden = true;
    const sendButton = el("button", "send", "Send");
    sendButton.type = "submit";
    toolbar.append(modelLabel, modelPicker, abortButton, sendButton);
    const statusLine = el("p", "status");
    statusLine.id = "status";
    statusLine.setAttribute("role", "status");
    form.append(input, toolbar, statusLine);
    root.append(transcript, form);
    let draft = null;
    let draftText = "";
    let controller = null;
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
    function ensureDraft() {
        transcript.querySelector(".empty")?.remove();
        if (draft)
            return draft;
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
            return;
        }
        if (frame.event === "tool_call") {
            appendToolActivity(transcript, {
                event: "tool_call",
                name: payload.name ?? "tool",
                arguments: payload.arguments ?? "",
            });
            return;
        }
        if (frame.event === "tool_result") {
            appendToolActivity(transcript, {
                event: "tool_result",
                name: payload.name ?? "tool",
                content: payload.content ?? "",
            });
            return;
        }
        if (frame.event === "done") {
            commitReply(payload.reply ?? "");
            setStatus("");
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
        try {
            const response = await fetch(`/api/sessions/${sessionId()}/turns`, {
                method: "POST",
                headers: { "content-type": "application/json" },
                body: JSON.stringify({ message: text, model: modelPicker.value || null }),
                signal,
            });
            if (response.status === 409) {
                const body = (await response.json());
                setStatus(body.error ?? "A turn is already running for this session.");
                return;
            }
            if (!response.ok) {
                setStatus("The turn could not be started.");
                return;
            }
            transcript.querySelector(".empty")?.remove();
            transcript.append(renderUserTurn(text));
            finished = await readSse(response);
        }
        catch {
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
    abortButton.addEventListener("click", () => {
        controller?.abort();
        controller = null;
        setBusy(false);
    });
    form.addEventListener("submit", (event) => {
        event.preventDefault();
        const text = input.value.trim();
        if (!text)
            return;
        input.value = "";
        grow();
        void sendMessage(text);
    });
    input.addEventListener("input", grow);
    input.addEventListener("keydown", (event) => {
        if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            form.requestSubmit();
        }
    });
    modelPicker.addEventListener("change", () => {
        sessionStorage.setItem(MODEL_KEY, modelPicker.value);
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
