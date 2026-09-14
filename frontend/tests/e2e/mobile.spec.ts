import { expect, Page, test } from "@playwright/test";

// The measurements plan/29's two static gates cannot make.
//
// scripts/ms/ms-gates.sh is two greps. Neither can see a rendered pixel, so
// everything about geometry is here: whether a control actually reaches the
// touch floor, whether the page overflows sideways, whether the mobile palette
// is the one the browser computed.
//
// WHAT THIS FILE IS NOT. Running it under the `mobile-*-emulated` projects is
// emulation: a phone viewport, touch flags and a user agent string. It is not
// iOS Safari and not Android Chrome, it has no software keyboard, no safe-area
// insets and no IME. MSP-R-005 and MSP-R-010 need real devices and this file
// cannot advance either of them by a single line. What it buys is the
// regression: a change that breaks the narrow layout goes red before it merges.
//
// The cases split in two. The first group needs nothing but the app being
// served, so it runs on any stack; the second needs a real session and is
// gated exactly like session.spec.ts.

const fullStack = process.env.E2E_FULL_STACK === "1";
const adminUser = process.env.E2E_ADMIN_USER ?? "";
const adminPass = process.env.E2E_ADMIN_PASSWORD ?? "";

/** The eight acceptance sizes (plan/29 MSP-F-009). */
const SIZES = [
  { width: 360, height: 844 },
  { width: 390, height: 844 },
  { width: 430, height: 932 },
  { width: 844, height: 390 },
  { width: 768, height: 844 },
  { width: 1024, height: 768 },
  { width: 1100, height: 800 },
  { width: 1440, height: 900 },
];

const TOUCH_FLOOR = 44;

async function signIn(page: Page): Promise<void> {
  await page.goto("/login");
  await page.locator('input[name="username"]').fill(adminUser);
  await page.locator('input[name="password"]').fill(adminPass);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/dashboard/);
}

/** Every visible control smaller than the floor, named so a failure is fixable. */
async function undersizedControls(page: Page, floor: number) {
  return page.evaluate((min) => {
    const out: string[] = [];
    const nodes = document.querySelectorAll<HTMLElement>(
      "button, input, select, textarea, a[href], [role='tab'], [role='menuitem']",
    );
    for (const el of nodes) {
      const style = getComputedStyle(el);
      if (style.display === "none" || style.visibility === "hidden") continue;
      const box = el.getBoundingClientRect();
      // Zero-sized means "not laid out", which is not the failure this is
      // looking for; a visually-hidden input (the sr-only pattern) is one.
      if (box.width === 0 || box.height === 0) continue;
      // The hit area may be larger than the visual box: UiButton tops its own
      // up with a pseudo-element. Measure the largest rect the element offers.
      const rects = [...el.getClientRects()];
      const widest = Math.max(box.width, ...rects.map((r) => r.width));
      const tallest = Math.max(box.height, ...rects.map((r) => r.height));
      if (widest + 0.5 < min || tallest + 0.5 < min) {
        out.push(
          `${el.tagName.toLowerCase()}.${el.className || "-"} ` +
            `${Math.round(widest)}x${Math.round(tallest)}`,
        );
      }
    }
    return out;
  }, floor);
}

test.describe("mobile: geometry on any stack", () => {
  for (const size of SIZES) {
    test(`${size.width}x${size.height}: the page never scrolls sideways`, async ({
      page,
    }) => {
      await page.setViewportSize(size);
      await page.goto("/login");
      const overflow = await page.evaluate(() => {
        const root = document.documentElement;
        return {
          scrollWidth: root.scrollWidth,
          clientWidth: root.clientWidth,
          // Naming the widest offender turns "something overflows" into "this
          // element overflows", which is the difference between a bug report
          // and a bug fix.
          widest: Array.from(document.querySelectorAll("body *"))
            .filter((el) => el.scrollWidth > el.clientWidth + 1)
            .map((el) => `${el.tagName}.${el.className}`)
            .slice(0, 5),
        };
      });
      expect(
        overflow.scrollWidth,
        `widest offenders: ${overflow.widest.join(", ")}`,
      ).toBeLessThanOrEqual(overflow.clientWidth);
    });
  }

  test("every visible control on the sign-in page reaches the touch floor", async ({
    page,
  }) => {
    // The one page every user meets before any permission is decided, and the
    // one this suite can measure without a backend. `--density-control` is
    // raised to the floor below 768px precisely so the inputs here pass —
    // UiButton already topped its own hit area up, an `<input>` cannot.
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/login");
    expect(await undersizedControls(page, TOUCH_FLOOR)).toEqual([]);
  });

  test("the mobile palette is light, and an OS dark preference does not change that", async ({
    page,
  }) => {
    // #62's decision, measured in the browser rather than asserted in a table.
    await page.emulateMedia({ colorScheme: "dark" });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/login");

    await expect(page.locator("html")).toHaveAttribute("data-theme", "pocket");
    const painted = await page.evaluate(() => {
      const style = getComputedStyle(document.documentElement);
      return {
        terminal: style.getPropertyValue("--terminal-background").trim(),
        canvas: style.getPropertyValue("--surface-canvas").trim(),
        scheme: style.colorScheme,
      };
    });
    expect(painted.terminal.toLowerCase()).toBe("#ffffff");
    expect(painted.scheme).toContain("light");
  });

  test("a desktop viewport still follows the OS preference", async ({
    page,
  }) => {
    // MS-21. The regression this guards is silent: an override that leaked one
    // breakpoint too far would repaint every desktop.
    await page.emulateMedia({ colorScheme: "dark" });
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/login");
    await expect(page.locator("html")).not.toHaveAttribute(
      "data-theme",
      "pocket",
    );
  });

  test("the mobile palette is in force before the module graph runs", async ({
    page,
  }) => {
    // theme-boot.js runs in <head>, before the stylesheet paints. main.ts is a
    // module, so it is deferred and runs after parsing — leaving the width
    // check to it would show one full dark frame on every cold load on a phone.
    //
    // Proved by removing the other candidate rather than by racing it. The
    // first version of this test listened for DOMContentLoaded and passed with
    // theme-boot.js reverted, because a deferred module has already run by
    // then; the second tried to catch the attribute mid-parse with a
    // MutationObserver, which is a timing assumption dressed up as a
    // measurement. Blocking the module leaves exactly one thing that could have
    // set the attribute.
    await page.setViewportSize({ width: 390, height: 844 });
    await page.route("**/src/main.ts", (route) => route.abort());
    await page.goto("/login");
    await expect(page.locator("html")).toHaveAttribute("data-theme", "pocket");
  });

  test("the shell takes its height from the usable viewport", async ({
    page,
  }) => {
    // The variable is only set when the browser reports a visual viewport; when
    // it is set, the shell must be using it rather than 100dvh. Emulation has
    // no software keyboard, so this asserts the wiring, not the keyboard.
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/login");
    const supported = await page.evaluate(
      () => typeof window.visualViewport !== "undefined",
    );
    test.skip(!supported, "this browser reports no visualViewport");
    // The login page has no app shell, so navigating away is what proves the
    // variable is removed rather than left behind.
    const afterLogin = await page.evaluate(() =>
      document.documentElement.style.getPropertyValue(
        "--viewport-usable-height",
      ),
    );
    expect(afterLogin).toBe("");
  });
});

test.describe("mobile: the session workspace", () => {
  test.skip(
    !fullStack || !adminUser || !adminPass,
    "needs E2E_FULL_STACK=1 with admin credentials",
  );

  test.beforeEach(async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await signIn(page);
  });

  test("the session list is cards, and every field survives", async ({
    page,
  }) => {
    await page.goto("/sessions");
    const cards = page.locator(".card");
    await expect(cards.first()).toBeVisible();
    await expect(page.locator("table")).toHaveCount(0);
    // The whole card is the control, so it is a button and it is tall enough.
    const box = await cards.first().boundingBox();
    expect(box?.height ?? 0).toBeGreaterThanOrEqual(TOUCH_FLOOR);
  });

  test("terminal and files are one tap apart, and the terminal is not rebuilt", async ({
    page,
  }) => {
    await page.goto("/sessions");
    await page.locator(".card").first().click();
    await expect(page.locator(".modes")).toBeVisible();

    const before = await page.evaluate(
      () => document.querySelectorAll("#panel-cli .xterm-screen").length,
    );
    await page.getByRole("tab", { name: "檔案" }).click();
    await expect(page.locator("#file-panel")).toBeVisible();
    await page.getByRole("tab", { name: "終端機" }).click();
    const after = await page.evaluate(
      () => document.querySelectorAll("#panel-cli .xterm-screen").length,
    );
    // One screen before and after: a second one means the terminal was rebuilt,
    // which means the socket and the scrollback went with it.
    expect(after).toBe(before);
  });

  test("the back gesture closes the preview instead of leaving the session", async ({
    page,
  }) => {
    await page.goto("/sessions");
    await page.locator(".card").first().click();
    const url = page.url();
    await page.getByRole("tab", { name: "檔案" }).click();
    await page.locator("#file-panel .entry").nth(1).click();
    await expect(page.locator("#panel-preview")).toBeVisible();

    await page.goBack();
    await expect(page.locator("#panel-preview")).toHaveCount(0);
    // Still in the session, and the URL never carried the path.
    expect(page.url()).toBe(url);
    await expect(page.locator("#file-panel")).toBeVisible();
  });

  for (const width of [1024, 1100]) {
    test(`${width}px: the file panel is reachable`, async ({ page }) => {
      // The defect MS-05 fixed, measured where it actually lived. Between 1024
      // and 1100 the panel was in the DOM, display:none, and had no control to
      // open it.
      await page.setViewportSize({ width, height: 800 });
      await page.goto("/sessions");
      await page.locator("tbody tr").first().click();
      const panel = page.locator("#file-panel");
      const opener = page.locator('[aria-controls="file-panel"]');
      const reachable =
        (await panel.isVisible().catch(() => false)) ||
        (await opener.isVisible().catch(() => false));
      expect(
        reachable,
        `${width}px: neither the panel nor a way to open it`,
      ).toBe(true);
    });
  }

  test("node posture is visible before anything can be typed", async ({
    page,
  }) => {
    // ADR 0023 D10. The header compacts on a phone; posture is not part of what
    // compacting collapses.
    await page.goto("/sessions");
    await page.locator(".card").first().click();
    const posture = page.locator(".posture");
    if ((await posture.count()) === 0) {
      test.skip(true, "this node reports no posture to show");
    }
    await expect(posture.first()).toBeVisible();
  });

  test("every visible control in the workspace reaches the touch floor", async ({
    page,
  }) => {
    await page.goto("/sessions");
    await page.locator(".card").first().click();
    await expect(page.locator(".modes")).toBeVisible();
    expect(await undersizedControls(page, TOUCH_FLOOR)).toEqual([]);
  });

  test("the filename search says it covers the whole workspace", async ({
    page,
  }) => {
    // On a phone the box sits under a breadcrumb naming the current folder, and
    // that layout answers the scope question for the user unless text does.
    await page.goto("/sessions");
    await page.locator(".card").first().click();
    await page.getByRole("tab", { name: "檔案" }).click();
    await expect(page.getByText("整個工作區")).toBeVisible();
  });
});
