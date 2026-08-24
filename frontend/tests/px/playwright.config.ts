import { defineConfig, devices } from "@playwright/test";

// A config of its own rather than a project inside `../../playwright.config.ts`:
// this suite writes evidence for one wave and is run by hand against a stack that is
// already up. Folding it into the browser suite would put a screenshot job in CI's
// critical path for no gate.
export default defineConfig({
  testDir: ".",
  use: { baseURL: process.env.E2E_BASE_URL ?? "http://127.0.0.1:5173" },
  reporter: [["list"]],
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
