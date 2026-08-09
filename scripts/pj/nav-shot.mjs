// Per-role navigation screenshots (plan/16 PJ-00 B3, exit condition 6).
//
// The rail is permission-conditional, so one screenshot cannot be the baseline:
// Admin sees six entries, Developer and Viewer see three (plan/16/01-…md §2). This
// signs in as each seeded role against a running stack and captures the rail plus a
// machine-diffable dump of its entries.
//
// The text dump matters as much as the image: a screenshot tells you *that*
// something moved, the dump tells you *what*, and "existing route paths never
// change" (plan/16/00-…md D11) is a claim about hrefs, not pixels.
//
//   cd frontend && node ../scripts/pj/nav-shot.mjs --out ../artifacts/pj/local/baseline
//
// Requires a stack at BASE (default http://127.0.0.1:8000) with scripts/pj/seed_users.py
// already run.

import { mkdirSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const frontend = resolve(here, "../../frontend");
const { chromium } = createRequire(resolve(frontend, "package.json"))("@playwright/test");

const args = new Map();
for (let i = 2; i < process.argv.length; i += 2) args.set(process.argv[i], process.argv[i + 1]);

// The Vite dev server, not Central: `frontend/playwright.config.ts` puts the UI on
// :5173 and proxies the API to :8000. Pointing at Central serves the API only, and
// the failure looks like "the login form never appeared".
const BASE = args.get("--base") ?? process.env.E2E_BASE_URL ?? "http://127.0.0.1:5173";
const OUT = resolve(process.cwd(), args.get("--out") ?? "artifacts/pj/local/baseline");
const LABEL = args.get("--label") ?? "baseline";

const ROLES = [
  { role: "admin", user: process.env.E2E_ADMIN_USER ?? "e2e-admin", pw: process.env.E2E_ADMIN_PASSWORD ?? "e2e-admin-pw" },
  { role: "developer", user: "e2e-developer", pw: process.env.E2E_SEED_PASSWORD ?? "e2e-seed-pw" },
  { role: "viewer", user: "e2e-viewer", pw: process.env.E2E_SEED_PASSWORD ?? "e2e-seed-pw" },
];

mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch();
const dump = [];

for (const { role, user, pw } of ROLES) {
  // A fresh context per role: a leaked token would silently produce three copies of
  // the same screenshot, which is the one failure mode this script must not have.
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();

  await page.goto(`${BASE}/login`, { waitUntil: "domcontentloaded" });
  await page.locator('input[name="username"], input#username, input[type="text"]').first().fill(user);
  await page.locator('input[type="password"]').first().fill(pw);
  await page.locator('button[type="submit"], button:has-text("Sign in")').first().click();
  await page.waitForURL(/\/(dashboard|nodes|sessions)/, { timeout: 15000 });

  const rail = page.locator("aside");
  await rail.waitFor({ state: "visible" });
  await page.screenshot({ path: resolve(OUT, `nav-${LABEL}-${role}.png`), clip: await rail.boundingBox() });

  const entries = await page.locator("aside nav a").evaluateAll((nodes) =>
    nodes.map((n) => `${n.getAttribute("href")}  ${n.textContent.trim().replace(/\s+/g, " ")}`),
  );
  const headings = await page
    .locator("aside nav [data-nav-group]")
    .evaluateAll((nodes) => nodes.map((n) => n.textContent.trim()));
  const width = await page.evaluate(() =>
    getComputedStyle(document.documentElement).getPropertyValue("--layout-sidebar").trim(),
  );

  dump.push(
    `[${role}]  --layout-sidebar: ${width}  entries: ${entries.length}  groups: ${headings.length}`,
    ...entries.map((e) => `  ${e}`),
    ...headings.map((h) => `  GROUP ${h}`),
    "",
  );
  console.log(`${role}: ${entries.length} entries, ${headings.length} group headings`);
  await context.close();
}

await browser.close();
writeFileSync(resolve(OUT, `nav-${LABEL}.txt`), dump.join("\n"), "utf8");
console.log(`wrote ${OUT}/nav-${LABEL}.txt and three PNGs`);
