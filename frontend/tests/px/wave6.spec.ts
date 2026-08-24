import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { resolve } from "node:path";

// My Work and the reorganised rail (PX-49/PX-63). Wave 6's visible outcome, plus wave 3's
// navigation half.
//
// The assertion worth having here is the **three-state** one: the "no eligible runner"
// section must say it could not answer rather than saying zero, and against a live Central
// with nothing connected that section is answerable, so the picture shows the answered
// case. The unanswerable case is a component test — it needs a Central without a registry,
// which a running one is not.

const user = process.env.E2E_ADMIN_USER ?? "admin";
const password = process.env.E2E_ADMIN_PASSWORD ?? "px-measure-pw-1";
const OUT = resolve(process.cwd(), "..", "artifacts/px/local/w6");

test.use({ viewport: { width: 1600, height: 1000 } });

async function signIn(page: Page): Promise<void> {
  await page.goto("/login");
  await page.locator('input[name="username"]').fill(user);
  await page.locator('input[name="password"]').fill(password);
  await page.getByRole("button", { name: /sign in/i }).click();
  await expect(page).toHaveURL(/\/(dashboard|nodes|sessions|\/)$|\/$/);
}

test.beforeAll(() => mkdirSync(OUT, { recursive: true }));

test("My Work answers the question without opening a project", async ({
  page,
}) => {
  await signIn(page);
  await page.goto("/my-work");

  // Six sections, or five for a reader without `task.approve`. The admin has it.
  const sections = page.locator("[data-section]");
  await expect(sections).toHaveCount(6);
  await expect(page.locator("[data-section='no-runner']")).toBeVisible();
  await page.screenshot({ path: `${OUT}/01-my-work.png`, fullPage: true });

  // Every section either answers or says it could not. Neither may be silent.
  for (const key of [
    "waiting",
    "approval",
    "failed",
    "assigned",
    "no-runner",
    "delivered",
  ]) {
    const section = page.locator(`[data-section='${key}']`);
    const answered = await section.locator("[data-count]").count();
    const unanswerable = await section.locator("[data-unavailable]").count();
    expect(answered + unanswerable).toBeGreaterThan(0);
  }

  // The rail: Home, My Work, Projects first, and two group headings.
  const rail = page.locator('nav[aria-label="Primary"]');
  // The rail renders an icon glyph and the label in one anchor, so the text carries
  // both. Compared on the label rather than the whole node.
  const labels = (await rail.locator("a").allInnerTexts()).map((text) =>
    text.split("\n").pop()!.trim(),
  );
  expect(labels.slice(0, 3)).toEqual(["Home", "My Work", "Projects"]);
  await expect(rail.locator("[data-nav-group]")).toHaveCount(2);
  await page.screenshot({
    path: `${OUT}/02-navigation.png`,
    clip: { x: 0, y: 0, width: 240, height: 520 },
  });

  // `/dashboard` is now the alias and `/` is the page.
  await page.goto("/dashboard");
  await expect(page).toHaveURL(/\/$/);
  await page.screenshot({ path: `${OUT}/03-home.png`, fullPage: true });
});
