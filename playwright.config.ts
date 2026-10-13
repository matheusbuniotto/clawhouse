import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 30000,
  webServer: {
    command:
      "CRABRIKS_DEV_USER=test-user@databricks.local uv run uvicorn crabriks.app:app --port 8765 --host 127.0.0.1",
    port: 8765,
    reuseExistingServer: !process.env.CI,
  },
  use: {
    baseURL: "http://127.0.0.1:8765",
  },
  projects: [
    {
      name: "webkit",
      use: { ...devices["Desktop Safari"] },
    },
  ],
});
