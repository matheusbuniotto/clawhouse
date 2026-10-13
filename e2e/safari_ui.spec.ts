import fs from "node:fs";
import path from "node:path";
import { test, expect } from "@playwright/test";

test.describe("Crabriks UI in Safari (WebKit)", () => {
  test.afterAll(() => {
    const customAgentDir = path.resolve("claw/agents/nyctaxi_analyst");
    if (fs.existsSync(customAgentDir)) {
      fs.rmSync(customAgentDir, { recursive: true, force: true });
    }
  });
  test("loads chat surface, rail navigation, and user identity", async ({ page }) => {
    await page.goto("/chat");

    // Title and shell elements
    await expect(page).toHaveTitle(/Crabriks/);
    await expect(page.locator("#rail-user")).toContainText("test-user@databricks.local");

    // Navigation rail links
    const chatLink = page.locator("#nav-chat");
    const sessionsLink = page.locator("#nav-sessions");
    const approvalsLink = page.locator("#nav-approvals");
    const statusLink = page.locator("#nav-status");

    await expect(chatLink).toBeVisible();
    await expect(sessionsLink).toBeVisible();
    await expect(approvalsLink).toBeVisible();
    await expect(statusLink).toBeVisible();

    // Theme toggle
    const themeBtn = page.locator("#theme-toggle");
    await expect(themeBtn).toBeVisible();
    await themeBtn.click();
    await expect(themeBtn).toHaveAttribute("aria-pressed", "true");
    await themeBtn.click();
    await expect(themeBtn).toHaveAttribute("aria-pressed", "false");
  });

  test("provisions and displays custom agent in picker on /new", async ({ page }) => {
    await page.goto("/new");

    // Verify active agent and default card
    await expect(page.locator("#active-agent-desc")).toContainText("main");
    await expect(page.locator(".agent-cards-grid")).toBeVisible();

    // Create a new custom agent
    const nameInput = page.locator("input[placeholder*='Agent name']");
    const descInput = page.locator("input[placeholder='Description']");
    const promptInput = page.locator("textarea[placeholder*='Operating rules']");
    const emojiInput = page.locator("input[placeholder*='Emoji']");

    await nameInput.fill("nyctaxi_analyst");
    await emojiInput.fill("🚕");
    await descInput.fill("NYC Taxi fare anomaly investigator");
    await promptInput.fill("You analyze trip distances and fare anomalies in samples.nyctaxi.trips.");

    // Submit agent creation form
    await page.locator("form.create-agent-form button[type='submit']").click();

    // Check custom agent card is added to picker grid
    const customCard = page.locator(".agent-card", { hasText: "nyctaxi_analyst" });
    await expect(customCard).toBeVisible({ timeout: 5000 });
    await expect(customCard).toContainText("🚕");
    await expect(customCard).toContainText("NYC Taxi fare anomaly investigator");

    // Selecting the card updates active agent description
    await customCard.click();
    await expect(page.locator("#active-agent-desc")).toContainText("nyctaxi_analyst");
  });

  test("chat composer autocompletes agent mentions with @", async ({ page }) => {
    await page.goto("/chat");

    const messageInput = page.locator("#message");
    await expect(messageInput).toBeVisible();

    // Clear any draft and type @ to trigger mention popover
    await messageInput.fill("");
    await messageInput.pressSequentially("@");

    // Mention popover should appear with available agents
    const popover = page.locator(".composer-popover");
    await expect(popover).toBeVisible({ timeout: 5000 });

    const popoverItems = popover.locator(".composer-popover-item");
    await expect(popoverItems.first()).toBeVisible();

    // Click first suggestion and verify input is filled
    await popoverItems.first().click();
    const val = await messageInput.inputValue();
    expect(val).toMatch(/@\w+\s*/);
  });

  test("approvals and status screens render cleanly in Safari", async ({ page }) => {
    // Navigate to approvals
    await page.goto("/approvals");
    await expect(page.getByRole("heading", { name: "Pending Approvals" })).toBeVisible();

    // Navigate to status
    await page.goto("/status");
    await expect(page.getByRole("heading", { name: "Connection & Identity" })).toBeVisible();
  });
});
