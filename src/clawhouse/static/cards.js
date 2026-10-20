/** Interaction cards in the transcript: questions with buttons (`ask_user`). */
import { el } from "./dom.js";
/** Tool name the transcript stores questions under. */
export const ASK_USER = "ask_user";
function optionButton(label, isDefault) {
    const button = el("button", "question-option", label);
    button.type = "button";
    button.dataset.option = label;
    if (isDefault) {
        button.classList.add("default");
        button.title = "Opção padrão";
        button.append(el("span", "question-default-tag", "padrão"));
    }
    return button;
}
function markChosen(card, chosen) {
    card.dataset.state = "answered";
    for (const button of card.querySelectorAll(".question-option")) {
        button.disabled = true;
        const picked = chosen.includes(button.dataset.option ?? "");
        button.classList.toggle("chosen", picked);
        button.setAttribute("aria-pressed", picked ? "true" : "false");
    }
}
function shell(question) {
    const card = el("div", "question-card");
    card.dataset.questionId = question.id;
    card.setAttribute("role", "group");
    card.setAttribute("aria-label", question.question);
    const options = el("div", "question-options");
    card.append(el("p", "question-text", question.question), options);
    return { card, options };
}
/**
 * A live card: one click answers a single-choice question; a multi-choice one
 * toggles options and sends on "Enviar". The answer goes back as the tool
 * result, never as a user message.
 */
export function renderQuestionCard(question, onAnswered, onStream) {
    const { card, options } = shell(question);
    card.dataset.state = "pending";
    const note = el("p", "question-note");
    const picked = new Set();
    const buttons = question.options.map((label) => optionButton(label, label === question.default));
    options.append(...buttons);
    async function send(selected) {
        for (const button of buttons)
            button.disabled = true;
        markChosen(card, selected);
        note.textContent = "Enviando…";
        try {
            const headers = { "content-type": "application/json" };
            if (onStream) {
                headers["Accept"] = "text/event-stream";
            }
            const response = await fetch(`/api/questions/${encodeURIComponent(question.id)}/answer`, {
                method: "POST",
                headers,
                body: JSON.stringify({ selected }),
            });
            if (!response.ok) {
                note.textContent = "Não foi possível enviar a resposta.";
                for (const button of buttons)
                    button.disabled = false;
                return;
            }
            note.textContent = "";
            const contentType = (typeof response.headers?.get === "function"
                ? response.headers.get("content-type")
                : "") ?? "";
            if (contentType.includes("text/event-stream") && onStream) {
                await onStream(response);
            }
            else {
                const data = (await response.json());
                onAnswered({
                    status: data.status ?? "ok",
                    reply: data.reply ?? "",
                    pending: data.pending ?? [],
                });
            }
        }
        catch {
            note.textContent = "Erro de rede ao enviar a resposta.";
            for (const button of buttons)
                button.disabled = false;
        }
    }
    if (question.multi) {
        const submit = el("button", "question-submit", "Enviar");
        submit.type = "button";
        submit.disabled = true;
        for (const button of buttons) {
            button.onclick = () => {
                const label = button.dataset.option ?? "";
                if (picked.has(label))
                    picked.delete(label);
                else
                    picked.add(label);
                button.setAttribute("aria-pressed", picked.has(label) ? "true" : "false");
                submit.disabled = picked.size === 0;
            };
        }
        submit.onclick = () => {
            submit.remove();
            void send([...picked]);
        };
        card.append(submit);
    }
    else {
        for (const button of buttons)
            button.onclick = () => void send([button.dataset.option ?? ""]);
    }
    card.append(note);
    return card;
}
/** The labels a stored `ask_user` result picked: a click, or a job's default. */
export function chosenFromResult(result, options) {
    const clicked = /^The user chose: (.*)$/s.exec(result);
    if (clicked)
        return clicked[1].split(", ").filter((label) => options.includes(label));
    const fallback = /picked the default option "(.*)"/.exec(result);
    return fallback ? [fallback[1]] : [];
}
/** A question as it reads after reload: buttons disabled, the chosen one marked. */
export function renderAnsweredQuestion(argumentsJson, result) {
    let args;
    try {
        args = JSON.parse(argumentsJson);
    }
    catch {
        return null;
    }
    const options = Array.isArray(args.options) ? args.options.map(String) : [];
    if (!args.question || options.length === 0)
        return null;
    const question = {
        id: "",
        question: args.question,
        options,
        default: args.default ?? null,
        multi: Boolean(args.multi),
    };
    const { card, options: row } = shell(question);
    row.append(...options.map((label) => optionButton(label, label === question.default)));
    markChosen(card, chosenFromResult(result, options));
    if (/picked the default option/.test(result)) {
        card.append(el("p", "question-note", "Sem usuário (job): seguiu a opção padrão."));
    }
    return card;
}
/** Tool name the transcript stores progress cards under. */
export const REPORT_PROGRESS = "report_progress";
const STEP_STATUSES = [
    "pending",
    "running",
    "done",
    "failed",
];
const STEP_MARK = {
    pending: "○",
    running: "◐",
    done: "✓",
    failed: "✗",
};
const STEP_LABEL = {
    pending: "pendente",
    running: "em andamento",
    done: "concluído",
    failed: "falhou",
};
/** A stored `report_progress` call's state, or null when it is not usable. */
export function parseProgress(argumentsJson) {
    let args;
    try {
        args = JSON.parse(argumentsJson);
    }
    catch {
        return null;
    }
    if (typeof args.task_id !== "string" || !Array.isArray(args.steps))
        return null;
    const steps = [];
    for (const raw of args.steps) {
        const status = (raw.status ?? "pending");
        if (typeof raw.label !== "string" || !STEP_STATUSES.includes(status))
            return null;
        steps.push({ label: raw.label, status });
    }
    return { task_id: args.task_id, steps };
}
function fillProgress(card, state) {
    const done = state.steps.filter((step) => step.status === "done").length;
    const list = el("ol", "progress-steps");
    for (const step of state.steps) {
        const item = el("li", "progress-step");
        item.dataset.status = step.status;
        const mark = el("span", "progress-mark", STEP_MARK[step.status]);
        mark.setAttribute("aria-label", STEP_LABEL[step.status]);
        item.append(mark, el("span", "progress-label", step.label));
        list.append(item);
    }
    card.replaceChildren(el("p", "progress-count", `${done}/${state.steps.length} concluídos`), list);
}
/**
 * One card per task: the first report places it, later ones update it in place.
 * Returns the card; `before` positions a new card (e.g. ahead of the draft).
 */
export function upsertProgressCard(container, state, before = null) {
    const existing = [
        ...container.querySelectorAll(".progress-card"),
    ].find((card) => card.dataset.taskId === state.task_id);
    const card = existing ?? el("div", "progress-card");
    if (!existing) {
        card.dataset.taskId = state.task_id;
        card.setAttribute("role", "status");
        if (before)
            container.insertBefore(card, before);
        else
            container.append(card);
    }
    fillProgress(card, state);
    return card;
}
