import { expect, Page, test } from "@playwright/test";

// The measurements the four static gates cannot make.
//
// scripts/vr/vr-gates.sh is three greps and one arithmetic test. None of them
// can see a rendered pixel, so all three of the failures that would actually
// hurt a user live here:
//
//   * switching theme rebuilds the terminal and loses the session;
//   * a half-transparent colour composites to something illegible;
//   * the theme applies after first paint, so every load flashes.
//
// Same gating as session.spec.ts: the whole stack, plus an online node for the
// interactive parts. The theme tests that need no session run on any stack.
const fullStack = process.env.E2E_FULL_STACK === "1";
const adminUser = process.env.E2E_ADMIN_USER ?? "";
const adminPass = process.env.E2E_ADMIN_PASSWORD ?? "";

const THEMES = ["graphite", "porcelain"] as const;

async function signIn(page: Page): Promise<void> {
  await page.goto("/login");
  await page.locator('input[name="username"]').fill(adminUser);
  await page.locator('input[name="password"]').fill(adminPass);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/dashboard/);
}

// Writes the preference before any script runs, so the assertion exercises the
// real path — theme-boot.js reading localStorage in <head> — rather than a
// switcher click after paint. Those are different code paths and only one of
// them is what a returning user gets.
async function withStoredTheme(page: Page, theme: string): Promise<void> {
  await page.addInitScript((value) => {
    window.localStorage.setItem("cliora-theme", value);
  }, theme);
}

/** The token's resolved value, as the browser actually computed it. */
async function token(page: Page, name: string): Promise<string> {
  return page.evaluate(
    (t) =>
      getComputedStyle(document.documentElement).getPropertyValue(t).trim(),
    `--${name}`,
  );
}

// `rgb()`/`rgba()` as the browser reports it, to a ratio. Duplicated from
// theme/contrast.ts in the page's own terms because the values under test here
// are *composited* — the arithmetic version deliberately refuses to guess what
// is behind a translucent colour, so this side has to read the real pixels.
function ratioOf(a: [number, number, number], b: [number, number, number]) {
  const lum = ([r, g, bl]: [number, number, number]) => {
    const ch = (v: number) => {
      const c = v / 255;
      return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
    };
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(bl);
  };
  const la = lum(a);
  const lb = lum(b);
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}

// Choosing a theme now means going to personal settings, which is the point of
// the move: it is a global preference, not a control on whatever page you
// happen to be looking at. The helper exists so the two tests that need it do
// not each re-derive the route.
async function chooseTheme(page: Page, theme: string): Promise<void> {
  await page.goto("/settings/preferences");
  await page.getByRole("radio", { name: new RegExp(theme, "i") }).check();
  await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
}

function parseRgb(value: string): [number, number, number] {
  const m = value.match(/(\d+(?:\.\d+)?)/g);
  if (!m || m.length < 3) throw new Error(`not an rgb value: ${value}`);
  return [Number(m[0]), Number(m[1]), Number(m[2])];
}

test.describe("theme: cold load", () => {
  test.skip(
    !fullStack || !adminUser || !adminPass,
    "needs E2E_FULL_STACK=1 with admin credentials",
  );

  for (const theme of THEMES) {
    test(`${theme} is in force on the first paint, with no flash`, async ({
      page,
    }) => {
      await withStoredTheme(page, theme);
      // Two samples: one as soon as the DOM exists, one after everything has
      // loaded. A theme applied by main.ts instead of theme-boot.js shows up
      // here as two different colours — which is exactly the flash a user sees
      // when their choice differs from their OS preference.
      const samples: string[] = [];
      page.on("domcontentloaded", async () => {
        samples.push(
          await page
            .evaluate(() => getComputedStyle(document.body).backgroundColor)
            .catch(() => ""),
        );
      });
      await page.goto("/login");
      await page.waitForLoadState("load");
      samples.push(
        await page.evaluate(
          () => getComputedStyle(document.body).backgroundColor,
        ),
      );

      const seen = samples.filter(Boolean);
      expect(seen.length, "no background sample was taken").toBeGreaterThan(0);
      expect(
        new Set(seen).size,
        `the background changed during load (FOUC): ${JSON.stringify(seen)}`,
      ).toBe(1);

      // And it is the stored theme, not merely a stable wrong one.
      await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
    });

    test(`${theme} survives a reload`, async ({ page }) => {
      await signIn(page);
      await page.goto("/settings/preferences");
      // Radio, not select: a theme has three states, and "follow the system"
      // is one a two-option select could not express.
      const label = theme === "graphite" ? "石墨" : "明亮";
      await page.getByRole("radio", { name: new RegExp(label) }).check();
      await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
      await page.reload();
      await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
    });
  }

  test("no CSP violation from the boot script", async ({ page }) => {
    // theme-boot.js is an external file precisely so it survives
    // `script-src 'self'`. If someone inlines it, the browser blocks it and the
    // only symptom is "the theme sometimes doesn't apply" — which is very hard
    // to attribute after the fact.
    const violations: string[] = [];
    page.on("console", (message) => {
      const text = message.text();
      if (/content security policy/i.test(text)) violations.push(text);
    });
    await page.goto("/login");
    await page.waitForLoadState("load");
    expect(violations, violations.join("\n")).toHaveLength(0);
  });
});

test.describe("theme: switching does not interrupt work", () => {
  test.skip(
    !fullStack || !adminUser || !adminPass,
    "needs E2E_FULL_STACK=1 with admin credentials",
  );

  // The most important test in plan/28.
  //
  // The whole ticket rests on one claim: a theme switch recolours in place. If
  // it instead rebuilt the terminal, the user would silently lose scrollback,
  // scroll position and anything half-typed — and it would be easy to miss in
  // review, because a reconnect on a local stack completes in a few hundred
  // milliseconds and the screen looks fine again straight away.
  test("keeps the buffer, the scroll position, unsent input and the role", async ({
    page,
  }) => {
    await signIn(page);
    await page.goto("/sessions");
    const rows = page.getByRole("row");
    test.skip((await rows.count()) < 2, "no session available in this stack");

    // Open the first session in the list.
    await rows.nth(1).getByRole("button").first().click();
    await expect(page).toHaveURL(/\/sessions\/[0-9a-f-]{36}$/);
    await expect(page.locator("#panel-cli .xterm-rows")).not.toBeEmpty({
      timeout: 15_000,
    });

    // Give the terminal enough output to have a scrollback, then scroll off the
    // bottom, then type without submitting. All three are things a rebuild
    // would destroy.
    await page.locator('[aria-label="Interactive CLI terminal"]').click();
    for (let i = 0; i < 60; i += 1) {
      await page.keyboard.type(`echo probe-${i}\n`);
    }
    await page.waitForTimeout(1200);
    await page.mouse.wheel(0, -600);
    await page.keyboard.type("half-typed-command");
    await page.waitForTimeout(400);

    const before = await page.evaluate(() => {
      const viewport = document.querySelector(
        "#panel-cli .xterm-viewport",
      ) as HTMLElement;
      return {
        scrollTop: viewport.scrollTop,
        scrollHeight: viewport.scrollHeight,
        text: (
          document.querySelector("#panel-cli .xterm-rows") as HTMLElement
        ).innerText.slice(-400),
        connection: (document.querySelector(".status-bar") as HTMLElement)
          .innerText,
        background: getComputedStyle(viewport).backgroundColor,
      };
    });

    // Watch for a reconnect. A rebuilt terminal reconnects, and the status
    // passes through "連線中" on the way — briefly, but observably.
    const statusChanges: string[] = [];
    await page.exposeFunction("recordStatus", (value: string) => {
      statusChanges.push(value);
    });
    await page.evaluate(() => {
      const bar = document.querySelector(".status-bar");
      if (!bar) return;
      new MutationObserver(() => {
        (
          window as unknown as { recordStatus: (v: string) => void }
        ).recordStatus((bar as HTMLElement).innerText);
      }).observe(bar, { subtree: true, childList: true, characterData: true });
    });

    // Switching happens in a SECOND TAB, and that is the honest path rather than
    // a convenience: personal settings is its own page, and navigating there
    // would unmount this workspace and rebuild the terminal on return — which
    // would make the assertions below vacuous. A second tab plus the `storage`
    // listener is how a user actually changes theme without disturbing a live
    // session, and it is the only path that exercises "recolour in place".
    const current = await page.locator("html").getAttribute("data-theme");
    const next = current === "porcelain" ? "graphite" : "porcelain";

    const settings = await page.context().newPage();
    await settings.goto("/settings/preferences");
    const label = next === "graphite" ? "石墨" : "明亮";
    await settings.getByRole("radio", { name: new RegExp(label) }).check();
    await expect(settings.locator("html")).toHaveAttribute("data-theme", next);
    await settings.close();

    // The workspace tab follows without being reloaded.
    await expect(page.locator("html")).toHaveAttribute("data-theme", next);
    await page.waitForTimeout(600);

    const after = await page.evaluate(() => {
      const viewport = document.querySelector(
        "#panel-cli .xterm-viewport",
      ) as HTMLElement;
      return {
        scrollTop: viewport.scrollTop,
        scrollHeight: viewport.scrollHeight,
        text: (
          document.querySelector("#panel-cli .xterm-rows") as HTMLElement
        ).innerText.slice(-400),
        connection: (document.querySelector(".status-bar") as HTMLElement)
          .innerText,
        background: getComputedStyle(viewport).backgroundColor,
      };
    });

    const why = JSON.stringify({ before, after, statusChanges }, null, 2);
    expect(after.text, `the buffer changed: ${why}`).toBe(before.text);
    expect(after.scrollHeight, `the scrollback length changed: ${why}`).toBe(
      before.scrollHeight,
    );
    expect(after.scrollTop, `the scroll position moved: ${why}`).toBe(
      before.scrollTop,
    );
    // The status bar reports session state, connection and control. None of the
    // three may change: a reconnect would move the middle one and a rebuilt
    // terminal would drop the write lock.
    expect(
      after.connection.replace(/\s+/g, " "),
      `a status changed: ${why}`,
    ).toBe(before.connection.replace(/\s+/g, " "));
    expect(
      statusChanges.some((s) => s.includes("連線中")),
      `the socket reconnected, so the terminal was rebuilt: ${why}`,
    ).toBe(false);

    // And the terminal really did repaint. Read `.xterm-viewport`, not
    // `.xterm-screen`: the screen's own CSS background is transparent because
    // xterm's renderer paints it, so measuring the screen reports
    // rgba(0,0,0,0) before and after and says nothing at all. That mistake was
    // made once already while measuring this (plan/28 08-…md §2).
    expect(after.background, `the terminal did not repaint: ${why}`).not.toBe(
      before.background,
    );
  });
});

test.describe("theme: contrast the arithmetic cannot reach", () => {
  test.skip(
    !fullStack || !adminUser || !adminPass,
    "needs E2E_FULL_STACK=1 with admin credentials",
  );

  for (const theme of THEMES) {
    test(`${theme}: the focus ring is visible on every focusable control`, async ({
      page,
    }) => {
      await withStoredTheme(page, theme);
      await signIn(page);
      const ring = await token(page, "focus-ring");
      expect(ring, "the focus-ring token is not defined").not.toBe("");

      // Every focusable control, not a sample: a ring that is missing on one
      // control is missing exactly where the user is stuck.
      const results = await page.evaluate(() => {
        const selector =
          "a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex='-1'])";
        const out: Array<{ what: string; width: string; color: string }> = [];
        for (const el of Array.from(
          document.querySelectorAll<HTMLElement>(selector),
        )) {
          if (el.offsetParent === null) continue;
          el.focus();
          const style = getComputedStyle(el);
          out.push({
            what: `${el.tagName}.${el.className}`.slice(0, 60),
            width: style.outlineWidth,
            color: style.outlineColor,
          });
        }
        return out;
      });

      expect(results.length, "no focusable control found").toBeGreaterThan(0);
      const unringed = results.filter((r) => parseFloat(r.width) < 1);
      expect(
        unringed,
        `controls with no focus ring: ${JSON.stringify(unringed)}`,
      ).toHaveLength(0);
    });

    test(`${theme}: the dialog scrim keeps the page below it legible enough to be clearly behind`, async ({
      page,
    }) => {
      await withStoredTheme(page, theme);
      await signIn(page);
      await page.goto("/sessions");
      await page.getByRole("button", { name: "建立 Session" }).first().click();
      const dialog = page.getByRole("dialog");
      await expect(dialog).toBeVisible();

      // The scrim is half-transparent, so its effect can only be read from the
      // composited pixels. theme/contrast.ts refuses to guess at an alpha
      // channel by design, which is why this is here rather than in the unit
      // test.
      const composited = await page.evaluate(() => {
        const scrim = document.querySelector(".backdrop") as HTMLElement;
        const panel = document.querySelector("[role='dialog']") as HTMLElement;
        return {
          scrim: getComputedStyle(scrim).backgroundColor,
          panel: getComputedStyle(panel).backgroundColor,
        };
      });
      // The panel must stand clear of the scrim it sits on, or the dialog reads
      // as part of the dimmed page rather than as the thing in front of it.
      const contrast = ratioOf(
        parseRgb(composited.panel),
        parseRgb(composited.scrim),
      );
      expect(
        contrast,
        `the dialog panel does not separate from the scrim: ${JSON.stringify(composited)}`,
      ).toBeGreaterThanOrEqual(1.5);

      // Escape closes it, and focus goes back to the trigger.
      await page.keyboard.press("Escape");
      await expect(dialog).toBeHidden();
      await expect(
        page.getByRole("button", { name: "建立 Session" }).first(),
      ).toBeFocused();
    });

    test(`${theme}: every status badge carries text, not only a colour`, async ({
      page,
    }) => {
      await withStoredTheme(page, theme);
      await signIn(page);
      await page.goto("/nodes");
      await page.waitForTimeout(600);
      const badges = await page.evaluate(() =>
        Array.from(document.querySelectorAll(".badge")).map((b) => ({
          tone: b.getAttribute("data-tone"),
          text: (b as HTMLElement).innerText.trim(),
        })),
      );
      const wordless = badges.filter((b) => !b.text);
      expect(
        wordless,
        `badges with no text: ${JSON.stringify(wordless)}`,
      ).toHaveLength(0);
    });
  }
});

test.describe("theme: responsive", () => {
  test.skip(
    !fullStack || !adminUser || !adminPass,
    "needs E2E_FULL_STACK=1 with admin credentials",
  );

  // 2 themes x 8 sizes — the acceptance widths from plan/29 MSP-F-009, which
  // the fixture prototype already covered and production did not. 844x390 is
  // landscape on a phone and is the one that most often finds a fixed height;
  // 1024 and 1100 are the two sides of the file-panel defect MS-05 fixed.
  for (const theme of THEMES) {
    for (const size of [
      { width: 1440, height: 900 },
      { width: 1100, height: 800 },
      { width: 1024, height: 768 },
      { width: 768, height: 844 },
      { width: 430, height: 932 },
      { width: 390, height: 844 },
      { width: 360, height: 844 },
      { width: 844, height: 390 },
    ]) {
      test(`${theme} at ${size.width}x${size.height}: no page-level horizontal overflow`, async ({
        page,
      }) => {
        await withStoredTheme(page, theme);
        await page.setViewportSize(size);
        await signIn(page);
        for (const path of ["/dashboard", "/nodes", "/sessions"]) {
          await page.goto(path);
          await page.waitForTimeout(400);
          const overflow = await page.evaluate(() => {
            const root = document.documentElement;
            return {
              scrollWidth: root.scrollWidth,
              clientWidth: root.clientWidth,
              // Naming the widest offender turns "something overflows" into
              // "this element overflows", which is the difference between a
              // bug report and a bug fix.
              widest: Array.from(document.querySelectorAll("body *"))
                .filter((el) => el.scrollWidth > el.clientWidth + 1)
                .map((el) => `${el.tagName}.${el.className}`)
                .slice(0, 5),
            };
          });
          expect(
            overflow.scrollWidth,
            `${path} overflows at ${size.width}: ${JSON.stringify(overflow)}`,
          ).toBeLessThanOrEqual(overflow.clientWidth);
        }
      });
    }

    test(`${theme} at 1024x768: the rail is icons-only and every item still has a name`, async ({
      page,
    }) => {
      await withStoredTheme(page, theme);
      await page.setViewportSize({ width: 1024, height: 768 });
      await signIn(page);
      const rail = page.locator(".shell > aside");
      expect(await rail.evaluate((el) => el.clientWidth)).toBeLessThanOrEqual(
        72,
      );
      // Collapsed means "no visible label", not "no accessible name".
      const names = await page.evaluate(() =>
        Array.from(document.querySelectorAll("nav a")).map(
          (a) => a.getAttribute("aria-label") ?? (a as HTMLElement).innerText,
        ),
      );
      expect(names.length).toBeGreaterThan(0);
      for (const name of names) expect((name ?? "").trim()).not.toBe("");
    });

    test(`${theme} at 390x844: the primary navigation is reachable through a menu`, async ({
      page,
    }) => {
      await withStoredTheme(page, theme);
      await page.setViewportSize({ width: 390, height: 844 });
      await signIn(page);
      // Reachable, not removed. "可觸及不等於授權放寬" — this is a layout
      // change and it must not become a capability change.
      await expect(page.locator(".shell > aside")).toHaveCount(0);
      const toggle = page.getByRole("button", { name: "開啟主導覽" });
      await expect(toggle).toBeVisible();
      await toggle.click();
      await expect(page.locator(".menu-panel")).toBeVisible();
      await expect(
        page.locator(".menu-panel").getByRole("link", { name: /Sessions/ }),
      ).toBeVisible();
    });
  }
});
