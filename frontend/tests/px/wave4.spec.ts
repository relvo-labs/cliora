import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { resolve } from "node:path";

// Wave 4's visible outcome (plan/26/00 §4b): the Active Board on the read model, the
// Backlog list, filtering, and a keyboard move.
//
// The assertions here are the ones a screenshot cannot make: that a column header is the
// **server's** count, that a quick filter writes the URL and not the view, and that the
// keyboard move goes through and the board reflects it.

const project = process.env.E2E_PX_PROJECT ?? "";
const user = process.env.E2E_ADMIN_USER ?? "admin";
const password = process.env.E2E_ADMIN_PASSWORD ?? "px-measure-pw-1";
const OUT = resolve(process.cwd(), "..", "artifacts/px/local/w4");

test.use({ viewport: { width: 1600, height: 1000 } });

async function signIn(page: Page): Promise<void> {
  await page.goto("/login");
  await page.locator('input[name="username"]').fill(user);
  await page.locator('input[name="password"]').fill(password);
  await page.getByRole("button", { name: /sign in/i }).click();
  await expect(page.locator('nav[aria-label="Primary"]')).toBeVisible();
}

test.beforeAll(() => mkdirSync(OUT, { recursive: true }));

test.describe("the Active Board", () => {
  test.skip(project === "", "set E2E_PX_PROJECT to the demo project id");

  test("four lanes, server counts, quick filters and a keyboard move", async ({
    page,
  }) => {
    await signIn(page);
    await page.goto(`/projects/${project}/work`);

    // Four lanes, and `backlog` is not one of them — it has a view of its own.
    for (const lane of ["ready", "in_progress", "review", "done"]) {
      await expect(page.locator(`[data-group='${lane}']`)).toBeVisible();
    }
    await expect(page.locator("[data-group='backlog']")).toHaveCount(0);
    // Done says what window it shows.
    await expect(
      page.locator("[data-group='done'] .window-note"),
    ).toContainText("7");
    await page.screenshot({
      path: `${OUT}/01-active-board.png`,
      fullPage: true,
    });

    // A quick filter writes `f=` and leaves the view alone (D103).
    await page.locator("[data-chip='high-risk']").click();
    await expect(page).toHaveURL(/[?&]f=/);
    await page.screenshot({
      path: `${OUT}/02-quick-filter.png`,
      fullPage: true,
    });
    await page.locator("[data-revert]").click();
    await expect(page).not.toHaveURL(/[?&]f=/);

    // The list layout is the Backlog.
    await page.locator("[data-layout-list]").click();
    await expect(page.locator(".rows")).toBeVisible();
    await page.screenshot({
      path: `${OUT}/03-backlog-list.png`,
      fullPage: true,
    });
    await page.locator("[data-layout-board]").click();

    // Grouping by attention is offered; sorting by it is not (D92).
    const orders = await page
      .locator("[data-order-selector] option")
      .evaluateAll((options) =>
        options.map((option) => option.getAttribute("value")),
      );
    expect(orders.some((value) => value?.startsWith("attention"))).toBe(false);
    await page.locator("[data-group-selector]").selectOption("attention");
    await expect(page).toHaveURL(/[?&]g=attention/);
    await page.screenshot({
      path: `${OUT}/04-grouped-by-attention.png`,
      fullPage: true,
    });
    await page.locator("[data-group-selector]").selectOption("lifecycle");

    // The keyboard path: the Move dialog, which is the same mutation the drag uses.
    // The card reference is read from the dialog rather than from the button: the board
    // re-renders between resolutions, and `first()` is not the same element twice.
    await page.locator("[data-group='ready'] [data-move-for]").first().click();
    const dialog = page.locator("[data-move-dialog]");
    await expect(dialog).toBeVisible();
    const cardRef = (await dialog.locator("h2").textContent())!
      .replace("移動 ", "")
      .trim();
    await page.screenshot({ path: `${OUT}/05-move-dialog.png` });
    await dialog.locator("[data-move-group]").selectOption("review");
    await dialog.locator("[data-move-confirm]").click();
    await expect(dialog).toBeHidden();
    // Announced in both directions.
    await expect(page.locator("[data-announcement]")).toContainText(cardRef);
    await page.screenshot({ path: `${OUT}/06-after-move.png`, fullPage: true });

    // Full screen is a page state, not a second layout — and it **survives a reload**
    // (PX-36). Local rather than in the URL, so a shared link does not force somebody
    // else's window into it; the reload is what proves the local half.
    await page.locator("[data-toggle-full-screen]").click();
    await expect(
      page.locator(".work-panel[data-full-screen='true']"),
    ).toBeVisible();
    await page.screenshot({
      path: `${OUT}/07-full-screen.png`,
      fullPage: true,
    });
    await page.reload();
    await expect(
      page.locator(".work-panel[data-full-screen='true']"),
    ).toBeVisible();
    await expect(page).not.toHaveURL(/fs=/);
    await page.locator("[data-toggle-full-screen]").click();
    await page.reload();
    await expect(
      page.locator(".work-panel[data-full-screen='false']"),
    ).toBeVisible();
  });

  // --- PX-31 and PX-33, in a browser -------------------------------------------
  //
  // These are the two controls whose *unit* tests cannot see the thing that matters:
  // whether the URL the control writes is a URL the server answers. A search box that
  // debounces correctly and sends a parameter the API ignores looks identical on screen
  // to one that works.

  test("search narrows the board and travels in the link", async ({ page }) => {
    await signIn(page);
    await page.goto(`/projects/${project}/work`);
    const before = await page.locator("[data-card-ref]").count();

    // A string that cannot match everything. Typed rather than filled, so the debounce
    // is exercised the way a person exercises it.
    await page
      .locator("[data-search-input]")
      .pressSequentially("zzz-no-such-card", {
        delay: 30,
      });
    await expect(page).toHaveURL(/[?&]q=zzz-no-such-card/);
    await expect(page.locator("[data-card-ref]")).toHaveCount(0);
    await page.screenshot({
      path: `${OUT}/08-search-empty.png`,
      fullPage: true,
    });

    // **The counts agree with the list.** This is exit condition 1 asserted through the
    // screen: a counts request that dropped `q` would leave a header saying 200 above an
    // empty board.
    for (const lane of ["ready", "in_progress", "review", "done"]) {
      const header = page.locator(`[data-group='${lane}'] .count`);
      if (await header.count()) await expect(header).toContainText("0");
    }

    // Reloading the link lands on the same board, and clearing it comes back.
    await page.reload();
    await expect(page.locator("[data-search-input]")).toHaveValue(
      "zzz-no-such-card",
    );
    await page.locator("[data-clear-search]").click();
    await expect(page).not.toHaveURL(/[?&]q=/);
    await expect(page.locator("[data-card-ref]")).toHaveCount(before);
  });

  test("the filter builder writes the same `f=` a chip writes", async ({
    page,
  }) => {
    await signIn(page);
    await page.goto(`/projects/${project}/work`);

    await page.locator("[data-toggle-filter-builder]").click();
    await page.locator("[data-add-builder-row]").click();
    const row = page.locator("[data-builder-row]").first();
    await row.locator("[data-builder-field]").selectOption("risk");
    await row.locator("[data-builder-value='high']").click();
    // The server answered it: the URL carries `f=` and the board did not error.
    await expect(page).toHaveURL(/[?&]f=/);
    await expect(page.locator("[data-async-error]")).toHaveCount(0);
    await page.screenshot({
      path: `${OUT}/09-filter-builder.png`,
      fullPage: true,
    });

    // Re-opening reads the filter back into the rows rather than showing an empty
    // builder over a filtered board.
    await page.reload();
    await page.locator("[data-toggle-filter-builder]").click();
    await expect(page.locator("[data-builder-row]")).toHaveCount(1);
    await expect(
      page.locator("[data-builder-value='high'][data-active='true']"),
    ).toBeVisible();

    await page.locator("[data-clear-filter]").click();
    await expect(page).not.toHaveURL(/[?&]f=/);
  });

  test("a saved view can be made default, duplicated and deleted", async ({
    page,
  }) => {
    await signIn(page);
    await page.goto(`/projects/${project}/work`);

    // Duplicate first, so everything after this operates on a copy — a test that renames
    // and deletes the project's seeded shared view is a test that breaks the next run.
    const seeded = page.locator("[data-view-selector] option").nth(1);
    const seededId = await seeded.getAttribute("value");
    await page.locator("[data-view-selector]").selectOption(seededId!);

    // The seeded view is shared, and the toolbar says so out loud rather than only as an
    // option suffix — it is the one control on this page whose edits change what other
    // people see.
    await expect(page.locator("[data-shared-view-note]")).toBeVisible();

    // **A unique name per run.** View names are unique per owner per project and the
    // server answers a repeat with 409 — a fixed name makes this test pass exactly once
    // and then fail for a reason that has nothing to do with what it is testing.
    const copyName = `PX 副本 ${Date.now()}`;
    page.once("dialog", (dialog) => dialog.accept(copyName));
    await page.locator("[data-duplicate-view]").click();
    // **Wait for the selection, not only for the option.** The copy appearing in the list
    // and the board switching to it are two steps, and asserting on the first one makes
    // every assertion after it race.
    const copy = page.locator("[data-view-selector] option", {
      hasText: copyName,
    });
    await expect(copy).toHaveCount(1);
    await expect(page.locator("[data-view-selector]")).toHaveValue(
      (await copy.getAttribute("value"))!,
    );
    await page.screenshot({
      path: `${OUT}/10-view-duplicated.png`,
      fullPage: true,
    });

    // A duplicate is always personal, whatever it was copied from — copying a shared view
    // is how somebody experiments without changing what the team sees. So the shared note
    // is gone, and "set as default" is not offered at all: the server refuses a personal
    // default, because the default is what somebody sees on their *first* visit here.
    await expect(page.locator("[data-shared-view-note]")).toHaveCount(0);
    await expect(page.locator("[data-set-default]")).toHaveCount(0);
    await expect(page.locator("[data-cannot-default]")).toBeVisible();

    page.once("dialog", (dialog) => dialog.accept(`${copyName}（改名）`));
    await page.locator("[data-rename-view]").click();
    await expect(page.locator("[data-view-selector]")).toContainText(
      "（改名）",
    );

    // Delete confirms, and pressing cancel keeps it.
    page.once("dialog", (dialog) => dialog.dismiss());
    await page.locator("[data-delete-view]").click();
    await expect(page.locator("[data-view-selector]")).toContainText(
      "（改名）",
    );

    page.once("dialog", (dialog) => dialog.accept());
    await page.locator("[data-delete-view]").click();
    await expect(page.locator("[data-view-selector]")).not.toContainText(
      "（改名）",
    );
    // Back to the unfiltered board rather than to another view: `?view=` pointing at a
    // deleted row is a 404 on the next load.
    await expect(page).not.toHaveURL(/[?&]view=/);
  });

  // --- the project's default view (plan/26/06 §2, exit condition) ---------------
  test("with no filter and no view, the project's default is applied", async ({
    page,
  }) => {
    await signIn(page);
    await page.goto(`/projects/${project}/work`);

    // The seeded `Active Work` view is this project's default, and the toolbar says it is
    // in effect even though the URL names none. Without this the first screen is every
    // card in the project unfiltered — the picture this phase exists to replace.
    await expect(page).not.toHaveURL(/[?&]view=/);
    await expect(page).not.toHaveURL(/[?&]f=/);
    await expect(page.locator("[data-is-default]")).toBeVisible();
    await expect(page.locator("[data-modified]")).toHaveCount(0);
    await page.screenshot({
      path: `${OUT}/14-default-view.png`,
      fullPage: true,
    });

    // **And it does not follow the reader into the list layout.** The default view is a
    // board view; applied to the Backlog it would show the four active lanes, so a card
    // somebody had just created there would vanish as they typed it.
    await page.locator("[data-layout-list]").click();
    await expect(page.locator("[data-is-default]")).toHaveCount(0);

    // Naming a filter takes over, and the toolbar says the view is modified.
    await page.locator("[data-layout-board]").click();
    await page.locator("[data-chip='high-risk']").click();
    await expect(page.locator("[data-modified]")).toBeVisible();
    await page.locator("[data-revert]").click();
    await expect(page.locator("[data-modified]")).toHaveCount(0);
  });

  // --- PX-30's Ready transition, end to end ------------------------------------
  test("the Ready dialog lists what is missing and can be pressed through", async ({
    page,
  }) => {
    await signIn(page);
    await page.goto(`/projects/${project}/work?g=lifecycle`);
    await page.locator("[data-layout-list]").click();

    // A new card has nothing ticked, so it is the reliable subject — and creating one is
    // the flow a person is in when they hit this.
    const title = `PX ready ${Date.now()}`;
    await page.locator("[data-new-card]").fill(title);
    await page.locator("[data-create-card]").click();
    const row = page.locator(".rows li", { hasText: title });
    await expect(row).toBeVisible();

    await row.locator("[data-send-ready]").click();
    const dialog = page.locator("[data-ready-dialog]");
    await expect(dialog).toBeVisible();
    // **The sentence that stops it reading as a gate.** `plan/26/06` §5 makes the wording
    // a requirement: without it the first person to press through believes they bypassed
    // something.
    await expect(page.locator("[data-not-a-gate]")).toContainText(
      "不會阻擋這次移動",
    );
    await expect(dialog.locator("[data-fill]")).not.toHaveCount(0);
    await page.screenshot({
      path: `${OUT}/11-ready-dialog.png`,
      fullPage: true,
    });

    // "Fill it in" opens the card **on the item**, which is the exit condition
    // (`plan/26/06` §6: 點第一列 → Drawer 開啟且焦點在對應欄位).
    const firstKey = await dialog
      .locator("[data-fill]")
      .first()
      .getAttribute("data-fill");
    await dialog.locator("[data-fill]").first().click();
    await expect(page).toHaveURL(/[?&]task=/);
    const target = page.locator(`[data-readiness='${firstKey}'] input`);
    await expect(target).toBeFocused();
    await page.screenshot({
      path: `${OUT}/12-ready-focused.png`,
      fullPage: true,
    });
    // And the focus target is consumed, so a reload does not yank focus again.
    await expect(page).not.toHaveURL(/[?&]focus=/);

    // Ticking it there is a real write: the item is met when the card is re-read.
    await target.check();
    await expect(target).toBeChecked();
    await page.reload();
    await expect(
      page.locator(`[data-readiness='${firstKey}'] input`),
    ).toBeChecked();
  });

  // --- PX-30's inline rename ---------------------------------------------------
  test("a backlog row renames in place", async ({ page }) => {
    await signIn(page);
    await page.goto(`/projects/${project}/work`);
    await page.locator("[data-layout-list]").click();

    const title = `PX rename ${Date.now()}`;
    await page.locator("[data-new-card]").fill(title);
    await page.locator("[data-create-card]").click();
    const row = page.locator(".rows li", { hasText: title });
    await expect(row).toBeVisible();
    const ref = (await row.getAttribute("data-card-ref"))!;

    await row.locator(`[data-rename-for='${ref}']`).click();
    const input = page.locator(`[data-rename-input='${ref}']`);
    await input.fill(`${title} 改過`);
    await input.press("Enter");
    // Re-queried rather than held: the list re-renders after the write, so the old
    // handle is not the same element.
    await expect(page.locator(`[data-card-ref='${ref}']`)).toContainText(
      "改過",
    );
    await page.screenshot({
      path: `${OUT}/13-inline-rename.png`,
      fullPage: true,
    });

    // **The Drawer never opened.** That is the point of renaming in place: a rename that
    // costs an open, a scroll and a close is a rename people do not do.
    await expect(page).not.toHaveURL(/[?&]task=/);
  });
});
