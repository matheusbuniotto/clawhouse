/** Interaction cards in the transcript: questions with buttons (`ask_user`). */

import { el } from "./dom.js";

export interface QuestionCard {
  id: string;
  question: string;
  options: string[];
  default?: string | null;
  multi?: boolean;
}

export interface AnswerResult {
  status: string;
  reply: string;
  pending: QuestionCard[];
}

/** Tool name the transcript stores questions under. */
export const ASK_USER = "ask_user";

function optionButton(label: string, isDefault: boolean): HTMLButtonElement {
  const button = el("button", "question-option", label);
  button.type = "button";
  button.dataset.option = label;
  if (isDefault) {
    button.classList.add("default");
    button.title = "Opção padrão";
  }
  return button;
}

function markChosen(card: HTMLElement, chosen: string[]): void {
  card.dataset.state = "answered";
  for (const button of card.querySelectorAll<HTMLButtonElement>(".question-option")) {
    button.disabled = true;
    const picked = chosen.includes(button.dataset.option ?? "");
    button.classList.toggle("chosen", picked);
    button.setAttribute("aria-pressed", picked ? "true" : "false");
  }
}

function shell(question: QuestionCard): { card: HTMLElement; options: HTMLElement } {
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
export function renderQuestionCard(
  question: QuestionCard,
  onAnswered: (result: AnswerResult) => void,
): HTMLElement {
  const { card, options } = shell(question);
  card.dataset.state = "pending";
  const note = el("p", "question-note");
  const picked = new Set<string>();
  const buttons = question.options.map((label) => optionButton(label, label === question.default));
  options.append(...buttons);

  async function send(selected: string[]): Promise<void> {
    for (const button of buttons) button.disabled = true;
    note.textContent = "Enviando…";
    try {
      const response = await fetch(`/api/questions/${encodeURIComponent(question.id)}/answer`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ selected }),
      });
      if (!response.ok) {
        note.textContent = "Não foi possível enviar a resposta.";
        for (const button of buttons) button.disabled = false;
        return;
      }
      const data = (await response.json()) as Partial<AnswerResult>;
      markChosen(card, selected);
      note.textContent = "";
      onAnswered({ status: data.status ?? "ok", reply: data.reply ?? "", pending: data.pending ?? [] });
    } catch {
      note.textContent = "Erro de rede ao enviar a resposta.";
      for (const button of buttons) button.disabled = false;
    }
  }

  if (question.multi) {
    const submit = el("button", "question-submit", "Enviar");
    submit.type = "button";
    submit.disabled = true;
    for (const button of buttons) {
      button.onclick = () => {
        const label = button.dataset.option ?? "";
        if (picked.has(label)) picked.delete(label);
        else picked.add(label);
        button.setAttribute("aria-pressed", picked.has(label) ? "true" : "false");
        submit.disabled = picked.size === 0;
      };
    }
    submit.onclick = () => {
      submit.remove();
      void send([...picked]);
    };
    card.append(submit);
  } else {
    for (const button of buttons) button.onclick = () => void send([button.dataset.option ?? ""]);
  }
  card.append(note);
  return card;
}

/** The labels a stored `ask_user` result picked: a click, or a job's default. */
export function chosenFromResult(result: string, options: string[]): string[] {
  const clicked = /^The user chose: (.*)$/s.exec(result);
  if (clicked) return clicked[1].split(", ").filter((label) => options.includes(label));
  const fallback = /picked the default option "(.*)"/.exec(result);
  return fallback ? [fallback[1]] : [];
}

/** A question as it reads after reload: buttons disabled, the chosen one marked. */
export function renderAnsweredQuestion(argumentsJson: string, result: string): HTMLElement | null {
  let args: Partial<QuestionCard>;
  try {
    args = JSON.parse(argumentsJson) as Partial<QuestionCard>;
  } catch {
    return null;
  }
  const options = Array.isArray(args.options) ? args.options.map(String) : [];
  if (!args.question || options.length === 0) return null;
  const question: QuestionCard = {
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
