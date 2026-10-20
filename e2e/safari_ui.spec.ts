import fs from "node:fs";
import path from "node:path";
import { test, expect } from "@playwright/test";

test.describe("Clawhouse Lovable UI in Safari (WebKit)", () => {
  test.afterAll(() => {
    const customAgentDir = path.resolve("claw/agents/nyctaxi_analyst");
    if (fs.existsSync(customAgentDir)) {
      fs.rmSync(customAgentDir, { recursive: true, force: true });
    }
  });

  test("loads chat shell, navigation, and composer", async ({ page }) => {
    await page.goto("/chat");

    await expect(page).toHaveTitle(/Clawhouse/);
    await expect(page.getByRole("link", { name: "Chat" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Sessions" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Agents" })).toBeVisible();
    await expect(page.getByRole("button", { name: "New session" })).toBeVisible();
    await expect(page.getByPlaceholder(/Message @/)).toBeVisible();
  });

  test("agents screen lists crew and new agent action", async ({ page }) => {
    await page.goto("/agents");
    await expect(page.getByRole("heading", { name: "Agents" })).toBeVisible();
    await expect(page.getByRole("button", { name: /New agent/i })).toBeVisible();
  });

  test("approvals and status screens render", async ({ page }) => {
    await page.goto("/approvals");
    await expect(page.getByRole("heading", { name: "Approvals" })).toBeVisible();

    await page.goto("/status");
    await expect(page.getByRole("heading", { name: "Status" })).toBeVisible();
  });
});
