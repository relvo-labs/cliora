import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { resolve } from "node:path";

// Wave 3's visible outcome (plan/26/00 §4b): the project has sub-routes and the
// navigation is links. **The evidence is the per-page screenshot**; the assertions exist
// so a broken run fails loudly rather than writing a picture of an error page.
//
// The one assertion that is more than a smoke check is the `?tab=` redirect: every one of
// those URLs is a bookmark somebody has, and after D117 there is no flag to fall back to.
//
//   cd frontend && E2E_PX_PROJECT=<uuid> npx playwright test --config tests/px/playwright.config.ts wave3

const project = process.env.E2E_PX_PROJECT ?? "";
const user = process.env.E2E_ADMIN_USER ?? "admin";
const password = process.env.E2E_ADMIN_PASSWORD ?? "px-measure-pw-1";
const OUT = resolve(process.cwd(), "..", "artifacts/px/local/w3");

test.use({ viewport: { width: 1600, height: 1000 } });

async function signIn(page: Page): Promise<void> {
  await page.goto("/login");
  await page.locator('input[name="username"]').fill(user);
  await page.locator('input[name="password"]').fill(password);
  await page.getByRole("button", { name: /sign in/i }).click();
  // **The rail, not a URL.** These two specs asserted `/dashboard|nodes|sessions` and were
  // written before this phase swapped the landing route: `/` is the dashboard now and
  // `/dashboard` redirects to it (`plan/26/12` §2.19). The nav appearing is what "signed
  // in" actually means, and it does not have to be re-taught when a route moves — which
  // wave 4, 5 and 6 already do, and is why only these two went stale.
  await expect(page.locator('nav[aria-label="Primary"]')).toBeVisible();
}

test.beforeAll(() => mkdirSync(OUT, { recursive: true }));

const SECTIONS = [
  "overview",
  "work",
  "roadmap",
  "requirements",
  "activity",
  "settings",
] as const;

test.describe("the project shell", () => {
  test.skip(project === "", "set E2E_PX_PROJECT to the demo project id");

  test("every section is its own URL, and the old ?tab= links still land", async ({
    page,
  }) => {
    await signIn(page);

    // `/projects/:id` with no section lands on Overview rather than on nothing.
    await page.goto(`/projects/${project}`);
    await expect(page).toHaveURL(new RegExp(`/projects/${project}/overview$`));

    for (const [index, section] of SECTIONS.entries()) {
      await page.goto(`/projects/${project}/${section}`);
      await expect(page).toHaveURL(new RegExp(`/${section}$`));
      const active = page.locator(
        'nav[aria-label="Project sections"] a[data-active="true"]',
      );
      await expect(active).toHaveCount(1);
      await page.screenshot({
        path: `${OUT}/${String(index + 1).padStart(2, "0")}-${section}.png`,
        fullPage: true,
      });
    }

    // The navigation is anchors, so middle-click and "copy link address" work.
    const nav = page.locator('nav[aria-label="Project sections"]');
    await expect(nav.locator("a")).toHaveCount(7);
    await expect(nav.locator("button")).toHaveCount(0);

    // Every legacy tab, and the redirect drops only `tab`.
    for (const [tab, expected] of [
      ["overview", "overview"],
      ["board", "work"],
      ["roadmap", "roadmap"],
      ["requirements", "requirements"],
      ["activity", "activity"],
      ["settings", "settings"],
    ] as const) {
      await page.goto(`/projects/${project}?tab=${tab}`);
      await expect(page).toHaveURL(
        new RegExp(`/projects/${project}/${expected}$`),
      );
    }

    // And the Drawer's own key survives the redirect, which is what makes a link to a
    // card inside a board still a link to that card.
    await page.goto(`/projects/${project}?tab=board&task=nonexistent`);
    await expect(page).toHaveURL(/\/work\?task=nonexistent$/);
    await page.screenshot({ path: `${OUT}/07-legacy-tab-redirect.png` });
  });
});
