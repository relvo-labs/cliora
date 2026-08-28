import { defineConfig, devices } from "@playwright/test";

// Its own config, for the same reason `tests/px/` has one: this suite runs against a
// stack that is already up, and folding it into `../../playwright.config.ts` would put a
// screenshot job on CI's critical path for the browser e2e suite.
//
// **`snapshotPathTemplate` is pinned** so the baselines live in one flat directory that
// `GATE-HD-VISUAL-BASELINE` can count. Playwright's default nests them per-spec and per-
// platform, which would make "eight declared, eight stored" an assertion about a
// directory walk rather than about coverage.
export default defineConfig({
  testDir: ".",
  use: { baseURL: process.env.E2E_BASE_URL ?? "http://127.0.0.1:5173" },
  reporter: [["list"]],
  snapshotPathTemplate: "{testDir}/__screenshots__/{arg}{ext}",
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
