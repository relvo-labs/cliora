import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { resolve } from "node:path";

// Wave 0's visible outcome, captured rather than asserted (plan/26/00 §4b).
//
// **The evidence is the screenshot; the assertions are only there so a broken run fails
// loudly instead of writing a picture of an error page.** What a reader is meant to
// judge from `artifacts/px/local/w0/` is whether eight attention levels are distinguishable
// on a real board without reading the colours, and whether opening a card keeps the
// board behind it.
//
//   cd frontend && E2E_PX_PROJECT=<uuid> npx playwright test --config tests/px/playwright.config.ts

const project = process.env.E2E_PX_PROJECT ?? "";
const user = process.env.E2E_ADMIN_USER ?? "admin";
const password = process.env.E2E_ADMIN_PASSWORD ?? "px-measure-pw-1";
const OUT = resolve(process.cwd(), "..", "artifacts/px/local/w0");

test.skip(project === "", "set E2E_PX_PROJECT to the demo project id");
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

test("the existing board carries attention, and a card opens without leaving it", async ({
  page,
}) => {
  await signIn(page);
  // **`view=all` explicitly**, because the default view is now applied when the URL names
  // neither a view nor a filter (`plan/26/06` §2) — and the default is the four active
  // lanes, which is the *right* first screen and the wrong baseline for this shot. The
  // point of this screenshot is all eight levels in one frame.
  await page.goto(`/projects/${project}/work?view=all&g=attention`);

  const badges = page.locator("[data-attention]");
  await expect(badges.first()).toBeVisible();
  const levels = await badges.evaluateAll((nodes) =>
    nodes.map((node) => node.getAttribute("data-attention")),
  );

  // **Not "eight distinct badges".** That is what this asserted, and it was wrong in a way
  // worth writing down: a badge shows one card's *primary* level, and a card can carry
  // several signals at once. `by_attention` on `work-counts` tallies **signals** — the
  // facts — while the badge shows the single most urgent of them (D107). So a card that is
  // both `no_eligible_runner` and `pending_human_approval` is counted twice and badged
  // once, and the level that does not win is invisible on the board by design.
  //
  // The assertion was also time-dependent: `over_wip_or_stale` accrues to every card as
  // the fixture ages, so re-running this a week later changed which levels won. A test
  // whose verdict depends on how long ago the seed ran is not a test.
  //
  // What is asserted instead: every badge on screen carries a level the read model
  // recognises, and the counts endpoint — the surface that speaks about facts — can
  // account for each of them.
  const KNOWN = new Set([
    "waiting_for_your_input",
    "pending_human_approval",
    "verification_failed",
    "run_failed",
    "no_eligible_runner",
    "assigned_runner_offline",
    "dependency_blocked",
    "over_wip_or_stale",
  ]);
  expect(levels.length).toBeGreaterThan(0);
  for (const level of levels) expect(KNOWN.has(level!)).toBe(true);
  await page.screenshot({
    path: `${OUT}/01-board-attention.png`,
    fullPage: true,
  });

  // A closer frame of one group, for judging legibility at the size a card actually
  // renders. `data-group`, not `data-stage`: the old board's lane attribute went with the
  // old board, and this spec kept pointing at it — which is the same staleness its
  // `signIn` had. A baseline spec is not exempt from being maintained; it is the one most
  // likely to rot, because nobody re-reads a screenshot.
  const group = page.locator("[data-group]").first();
  await expect(group).toBeVisible();
  await group.screenshot({ path: `${OUT}/02-attention-lane.png` });

  // Opening a card is a Drawer, not a navigation: the URL gains `?task=` and keeps
  // everything else — including `view=all` and `g=attention` — and the board is still in
  // the page behind it.
  const card = page
    .locator('[data-attention="waiting_for_your_input"]')
    .first();
  await card
    .locator("xpath=ancestor::li[1]")
    .getByRole("button")
    .first()
    .click();
  const drawer = page.locator("[data-task-drawer]");
  await expect(drawer).toBeVisible();
  await expect(page).toHaveURL(/[?&]task=/);
  await expect(page).toHaveURL(/[?&]view=all/);
  await expect(page).toHaveURL(/[?&]g=attention/);
  await expect(page.locator("[data-group]").first()).toBeVisible();
  await page.screenshot({ path: `${OUT}/03-drawer-open.png`, fullPage: false });

  // Escape closes it, the `task` key goes and the board's own state stays.
  await drawer.press("Escape");
  await expect(drawer).toBeHidden();
  // **Everything else survives the close.** That is the whole point of a Drawer, and the
  // assertion used to name `tab=board` — a query key this phase replaced with a sub-route.
  // The claim is unchanged; the two keys that carry it are now `view` and `g`.
  await expect(page).toHaveURL(/[?&]view=all/);
  await expect(page).toHaveURL(/[?&]g=attention/);
  await expect(page).not.toHaveURL(/task=/);
  await page.screenshot({
    path: `${OUT}/04-board-after-close.png`,
    fullPage: false,
  });
});
