// Verify the V2.0 navigation fits the app shell at the two acceptance viewports.
// jsdom cannot measure layout; this runs against the real rendered rail.

import { mkdirSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const frontend = resolve(here, "../../frontend");
const { chromium } = createRequire(resolve(frontend, "package.json"))("@playwright/test");

const base = process.env.E2E_BASE_URL ?? "http://127.0.0.1:5173";
const user = process.env.E2E_ADMIN_USER ?? "e2e-admin";
const password = process.env.E2E_ADMIN_PASSWORD ?? "e2e-admin-pw";
const out = resolve(here, "../../artifacts/pj/local/nav-height.txt");
const browser = await chromium.launch();
const rows = [];

for (const viewport of [
  { width: 1440, height: 900 },
  { width: 1920, height: 1080 },
]) {
  const context = await browser.newContext({ viewport });
  const page = await context.newPage();
  await page.goto(`${base}/login`);
  await page.locator('input[name="username"]').fill(user);
  await page.locator('input[type="password"]').fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL(/\/(dashboard|nodes|sessions)/);
  const result = await page.locator("aside").evaluate((aside) => {
    const nav = aside.querySelector("nav");
    const last = nav?.lastElementChild;
    const asideRect = aside.getBoundingClientRect();
    const lastRect = last?.getBoundingClientRect();
    return {
      clientHeight: aside.clientHeight,
      scrollHeight: aside.scrollHeight,
      lastBottom: lastRect ? Math.ceil(lastRect.bottom - asideRect.top) : 0,
      links: nav?.querySelectorAll("a").length ?? 0,
      groups: nav?.querySelectorAll("[data-nav-group]").length ?? 0,
    };
  });
  const fits = result.scrollHeight <= result.clientHeight && result.lastBottom <= result.clientHeight;
  rows.push(
    `${viewport.width}x${viewport.height} client=${result.clientHeight} scroll=${result.scrollHeight} ` +
      `last=${result.lastBottom} links=${result.links} groups=${result.groups} ${fits ? "FITS" : "OVERFLOWS"}`,
  );
  if (!fits) {
    await browser.close();
    throw new Error(`navigation overflows at ${viewport.width}x${viewport.height}`);
  }
  await context.close();
}

await browser.close();
mkdirSync(dirname(out), { recursive: true });
writeFileSync(out, `${rows.join("\n")}\n`, "utf8");
console.log(rows.join("\n"));
