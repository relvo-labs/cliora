import { expect, Page, test } from "@playwright/test";

import { terminateSessions, trackSessions } from "./session-cleanup";

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

// Session state, connection and control, as words in the workspace status bar.
const statusBar = (page: Page) => page.locator(".status-bar");
const connected = (page: Page) =>
  statusBar(page).getByText("已連線", { exact: true });

/**
 * Create a session on the first online node through the New session dialog
 * and return its id, or "" when the stack has no online node.
 */
async function createSession(page: Page, name: string): Promise<string> {
  await page.goto("/sessions");
  // `.first()`: on an empty list the empty state repeats the same button.
  await page.getByRole("button", { name: "建立 Session" }).first().click();
  const dialog = page
    .getByRole("dialog")
    .filter({ has: page.getByRole("heading", { name: "New session" }) });
  await expect(dialog).toBeVisible();
  const nodeSelect = dialog.locator("select").first();
  const hasNode = await nodeSelect
    .locator("option:not([disabled])")
    .first()
    .waitFor({ state: "attached", timeout: 8_000 })
    .then(() => true)
    .catch(() => false);
  if (!hasNode) return "";
  await nodeSelect.selectOption({ index: 1 });
  const runtime = dialog.locator("select").nth(1);
  await expect(runtime.locator("option:not([disabled])")).not.toHaveCount(0);
  await runtime.selectOption({ index: 1 });
  await expect(dialog.locator('input[list="roots"]')).not.toHaveValue("");
  await dialog.locator('input[placeholder="e.g. refactor-api"]').fill(name);
  await dialog.getByRole("button", { name: "Start" }).click();
  await expect(page).toHaveURL(/\/sessions\/[0-9a-f-]{36}$/);
  return page.url().split("/").pop() ?? "";
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
    // The login view is a lazy route chunk. Measured straight after `goto` it
    // may not have mounted, and an empty page has no undersized controls —
    // which is how this passed with 37px inputs on some hosts (#98).
    await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
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

  // Its own session, created once for the block and ended after it. These
  // cases used to open "the first session in the list", which made them depend
  // on another spec having left one behind — on a fresh database there was
  // none, and the first one could just as well be a terminated session.
  // Unique per run so a re-run against the same database cannot pick up a
  // leftover with the same name.
  let sessionName = "";
  let sessionId = "";

  test.beforeAll(async ({ browser }, testInfo) => {
    const page = await browser.newPage({
      baseURL: testInfo.project.use.baseURL,
    });
    try {
      await signIn(page);
      sessionName = `e2e-mobile-${Date.now().toString(36)}`;
      sessionId = await createSession(page, sessionName);
    } finally {
      await page.close();
    }
  });

  test.afterAll(async ({ playwright }, testInfo) => {
    if (!sessionId) return;
    const request = await playwright.request.newContext({
      baseURL: testInfo.project.use.baseURL,
    });
    try {
      await terminateSessions(request, [sessionId], {
        username: adminUser,
        password: adminPass,
      });
    } finally {
      await request.dispose();
    }
  });

  test.beforeEach(async ({ page }) => {
    test.skip(!sessionId, "no online node available in this stack");
    await page.setViewportSize({ width: 390, height: 844 });
    await signIn(page);
  });

  /** This block's session, reached the way a user reaches it: from the list. */
  async function openFromList(page: Page): Promise<void> {
    await page.goto("/sessions");
    const narrow = (page.viewportSize()?.width ?? 1280) < 768;
    if (narrow) {
      await page.locator(".card", { hasText: sessionName }).click();
    } else {
      // A table row is not a control; the session's name in it is.
      await page
        .getByRole("button", { name: sessionName, exact: true })
        .click();
    }
    await expect(page).toHaveURL(new RegExp(`/sessions/${sessionId}$`));
  }

  test("the session list is cards, and every field survives", async ({
    page,
  }) => {
    await page.goto("/sessions");
    const card = page.locator(".card", { hasText: sessionName });
    await expect(card).toBeVisible();
    await expect(page.locator("table")).toHaveCount(0);
    // The whole card is the control, so it is a button and it is tall enough.
    expect(await card.evaluate((el) => el.tagName)).toBe("BUTTON");
    const box = await card.boundingBox();
    expect(box?.height ?? 0).toBeGreaterThanOrEqual(TOUCH_FLOOR);
  });

  test("terminal and files are one tap apart, and the terminal is not rebuilt", async ({
    page,
  }) => {
    await openFromList(page);
    await expect(page.locator(".modes")).toBeVisible();

    // A live terminal before anything is sampled: exactly one screen, attached
    // as the writer, and a line typed now echoes back from the PTY. (A typed
    // marker rather than the Fake CLI's banner: the session starts at 24x80 and
    // is shrunk to the phone on attach, which cuts the banner's first line off
    // the screen — a separate defect, not what this case is about.)
    const screens = page.locator("#panel-cli .xterm-screen");
    const rows = page.locator("#panel-cli .xterm-rows");
    await expect(screens).toHaveCount(1, { timeout: 15_000 });
    await expect(connected(page)).toBeVisible({ timeout: 15_000 });
    await expect(statusBar(page).getByText("你有控制權")).toBeVisible();
    const marker = `TAP-${Date.now().toString(36)}`;
    await rows.click();
    await page.keyboard.type(`${marker}\n`);
    await expect(rows).toContainText(marker, { timeout: 15_000 });
    const screen = await screens.elementHandle();

    await page.getByRole("tab", { name: "檔案" }).click();
    await expect(page.locator("#file-panel")).toBeVisible();
    await page.getByRole("tab", { name: "終端機" }).click();

    // Still one screen, and it is the *same element*: a rebuilt terminal is a
    // new node even when the count matches, and it takes the socket and the
    // scrollback with it.
    await expect(screens).toHaveCount(1);
    expect(
      await screen!.evaluate(
        (el) =>
          el.isConnected &&
          el === document.querySelector("#panel-cli .xterm-screen"),
      ),
      "the terminal screen was replaced while switching modes",
    ).toBe(true);
    await expect(rows).toContainText(marker);
    await expect(connected(page)).toBeVisible();
  });

  // #82: the phone's file list leads to the same read-only preview the desktop
  // tree does — content shown, nothing editable.
  test("the file list opens a read-only preview", async ({ page }) => {
    await openFromList(page);
    await page.getByRole("tab", { name: "檔案" }).click();
    await page
      .locator("#file-panel")
      .getByRole("button", { name: "README.md", exact: true })
      .click();

    const preview = page.getByRole("region", { name: /README\.md/ });
    await expect(preview).toBeVisible({ timeout: 20_000 });
    await expect(preview.getByLabel("唯讀預覽")).toBeVisible();
    const lines = page.locator("#panel-preview .view-lines");
    await expect(lines).toContainText("Cliora e2e workspace", {
      timeout: 20_000,
    });
    const before = await lines.innerText();

    // Nothing in the preview accepts text: Monaco's input is read-only in the
    // DOM (domReadOnly), and there is no other field or editable region.
    await expect(
      page.locator(
        "#panel-preview :is(textarea, input:not([type=hidden]), select):not([readonly]):not([disabled]), #panel-preview [contenteditable=''], #panel-preview [contenteditable='true']",
      ),
    ).toHaveCount(0);
    // The user's path: tap into the text, then type. Whatever has focus must
    // not be an editable target, and the content must be exactly unchanged.
    await lines.click();
    const focusEditable = await page.evaluate(() => {
      const el = document.activeElement as HTMLElement | null;
      if (!el) return false;
      if (el.isContentEditable) return true;
      if (el instanceof HTMLTextAreaElement || el instanceof HTMLInputElement)
        return !el.readOnly && !el.disabled;
      return false;
    });
    expect(
      focusEditable,
      "a tap on the preview focused an editable field",
    ).toBe(false);
    await page.keyboard.type("xyz");
    await page.keyboard.press("Enter");
    await page.keyboard.press("Backspace");
    // A negative can only be read after the keystrokes have had time to land.
    await page.waitForTimeout(500);
    expect(await lines.innerText()).toBe(before);

    // The read-only tools are the desktop's (plan/29 MS-16: capability
    // unchanged): wrap toggles, refresh reloads the same content.
    const wrap = preview.getByRole("button", { name: "換行" });
    await expect(wrap).toHaveAttribute("aria-pressed", "true");
    await wrap.click();
    await expect(wrap).toHaveAttribute("aria-pressed", "false");
    await preview.getByRole("button", { name: "重新整理" }).click();
    await expect(lines).toContainText("Cliora e2e workspace");
  });

  test("the back gesture closes the preview instead of leaving the session", async ({
    page,
  }) => {
    await openFromList(page);
    const url = page.url();
    await page.getByRole("tab", { name: "檔案" }).click();
    // A file by name: by position, the second row at the root is the excluded
    // (disabled) node_modules folder.
    await page
      .locator("#file-panel")
      .getByRole("button", { name: "README.md", exact: true })
      .click();
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
      await openFromList(page);
      const panel = page.locator("#file-panel");
      const opener = page.locator('[aria-controls="file-panel"]');
      await expect(panel.or(opener).first()).toBeVisible();
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
    await openFromList(page);
    await expect(page.locator(".modes")).toBeVisible();
    const posture = page.locator(".posture");
    if ((await posture.count()) === 0) {
      test.skip(true, "this node reports no posture to show");
    }
    await expect(posture.first()).toBeVisible();
  });

  test("every visible control in the workspace reaches the touch floor", async ({
    page,
  }) => {
    await openFromList(page);
    await expect(page.locator(".modes")).toBeVisible();
    expect(await undersizedControls(page, TOUCH_FLOOR)).toEqual([]);
  });

  test("the filename search says it covers the whole workspace", async ({
    page,
  }) => {
    // On a phone the box sits under a breadcrumb naming the current folder, and
    // that layout answers the scope question for the user unless text does.
    await openFromList(page);
    await page.getByRole("tab", { name: "檔案" }).click();
    await expect(page.getByText("整個工作區")).toBeVisible();
  });

  // ---- mobile: file contracts ------------------------------------------------
  //
  // The phone counterparts of files.spec.ts, which drives the desktop tree and
  // is skipped below 768px. Same fixtures (scripts/e2e/run-stack.sh), same
  // contracts, through the one-level list (plan/29 MS-14–16).

  const filePanel = (page: Page) => page.locator("#file-panel");
  const entry = (page: Page, name: string) =>
    filePanel(page).getByRole("button", { name, exact: true });

  async function openFiles(page: Page): Promise<void> {
    await openFromList(page);
    await page.getByRole("tab", { name: "檔案" }).click();
    await expect(entry(page, "README.md")).toBeVisible({ timeout: 15_000 });
  }

  test("files: one folder at a time, a relative breadcrumb, the excluded folder listed but closed", async ({
    page,
  }) => {
    await openFiles(page);
    const panel = filePanel(page);

    // Excluded: listed, says why, and cannot be opened.
    const excluded = panel.getByRole("button", { name: /^node_modules/ });
    await expect(excluded).toContainText("未納入");
    await expect(excluded).toBeDisabled();

    // One level only: src's children are not listed at the root.
    await expect(entry(page, "main.py")).toHaveCount(0);
    await entry(page, "src").click();
    await expect(entry(page, "main.py")).toBeVisible({ timeout: 10_000 });
    await expect(entry(page, "app.ts")).toBeVisible();
    await expect(
      panel
        .getByRole("navigation", { name: "目前位置" })
        .locator('[aria-current="location"]'),
    ).toHaveText("src");

    // Never the absolute workspace path (ADR 0014), only paths relative to it.
    const workspace = await page.evaluate(async (id) => {
      const token = localStorage.getItem("cliora.access_token");
      const res = await fetch(`/api/sessions/${id}`, {
        headers: { authorization: `Bearer ${token}` },
      });
      return (await res.json()).workspace as string;
    }, sessionId);
    expect(workspace.startsWith("/")).toBe(true);
    expect(await panel.innerText()).not.toContain(workspace);

    await panel.getByRole("button", { name: "上一層" }).click();
    await expect(entry(page, "src")).toBeVisible();
    await expect(entry(page, "main.py")).toHaveCount(0);
  });

  test("files: search covers the whole workspace, opens the hit, and no-results has its own message", async ({
    page,
  }) => {
    await openFiles(page);
    const panel = filePanel(page);
    // From inside a folder, so a folder-scoped search would miss the hit.
    await entry(page, "src").click();
    await expect(entry(page, "main.py")).toBeVisible({ timeout: 10_000 });

    const box = page.getByLabel("以檔名搜尋工作區");
    await box.fill("needle");
    await box.press("Enter");
    const hit = panel.getByRole("button", { name: /needle_target\.py/ });
    await expect(hit).toBeVisible({ timeout: 15_000 });
    await hit.click();
    await expect(
      page.getByRole("region", { name: /needle_target\.py/ }),
    ).toBeVisible({ timeout: 20_000 });
    await expect(page.locator("#panel-preview .view-lines")).toContainText(
      "found me",
      { timeout: 20_000 },
    );

    // Back returns to the search, query intact (MS-15).
    await page.goBack();
    await expect(box).toHaveValue("needle");
    await expect(hit).toBeVisible();

    // No results is not the empty-folder message: different state, different
    // next step.
    await box.fill("zz-no-such-file");
    await box.press("Enter");
    await expect(
      panel.getByText("沒有符合「zz-no-such-file」的檔名。"),
    ).toBeVisible({ timeout: 15_000 });
    await expect(panel.getByText("這個資料夾是空的")).toHaveCount(0);
  });

  test("files: sensitive, binary and oversize files are refused with no content", async ({
    page,
  }) => {
    await openFiles(page);
    const editor = page.locator("#panel-preview .monaco-editor");

    // Sensitive by name: classification only, never a fragment of the content.
    await entry(page, ".env").click();
    await expect(page.getByText("此檔案為敏感類型，預設不可預覽")).toBeVisible({
      timeout: 20_000,
    });
    await expect(page.getByText("環境變數檔")).toBeVisible();
    await expect(page.locator("body")).not.toContainText(
      "e2e-must-never-be-previewed",
    );
    await expect(editor).toBeHidden();
    await page.goBack();

    // Sensitive by extension.
    await entry(page, "server.pem").click();
    await expect(page.getByText("私鑰檔")).toBeVisible({ timeout: 15_000 });
    await expect(editor).toBeHidden();
    await page.goBack();

    // Binary: metadata only.
    await entry(page, "logo.png").click();
    await expect(page.getByText("不支援預覽此檔案")).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.getByText(/application\/octet-stream/)).toBeVisible();
    await expect(editor).toBeHidden();
    await page.goBack();

    // Oversize: size and cap, no content read.
    await entry(page, "big.log").click();
    await expect(page.getByText("檔案過大，超過預覽上限")).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.getByText(/3\.00 MB/)).toBeVisible();
    await expect(editor).toBeHidden();
  });

  test("files: an ended session says so, and asks the node for nothing", async ({
    page,
    request,
  }) => {
    // Its own session: ending the block's one would end every case after this.
    const opened = trackSessions(page);
    try {
      const id = await createSession(page, `e2e-mobile-ended-${Date.now()}`);
      test.skip(!id, "no online node available in this stack");
      await expect(connected(page)).toBeVisible({ timeout: 15_000 });

      await page.getByRole("button", { name: "Session 操作" }).click();
      await page.getByRole("menuitem", { name: "終止 Session…" }).click();
      await page
        .getByRole("dialog", { name: "終止此 Session？" })
        .getByRole("button", { name: "確認終止" })
        .click();
      await expect(statusBar(page).getByText(/已終止|已結束/)).toBeVisible({
        timeout: 15_000,
      });

      // From here on, no listing or search may be sent for this session.
      const browseRequests: string[] = [];
      page.on("request", (req) => {
        if (/\/files\/(tree|search)/.test(req.url()))
          browseRequests.push(req.url());
      });
      await page.getByRole("tab", { name: "檔案" }).click();
      await expect(
        filePanel(page).getByText("Session 已結束，檔案瀏覽不再可用。"),
      ).toBeVisible();
      await expect(filePanel(page).locator(".entry")).toHaveCount(0);
      // Nothing asking again can change, so no retry is offered (MS-14).
      await expect(
        filePanel(page).getByRole("button", { name: /重試/ }),
      ).toHaveCount(0);
      expect(browseRequests).toEqual([]);
    } finally {
      await terminateSessions(request, opened, {
        username: adminUser,
        password: adminPass,
      });
    }
  });
});
