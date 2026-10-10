const form = document.querySelector<HTMLFormElement>("#start");
const statusNode = document.querySelector<HTMLElement>("#status");
const button = form?.querySelector<HTMLButtonElement>("button");

if (!form || !statusNode || !button) {
  throw new Error("new session page is missing a required element");
}

const starter = form;
const statusLine = statusNode;
const startButton = button;

async function start(): Promise<void> {
  startButton.disabled = true;
  statusLine.textContent = "";
  const response = await fetch("/api/sessions", { method: "POST" });
  if (!response.ok) {
    statusLine.textContent = "The session could not be started.";
    startButton.disabled = false;
    return;
  }
  const body = (await response.json()) as { id: string };
  location.href = `/chat?session=${body.id}`;
}

starter.addEventListener("submit", (event) => {
  event.preventDefault();
  void start();
});
