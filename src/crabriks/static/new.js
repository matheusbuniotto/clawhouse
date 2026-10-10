const form = document.querySelector("#start");
const statusNode = document.querySelector("#status");
const button = form?.querySelector("button");
if (!form || !statusNode || !button) {
    throw new Error("new session page is missing a required element");
}
const starter = form;
const statusLine = statusNode;
const startButton = button;
async function start() {
    startButton.disabled = true;
    statusLine.textContent = "";
    const response = await fetch("/api/sessions", { method: "POST" });
    if (!response.ok) {
        statusLine.textContent = "The session could not be started.";
        startButton.disabled = false;
        return;
    }
    const body = (await response.json());
    location.href = `/chat?session=${body.id}`;
}
starter.addEventListener("submit", (event) => {
    event.preventDefault();
    void start();
});
export {};
