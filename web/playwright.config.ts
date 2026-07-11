import { defineConfig, devices } from "@playwright/test";

const port = Number(process.env.NARRASCAPE_E2E_PORT ?? "8876");

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: {
    command: `narrascape workbench -p ../examples/golden-sample --host 127.0.0.1 --port ${port}`,
    url: `http://127.0.0.1:${port}/api/snapshot`,
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
