import { defineConfig, devices } from "@playwright/test";
export default defineConfig({
  use: { baseURL: "http://127.0.0.1:5173" },
  testDir: "./tests/e2e",
  webServer: {
    command: "npm run dev -- --host 127.0.0.1",
    url: "http://127.0.0.1:5173",
    reuseExistingServer: true,
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    { name: "firefox", use: { ...devices["Desktop Firefox"] } },
    { name: "webkit", use: { ...devices["Desktop Safari"] } },
    // EMULATION, NOT DEVICES (plan/29 MS-23).
    //
    // These two run the mobile layout at a phone's viewport, touch flags and
    // user agent. That buys regression detection — a change that breaks the
    // narrow layout goes red before it merges — and it buys nothing at all
    // towards MSP-R-010, which needs real iOS Safari and real Android Chrome
    // with a real software keyboard, real safe areas and a real IME. A
    // screenshot from here is not device evidence and must never be filed as
    // any. The project names say "emulated" so a report cannot imply otherwise.
    {
      name: "mobile-chrome-emulated",
      use: { ...devices["Pixel 7"] },
    },
    {
      name: "mobile-safari-emulated",
      use: { ...devices["iPhone 14"] },
    },
  ],
});
