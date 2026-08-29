import { defineConfig, devices } from "@playwright/test";

const frontendPort = process.env.E2E_FRONTEND_PORT ?? "5173";
const frontendBase = `http://127.0.0.1:${frontendPort}`;

export default defineConfig({
  use: { baseURL: frontendBase },
  testDir: "./tests/e2e",
  webServer: {
    command: `npm run dev -- --host 127.0.0.1 --port ${frontendPort}`,
    url: frontendBase,
    reuseExistingServer: true,
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    { name: "firefox", use: { ...devices["Desktop Firefox"] } },
    { name: "webkit", use: { ...devices["Desktop Safari"] } },
  ],
});
