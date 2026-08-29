import { defineConfig, devices } from "@playwright/test";

const frontendPort = process.env.E2E_FRONTEND_PORT ?? "5173";
const frontendBase = `http://127.0.0.1:${frontendPort}`;

// A config of its own rather than a project inside `../../playwright.config.ts`:
// this suite writes evidence for one wave and is run by hand against a stack that is
// already up. Folding it into the browser suite would put a screenshot job in CI's
// critical path for no gate.
export default defineConfig({
  testDir: ".",
  use: { baseURL: frontendBase },
  webServer: {
    command: `npm run dev -- --host 127.0.0.1 --port ${frontendPort}`,
    url: frontendBase,
    reuseExistingServer: true,
    timeout: 120_000,
  },
  reporter: [["list"]],
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
