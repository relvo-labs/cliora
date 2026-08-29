import { expect, test } from "@playwright/test";

import {
  PROJECT,
  SCREENS,
  assertResolved,
  resolveDrawerTasks,
  signIn,
  withTasks,
} from "./screens";

// HD-05 (plan/27/05). Eight screens, `toHaveScreenshot`, chromium only.
//
// **The threshold is a ratio, not zero.** Font hinting, the caret and the last frame of
// an animation move tens of pixels between runs on the same machine. A suite pinned at 0
// goes red on its first run, and after the third false alarm somebody adds
// `--update-snapshots` to CI — at which point it stops guarding anything while still
// appearing in the report. 0.01 of 1600×1000 is ~16,000 pixels: enough for antialiasing,
// not enough for a button that moved.
//
// **Chromium only.** Three browsers × eight screens is 24 baselines, and 16 of them would
// sit permanently near the tolerance because firefox and webkit render text differently.
//
//   cd frontend && E2E_HD_PROJECT=<uuid> npx playwright test --config tests/hd/playwright.config.ts visual
//   ...add --update-snapshots when a layout change is intended; the diff belongs in review.

test.use({ viewport: { width: 1600, height: 1000 } });

test.describe("visual regression", () => {
  test.skip(PROJECT === "", "set E2E_HD_PROJECT to the seeded project id");

  for (const screen of SCREENS) {
    test(`${screen.id} matches its baseline`, async ({ page }) => {
      await signIn(page);
      const tasks = await resolveDrawerTasks(page, PROJECT);
      const url = withTasks(screen.path(PROJECT), tasks);
      assertResolved(screen.id, url);
      await page.goto(url);
      await screen.ready(page);

      await expect(page).toHaveScreenshot(`${screen.id}.png`, {
        maxDiffPixelRatio: 0.01,
        animations: "disabled",
        caret: "hide",
        // Relative times ("running for 12m") and absolute timestamps change between
        // runs by design. Masked rather than frozen: freezing the clock would also
        // freeze the attention derivation, and level 8 is *about* elapsed time.
        mask: [page.locator("[data-visual-mask]"), page.locator("time")],
        fullPage: false,
      });
    });
  }
});
