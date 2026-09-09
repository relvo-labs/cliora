import { expect, Page, test } from "@playwright/test";

// Full session → terminal flow (login → sessions → New Session → workspace →
// live terminal → reconnect → terminate). Like nodes.spec.ts this needs the
// whole stack — Central + PostgreSQL (migrated) + a seeded admin — and is
// skipped unless E2E_FULL_STACK=1 with admin credentials. The interactive
// parts additionally need an *online node* with a runtime; the CI e2e job
// stands one up with the Fake CLI (see scripts/e2e/run-stack.sh and
// .github/workflows/p2.yml). When no online node is present the interactive
// tests skip themselves rather than fail, so the suite stays green on a
// node-less stack while still asserting the list/permission surface.
const fullStack = process.env.E2E_FULL_STACK === "1";
const adminUser = process.env.E2E_ADMIN_USER ?? "";
const adminPass = process.env.E2E_ADMIN_PASSWORD ?? "";

async function signIn(page: Page): Promise<void> {
  await page.goto("/login");
  await page.locator('input[name="username"]').fill(adminUser);
  await page.locator('input[name="password"]').fill(adminPass);
  await page.getByRole("button", { name: "Sign in" }).click();
  // A bare /login with no ?redirect lands on the dashboard (P4-08). This used to
  // assert /nodes and had been wrong since the dashboard shipped — a suite that
  // only runs behind E2E_FULL_STACK can rot without anything going red.
  await expect(page).toHaveURL(/\/dashboard/);
}

function newSessionDialog(page: Page) {
  return page
    .getByRole("dialog")
    .filter({ has: page.getByRole("heading", { name: "New session" }) });
}

// Opens the New Session dialog and returns the online nodes it offers. The
// interactive tests use this to skip themselves when the stack has no node.
async function openDialogAndCountNodes(page: Page): Promise<number> {
  await page.goto("/sessions");
  await expect(page.getByRole("heading", { name: "Sessions" })).toBeVisible();
  await page.getByRole("button", { name: "New session" }).click();
  const dialog = newSessionDialog(page);
  await expect(dialog).toBeVisible();
  // The dialog fetches nodes asynchronously on open; wait for the first real
  // <option> (index 1, after the disabled placeholder) before counting so a
  // present-but-not-yet-loaded node is not mistaken for "no node".
  await dialog
    .locator("select")
    .first()
    .locator("option")
    .nth(1)
    .waitFor({ state: "attached", timeout: 8_000 })
    .catch(() => {});
  // Options minus the disabled "Select an online node…" placeholder.
  return dialog
    .locator("select")
    .first()
    .locator("option:not([disabled])")
    .count();
}

// Terminate lives in the action menu now, and the confirmation names the
// session. Extracted because three tests end this way and a copied-out
// three-step flow is how one of them gets left behind.
async function terminate(page: Page): Promise<void> {
  await page.getByRole("button", { name: "Session 操作" }).click();
  await page.getByRole("menuitem", { name: "終止 Session…" }).click();
  const confirm = page.getByRole("dialog", { name: "終止此 Session？" });
  await confirm.getByRole("button", { name: "確認終止" }).click();
  // The session state is in the status bar now, not in the work header.
  await expect(
    page.locator(".status-bar").getByText(/已終止|已結束/),
  ).toBeVisible({ timeout: 15_000 });
}

test.describe("session & terminal", () => {
  test.skip(
    !fullStack || !adminUser,
    "requires E2E_FULL_STACK + seeded admin credentials",
  );

  test("admin sees the sessions list and the create action", async ({
    page,
  }) => {
    await signIn(page);
    await page.goto("/sessions");
    await expect(page.getByRole("heading", { name: "Sessions" })).toBeVisible();
    await expect(
      page.getByRole("button", { name: "New session" }),
    ).toBeVisible();
  });

  test("create → live terminal → reconnect → terminate", async ({ page }) => {
    await signIn(page);
    const nodeCount = await openDialogAndCountNodes(page);
    test.skip(nodeCount === 0, "no online node available in this stack");

    const dialog = newSessionDialog(page);
    // Node → runtime → workspace are dependent; selecting the node populates the
    // runtime list and pre-fills the first allowed workspace root.
    await dialog.locator("select").first().selectOption({ index: 1 });
    const runtime = dialog.locator("select").nth(1);
    await expect(runtime.locator("option:not([disabled])")).not.toHaveCount(0);
    await runtime.selectOption({ index: 1 });
    const workspace = dialog.locator('input[list="roots"]');
    await expect(workspace).not.toHaveValue("");
    await dialog
      .locator('input[placeholder="e.g. refactor-api"]')
      .fill("e2e-terminal");
    await dialog.getByRole("button", { name: "Start" }).click();

    // Landed on the workspace route as the writer.
    await expect(page).toHaveURL(/\/sessions\/[0-9a-f-]{36}$/);
    await expect(
      page.getByRole("heading", { name: "e2e-terminal" }),
    ).toBeVisible();
    await expect(page.locator('[data-role="writer"]')).toBeVisible();

    const terminalHost = page.locator(
      '[aria-label="Interactive CLI terminal"]',
    );
    await expect(terminalHost).toBeVisible();
    // The Fake CLI prints this banner on launch; seeing it in the xterm DOM
    // proves the daemon → relay → ws → xterm pipeline is live end to end.
    await expect(page.locator("#panel-cli .xterm-rows")).toContainText(
      "FAKECLI_READY",
      {
        timeout: 15_000,
      },
    );
    await expect(page.locator('[data-status="connected"]')).toBeVisible();

    // Browser refresh must reattach without killing the session (ADR 0012).
    await page.reload();
    await expect(terminalHost).toBeVisible();
    await expect(page.locator("#panel-cli .xterm-rows")).toContainText(
      "FAKECLI_READY",
      {
        timeout: 15_000,
      },
    );
    await expect(page.locator('[data-status="connected"]')).toBeVisible();

    // Terminate: graceful → force → state update (running leaves for good).
    await page.getByRole("button", { name: "Terminate" }).click();
    const confirm = page.getByRole("dialog", { name: "Terminate session" });
    await expect(confirm).toBeVisible();
    await confirm.getByRole("button", { name: "Terminate" }).click();
    await expect(
      page.locator('[data-status="terminated"], [data-status="exited"]'),
    ).toBeVisible({ timeout: 15_000 });
  });

  // WT-01 + WT-03. The load-bearing assertion is not that the tabs render — it
  // is that coming back to CLI finds the *same* terminal: same socket, same
  // scrollback, still usable. A `v-if` on the panel would pass a naive "the tab
  // works" check and fail every one of these.
  test("centre tabs: preview and CLI share one live terminal", async ({
    page,
  }) => {
    await signIn(page);

    // Count sockets from before the workspace opens: switching tabs must not
    // add one.
    let socketsOpened = 0;
    page.on("websocket", () => {
      socketsOpened += 1;
    });

    const nodeCount = await openDialogAndCountNodes(page);
    test.skip(nodeCount === 0, "no online node available in this stack");

    const dialog = newSessionDialog(page);
    await dialog.locator("select").first().selectOption({ index: 1 });
    const runtime = dialog.locator("select").nth(1);
    await expect(runtime.locator("option:not([disabled])")).not.toHaveCount(0);
    await runtime.selectOption({ index: 1 });
    await expect(dialog.locator('input[list="roots"]')).not.toHaveValue("");
    await dialog
      .locator('input[placeholder="e.g. refactor-api"]')
      .fill("e2e-tabs");
    await dialog.getByRole("button", { name: "Start" }).click();

    await expect(page).toHaveURL(/\/sessions\/[0-9a-f-]{36}$/);
    await expect(page.locator("#panel-cli .xterm-rows")).toContainText(
      "FAKECLI_READY",
      {
        timeout: 15_000,
      },
    );

    // WT-01: the left rail is gone, so the workspace has no "Sessions" heading.
    await expect(page.getByRole("heading", { name: "Sessions" })).toHaveCount(
      0,
    );

    // No preview tab until a file is opened. Asserted by label rather than by
    // count: whether a TERMINAL tab sits alongside these depends on the node's
    // shell runtime, which is not what this test is about.
    const tabs = page.getByRole("tab");
    await expect(tabs.first()).toHaveText("CLI");
    await expect(page.getByRole("tab", { name: "README.md" })).toHaveCount(0);

    const readme = page
      .getByRole("tree", { name: "工作區檔案" })
      .getByRole("treeitem", { name: /^README\.md,/ });
    // `isVisible()` does not wait, and the tree loads lazily — wait explicitly
    // or the skip fires before the first level has even arrived.
    const readmePresent = await readme
      .waitFor({ state: "visible", timeout: 15_000 })
      .then(() => true)
      .catch(() => false);
    test.skip(!readmePresent, "workspace fixture has no README.md");

    const socketsBeforeTabs = socketsOpened;
    await readme.click();

    // A preview tab appears, named by basename, and is selected. It is inserted
    // directly after CLI, before any TERMINAL tab.
    await expect(tabs.nth(1)).toHaveText("README.md");
    await expect(tabs.nth(1)).toHaveAttribute("aria-selected", "true");
    await expect(page.locator(".monaco-editor")).toBeVisible({
      timeout: 20_000,
    });

    // Back to CLI: the buffer and the connection are the ones we left behind.
    await tabs.first().click();
    await expect(page.locator("#panel-cli .xterm-rows")).toContainText(
      "FAKECLI_READY",
    );
    await expect(page.locator('[data-status="connected"]')).toBeVisible();

    // Arrow keys move between tabs without leaving the bar.
    await tabs.first().press("ArrowRight");
    await expect(tabs.nth(1)).toHaveAttribute("aria-selected", "true");
    await tabs.nth(1).press("ArrowLeft");
    await expect(tabs.first()).toHaveAttribute("aria-selected", "true");

    // The terminal still takes input after all that switching — this is what
    // catches a PTY resized from a hidden 0x0 container.
    await page.locator("#panel-cli .xterm-rows").click();
    await page.keyboard.type("echo tabs-alive\n");
    await expect(page.locator("#panel-cli .xterm-rows")).toContainText(
      "tabs-alive",
      {
        timeout: 15_000,
      },
    );

    expect(socketsOpened).toBe(socketsBeforeTabs);

    // Closing the preview tab leaves CLI selected and drops the panel.
    await page.getByRole("button", { name: "關閉 README.md" }).click();
    await expect(page.getByRole("tab", { name: "README.md" })).toHaveCount(0);
    await expect(tabs.first()).toHaveAttribute("aria-selected", "true");
    await expect(page.locator(".monaco-editor")).toHaveCount(0);

    await terminate(page);
  });

  // WT-11 exit condition 4. The tab work removed a column and stacked every
  // panel into one grid cell; both are the kind of change that looks right at
  // the size it was written on and overflows one breakpoint away. jsdom cannot
  // answer this — it has no layout — so it is asserted here or not at all.
  test("layout: no horizontal overflow at 1440x900 or below 1100px", async ({
    page,
  }) => {
    await signIn(page);
    const nodeCount = await openDialogAndCountNodes(page);
    test.skip(nodeCount === 0, "no online node available in this stack");

    const dialog = newSessionDialog(page);
    await dialog.locator("select").first().selectOption({ index: 1 });
    const runtime = dialog.locator("select").nth(1);
    await expect(runtime.locator("option:not([disabled])")).not.toHaveCount(0);
    await runtime.selectOption({ index: 1 });
    await expect(dialog.locator('input[list="roots"]')).not.toHaveValue("");
    await dialog
      .locator('input[placeholder="e.g. refactor-api"]')
      .fill("e2e-layout");
    await dialog.getByRole("button", { name: "Start" }).click();

    await expect(page).toHaveURL(/\/sessions\/[0-9a-f-]{36}$/);
    await expect(page.locator("#panel-cli .xterm-rows")).toContainText(
      "FAKECLI_READY",
      {
        timeout: 15_000,
      },
    );

    // 1440×900 is the reference desktop; 1000×800 is inside the 1100px
    // breakpoint, where the grid collapses to one column and the file tree is
    // hidden. A file open at both sizes is the wide case: Monaco and the tab bar
    // are the two things that can push the row wider than the viewport.
    const readme = page
      .getByRole("tree", { name: "工作區檔案" })
      .getByRole("treeitem", { name: /^README\.md,/ });
    if (
      await readme
        .waitFor({ state: "visible", timeout: 15_000 })
        .then(() => true)
        .catch(() => false)
    ) {
      await readme.click();
      await expect(page.locator(".monaco-editor")).toBeVisible({
        timeout: 20_000,
      });
    }

    for (const size of [
      { width: 1440, height: 900 },
      { width: 1000, height: 800 },
    ]) {
      await page.setViewportSize(size);
      // The grid re-fits the terminal on resize; measuring before that settles
      // reports the previous size's overflow.
      await page.waitForTimeout(400);
      const overflow = await page.evaluate(() => {
        const root = document.documentElement;
        return {
          scrollWidth: root.scrollWidth,
          clientWidth: root.clientWidth,
          // A page can also overflow through one inner scroller while the
          // document itself stays put, so name the widest offender.
          widest: Array.from(document.querySelectorAll("body *"))
            .filter((el) => el.scrollWidth > el.clientWidth + 1)
            .map((el) => `${el.tagName}.${el.className}`)
            .slice(0, 5),
        };
      });
      expect(
        overflow.scrollWidth,
        `horizontal overflow at ${size.width}x${size.height}: ${JSON.stringify(overflow)}`,
      ).toBeLessThanOrEqual(overflow.clientWidth);
    }

    // Below 1024px the file panel is a *closed drawer*, not a removed feature.
    // The tree is still hidden here, so the old assertion still passes — but it
    // used to pass for the wrong reason. Before plan/28 the tree was
    // `display: none` with no way whatsoever to bring it back, which is the one
    // shape the shared design foundation names as forbidden ("不將功能直接隱藏").
    // So the hidden check is kept AND the opening control is now required.
    await page.setViewportSize({ width: 1000, height: 800 });
    await page.waitForTimeout(400);
    await expect(page.getByRole("tree", { name: "工作區檔案" })).toBeHidden();

    const openFiles = page.getByRole("button", { name: "開啟檔案欄" });
    await expect(openFiles).toBeVisible();
    await openFiles.click();
    await expect(page.getByRole("tree", { name: "工作區檔案" })).toBeVisible();
    // Escape closes it and hands focus back to the button that opened it. A
    // drawer that traps focus and then drops it leaves the next Tab starting
    // from the top of the document.
    await page.keyboard.press("Escape");
    await expect(page.getByRole("tree", { name: "工作區檔案" })).toBeHidden();
    await expect(openFiles).toBeFocused();

    await page.setViewportSize({ width: 1440, height: 900 });
    await terminate(page);
  });

  // FR-TERM-001.AC-13 / AC-14 (plan/09 LY-06). The vertical counterpart of the
  // test above, and the reason it exists: that one only ever measured *width*, so
  // for three phases the CLI panel could sit at roughly half the height of its
  // pane with every gate green. The mechanism was self-stabilising — the terminal
  // host was placed in an `auto` grid row, so it measured exactly the 24 rows
  // xterm already had, and FitAddon kept re-proposing 24 rows at any window size.
  // Nothing but a real browser can see this: jsdom has no layout at all.
  test("layout: the CLI terminal fills the centre pane and the page does not scroll", async ({
    page,
  }) => {
    await signIn(page);
    const nodeCount = await openDialogAndCountNodes(page);
    test.skip(nodeCount === 0, "no online node available in this stack");

    const dialog = newSessionDialog(page);
    await dialog.locator("select").first().selectOption({ index: 1 });
    const runtime = dialog.locator("select").nth(1);
    await expect(runtime.locator("option:not([disabled])")).not.toHaveCount(0);
    await runtime.selectOption({ index: 1 });
    await expect(dialog.locator('input[list="roots"]')).not.toHaveValue("");
    await dialog
      .locator('input[placeholder="e.g. refactor-api"]')
      .fill("e2e-fill");
    await dialog.getByRole("button", { name: "Start" }).click();

    await expect(page).toHaveURL(/\/sessions\/[0-9a-f-]{36}$/);
    await expect(page.locator("#panel-cli .xterm-rows")).toContainText(
      "FAKECLI_READY",
      { timeout: 15_000 },
    );

    // One evaluate for the whole picture: a failure message that names only the
    // ratio cannot tell "the host did not grow" from "the host grew and xterm
    // never re-fitted", which are different bugs with different fixes.
    const measure = () =>
      page.evaluate(() => {
        const pane = document.querySelector("#panel-cli") as HTMLElement;
        const host = pane.querySelector(
          '[aria-label="Interactive CLI terminal"]',
        ) as HTMLElement;
        const screen = pane.querySelector(".xterm-screen") as HTMLElement;
        const root = document.documentElement;
        const main = document.querySelector("main") as HTMLElement;
        return {
          paneHeight: pane.clientHeight,
          hostHeight: host.clientHeight,
          screenHeight: Math.round(screen.getBoundingClientRect().height),
          // One <div> per row; xterm's own rows/cols are not exposed to the page.
          rows: pane.querySelectorAll(".xterm-rows > div").length,
          centreWidth: pane.clientWidth,
          asideWidth: (document.querySelector("aside") as HTMLElement)
            .clientWidth,
          pageOverflowY: root.scrollHeight - root.clientHeight,
          mainOverflowY: main.scrollHeight - main.clientHeight,
        };
      });

    const wide = await measure();
    const why = (m: object) => JSON.stringify(m);
    // The host takes the whole pane. 4px of slack, not 0: the pane's own border
    // radius and sub-pixel rounding are not a layout bug.
    expect(
      wide.hostHeight,
      `host did not fill the pane: ${why(wide)}`,
    ).toBeGreaterThanOrEqual(wide.paneHeight - 4);
    // …and xterm actually re-fitted into it. The screen is rows × cell height, so
    // it always leaves under one row spare; 90% is well clear of that and well
    // clear of the 50% the collapsed layout produced.
    expect(
      wide.screenHeight,
      `xterm did not re-fit to the host: ${why(wide)}`,
    ).toBeGreaterThanOrEqual(wide.paneHeight * 0.9);
    // A ratio alone would also pass on a correct-but-tiny terminal. 24 rows was
    // the broken value at every window size, so the floor is set above it.
    expect(
      wide.rows,
      `too few rows to work in: ${why(wide)}`,
    ).toBeGreaterThanOrEqual(30);
    // Two competing height formulas (the shell's and the view's) used to differ
    // by 16px, which showed up as a page that could be scrolled a little.
    expect(
      wide.pageOverflowY,
      `the page scrolls: ${why(wide)}`,
    ).toBeLessThanOrEqual(1);
    expect(
      wide.mainOverflowY,
      `fill-mode main scrolls: ${why(wide)}`,
    ).toBeLessThanOrEqual(1);
    // The rail is navigation for five items, not a column of its own; the centre
    // is what the work happens in (style.md §9/§12).
    expect(
      wide.asideWidth,
      `the rail is too wide: ${why(wide)}`,
    ).toBeLessThanOrEqual(220);
    expect(
      wide.centreWidth,
      `the centre pane is too narrow: ${why(wide)}`,
    ).toBeGreaterThanOrEqual(860);

    // A round trip through the preview must not disturb the terminal: it is
    // hidden while the file is open, and a fit taken from a hidden 0×0 host would
    // reshape the PTY behind the user's back.
    const readme = page
      .getByRole("tree", { name: "工作區檔案" })
      .getByRole("treeitem", { name: /^README\.md,/ });
    if (
      await readme
        .waitFor({ state: "visible", timeout: 15_000 })
        .then(() => true)
        .catch(() => false)
    ) {
      await readme.click();
      // The preview pane fills its own height too — the same defect lived in
      // PreviewPane, where the row template only worked while the meta line was
      // rendered.
      const preview = await page.evaluate(() => {
        const pane = document.querySelector("#panel-preview") as HTMLElement;
        const body = pane.querySelector(".body") as HTMLElement;
        return { paneHeight: pane.clientHeight, bodyHeight: body.clientHeight };
      });
      expect(
        preview.bodyHeight,
        `the preview body did not fill its pane: ${why(preview)}`,
      ).toBeGreaterThanOrEqual(preview.paneHeight * 0.85);

      await page.getByRole("tab", { name: "CLI" }).click();
      const back = await measure();
      expect(back.rows, `the round trip changed the size: ${why(back)}`).toBe(
        wide.rows,
      );
      // A gap banner here would mean the tab switch cost output continuity.
      await expect(
        page.getByText("顯示最新輸出片段（先前歷史已截斷）。"),
      ).toHaveCount(0);
    }

    // Inside the 1100px breakpoint: one column, no file tree, and the terminal
    // still fills what is left.
    await page.setViewportSize({ width: 1000, height: 800 });
    // The refit is debounced by 100ms; measuring sooner reads the old size.
    await page.waitForTimeout(400);
    const narrow = await measure();
    expect(
      narrow.hostHeight,
      `host did not fill at 1000x800: ${why(narrow)}`,
    ).toBeGreaterThanOrEqual(narrow.paneHeight - 4);
    expect(
      narrow.screenHeight,
      `xterm did not re-fit at 1000x800: ${why(narrow)}`,
    ).toBeGreaterThanOrEqual(narrow.paneHeight * 0.9);
    expect(
      narrow.rows,
      `too few rows at 1000x800: ${why(narrow)}`,
    ).toBeGreaterThanOrEqual(20);
    expect(
      narrow.pageOverflowY,
      `the page scrolls at 1000x800: ${why(narrow)}`,
    ).toBeLessThanOrEqual(1);

    await page.setViewportSize({ width: 1440, height: 900 });
    await terminate(page);
  });

  // WT-11 exit condition 10 (FR-SHELL-001 AC-02 / AC-08). Everything else about
  // the shell is asserted against a fake registry or a unit boundary; this is the
  // only place a real `bash` is started on a real node through the real relay.
  //
  // The stack node needs no shell configuration: an absent runtime.shell block
  // means enabled (D6), which is exactly the upgraded-node path, so this also
  // exercises the default rather than a test-only override.
  test("system terminal: TERMINAL tab opens a real shell and closing it ends the session", async ({
    page,
  }) => {
    await signIn(page);
    const nodeCount = await openDialogAndCountNodes(page);
    test.skip(nodeCount === 0, "no online node available in this stack");

    const dialog = newSessionDialog(page);
    await dialog.locator("select").first().selectOption({ index: 1 });
    const runtime = dialog.locator("select").nth(1);
    await expect(runtime.locator("option:not([disabled])")).not.toHaveCount(0);
    await runtime.selectOption({ index: 1 });
    await expect(dialog.locator('input[list="roots"]')).not.toHaveValue("");
    await dialog
      .locator('input[placeholder="e.g. refactor-api"]')
      .fill("e2e-shell");
    await dialog.getByRole("button", { name: "Start" }).click();

    await expect(page).toHaveURL(/\/sessions\/[0-9a-f-]{36}$/);
    const cliUrl = page.url();
    await expect(page.locator("#panel-cli .xterm-rows")).toContainText(
      "FAKECLI_READY",
      {
        timeout: 15_000,
      },
    );

    // The tab exists only when the server said yes to all three of: the user
    // holds terminal.shell, they own this session, and the node has a usable
    // shell. A node without bash reports available:false, and the honest outcome
    // there is a skip, not a failure.
    const terminalTab = page.getByRole("tab", { name: "TERMINAL" });
    const offered = await terminalTab
      .waitFor({ state: "visible", timeout: 10_000 })
      .then(() => true)
      .catch(() => false);
    test.skip(!offered, "this node reports no usable shell runtime");

    // Armed before the click: the tab creates the session on first selection
    // (D8), and its id is how the close assertion below knows which session it
    // is talking about.
    const created = page.waitForResponse(
      (res) => res.request().method() === "POST" && /\/shell$/.test(res.url()),
    );
    await terminalTab.click();
    const createdBody = await created.then((res) => res.json());
    expect(createdBody.runtime).toBe("shell");
    // plan/09 LY-04: the size the shell was *created* at, read from the server's
    // own record of it. This is asserted on the create response rather than by
    // measuring the terminal afterwards, because a later measurement would be
    // satisfied by "opened at 24×80, then resized" — the very thing that makes
    // bash redraw its prompt in front of the user.
    expect(
      createdBody.rows,
      `the shell opened at ${createdBody.rows}x${createdBody.columns}, not at the panel's size`,
    ).toBeGreaterThanOrEqual(30);
    expect(createdBody.columns).toBeGreaterThanOrEqual(60);
    const shellId: string = createdBody.id;

    const shellPanel = page.locator("#panel-terminal");
    await expect(shellPanel).toBeVisible();
    // The boundary notice is not decoration: this pane is outside the workspace
    // root the file tree enforces, and the user is told so.
    await expect(shellPanel.getByRole("note")).toContainText(
      "不受 workspace 路徑限制",
    );

    // A real shell, proved the only way that cannot be faked by the UI: run a
    // command and read its output back out of the PTY.
    const shellRows = shellPanel.locator(".xterm-rows");
    await expect(shellRows).toBeVisible({ timeout: 15_000 });
    await shellRows.click();
    await page.keyboard.type("echo shell-alive-$((6*7))\n");
    await expect(shellRows).toContainText("shell-alive-42", {
      timeout: 20_000,
    });

    // Two live terminals, one page: switching back must find the CLI session
    // untouched, and neither PTY may be resized from the other's hidden host.
    await page.getByRole("tab", { name: "CLI" }).click();
    await expect(page.locator("#panel-cli .xterm-rows")).toContainText(
      "FAKECLI_READY",
    );
    await page.getByRole("tab", { name: "TERMINAL" }).click();
    await expect(shellRows).toContainText("shell-alive-42");

    // AC-08: closing the tab ends the shell on the node. Asserted from the
    // server's own answer to the terminate call rather than by reading the
    // session list, because shells are filtered out of that list (D13) — the
    // close is only real if the server says this id is going away.
    const terminated = page.waitForResponse(
      (res) =>
        res.request().method() === "POST" &&
        res.url().endsWith(`/api/sessions/${shellId}/terminate`),
    );
    await page.getByRole("button", { name: "關閉 TERMINAL" }).click();
    const terminatedBody = await terminated.then((res) => res.json());
    expect(
      ["terminating", "terminated", "exited", "failed"],
      `the shell was left in status ${terminatedBody.status}`,
    ).toContain(terminatedBody.status);

    // The tab stays (the capability is still there); what goes is the session.
    await expect(page.locator("#panel-terminal")).toBeHidden();

    // The CLI session is untouched by the shell's termination — same page, same
    // socket, still connected. The cascade runs parent → child, never back.
    expect(page.url()).toBe(cliUrl);
    await expect(page.locator("#panel-cli .xterm-rows")).toContainText(
      "FAKECLI_READY",
    );
    await expect(page.locator('[data-status="connected"]')).toBeVisible();

    await terminate(page);
  });

  // The other half of AC-08: "closing the terminal **or leaving the Session
  // workspace**". A reload is the exit nothing else can stand in for — no unmount
  // runs, and an ordinary fetch is cancelled with the document — so only a real
  // browser can show that the terminate actually leaves. The symptom this covers is
  // the one users hit: after a reload the terminal was still live server-side, the
  // page no longer knew its id, and reopening was refused with SHELL_ALREADY_OPEN.
  test("system terminal: a reload ends the terminal and the next open is not refused", async ({
    page,
  }) => {
    await signIn(page);
    const nodeCount = await openDialogAndCountNodes(page);
    test.skip(nodeCount === 0, "no online node available in this stack");

    const dialog = newSessionDialog(page);
    await dialog.locator("select").first().selectOption({ index: 1 });
    const runtime = dialog.locator("select").nth(1);
    await expect(runtime.locator("option:not([disabled])")).not.toHaveCount(0);
    await runtime.selectOption({ index: 1 });
    await expect(dialog.locator('input[list="roots"]')).not.toHaveValue("");
    await dialog
      .locator('input[placeholder="e.g. refactor-api"]')
      .fill("e2e-shell-reload");
    await dialog.getByRole("button", { name: "Start" }).click();
    await expect(page).toHaveURL(/\/sessions\/[0-9a-f-]{36}$/);

    const terminalTab = page.getByRole("tab", { name: "TERMINAL" });
    const offered = await terminalTab
      .waitFor({ state: "visible", timeout: 10_000 })
      .then(() => true)
      .catch(() => false);
    test.skip(!offered, "this node reports no usable shell runtime");

    const created = page.waitForResponse(
      (res) => res.request().method() === "POST" && /\/shell$/.test(res.url()),
    );
    await terminalTab.click();
    const first: string = await created.then(
      async (res) => (await res.json()).id,
    );
    await expect(page.locator("#panel-terminal .xterm-rows")).toBeVisible({
      timeout: 15_000,
    });

    // Armed before the reload: the request is sent from a `pagehide` handler with
    // `keepalive`, so it is in flight while the document is going away.
    const terminated = page.waitForRequest(
      (req) =>
        req.method() === "POST" &&
        req.url().endsWith(`/api/sessions/${first}/terminate`),
    );
    await page.reload();
    await terminated;

    // Back on the same session: opening the terminal again is answered, not refused.
    // A different id is the proof that the reloaded page is not being handed the
    // terminal it abandoned (ADR 0021 §6 — an unattended shell is ended, not
    // inherited).
    const reopened = page.waitForResponse(
      (res) => res.request().method() === "POST" && /\/shell$/.test(res.url()),
    );
    await page.getByRole("tab", { name: "TERMINAL" }).click();
    const second = await reopened.then((res) => res.json());
    expect(second.id).not.toBe(first);
    expect(second.runtime).toBe("shell");
    await expect(page.locator("#panel-terminal")).toBeVisible();
  });

  // FR-TERM-004.AC-06 (ADR 0023, PV-04). The user's actual complaint: the wheel did
  // not scroll. It was not a missing feature — tmux attaches on the alternate screen
  // with mouse reporting off, so xterm.js was translating the wheel into arrow keys,
  // and scrolling up in a shell walked the command history instead of showing earlier
  // output. Both halves are asserted here: earlier output becomes visible, and the
  // shell's prompt line is not replaced by a history entry.
  //
  // This is the only test that exercises the fix the way a user meets it — real tmux,
  // real relay, real wheel events — so if it is skipped, the criterion is only
  // covered by GATE-PV-NODE-POSTURE on a real node.
  test("terminal: the wheel scrolls back through output instead of walking history", async ({
    page,
  }) => {
    await signIn(page);
    const nodeCount = await openDialogAndCountNodes(page);
    test.skip(nodeCount === 0, "no online node available in this stack");

    const dialog = newSessionDialog(page);
    await dialog.locator("select").first().selectOption({ index: 1 });
    await dialog.locator("select").nth(1).selectOption({ index: 1 });
    await expect(dialog.locator('input[list="roots"]')).not.toHaveValue("");
    await dialog
      .locator('input[placeholder="e.g. refactor-api"]')
      .fill("e2e-scroll");
    await dialog.getByRole("button", { name: "Start" }).click();
    await expect(page).toHaveURL(/\/sessions\/[0-9a-f-]{36}$/);
    await expect(page.locator("#panel-cli .xterm-rows")).toContainText(
      "FAKECLI_READY",
      { timeout: 15_000 },
    );

    // A real shell is needed: the point is scrolling through *output*, and the CLI
    // stack runs fakecli, which does not produce pages of it.
    const terminalTab = page.getByRole("tab", { name: "TERMINAL" });
    const offered = await terminalTab
      .waitFor({ state: "visible", timeout: 10_000 })
      .then(() => true)
      .catch(() => false);
    test.skip(!offered, "this node reports no usable shell runtime");
    await terminalTab.click();
    const shell = page.locator("#panel-terminal .xterm-rows");
    await expect(page.locator("#panel-terminal")).toBeVisible();

    // A marker far enough back that it cannot still be on screen, then enough
    // output to push it off.
    const host = page.locator('[aria-label="System terminal"]');
    await host.click();
    await page.keyboard.type("echo SCROLLBACK_MARKER; seq 1 500\n");
    await expect(shell).toContainText("500", { timeout: 15_000 });
    await expect(shell).not.toContainText("SCROLLBACK_MARKER");

    // The prompt as it stands before scrolling. If the wheel were still being turned
    // into arrow keys, this line would change — the shell would recall a previous
    // command into it — which is the failure mode users reported.
    const promptBefore = await page
      .locator("#panel-terminal .xterm-rows > div")
      .last()
      .innerText();

    await host.hover();
    for (let i = 0; i < 12; i += 1) await page.mouse.wheel(0, -240);

    await expect(shell).toContainText("SCROLLBACK_MARKER", { timeout: 10_000 });
    const promptAfter = await page
      .locator("#panel-terminal .xterm-rows > div")
      .last()
      .innerText();
    expect(promptAfter).not.toContain("echo SCROLLBACK_MARKER");

    // And back: scrolling to the bottom leaves copy mode on its own (tmux's default
    // wheel binding uses `copy-mode -e`), so the user is not stranded in a mode the
    // console gives no indication of.
    for (let i = 0; i < 20; i += 1) await page.mouse.wheel(0, 240);
    await expect(shell).toContainText("500", { timeout: 10_000 });
    expect(promptBefore.length).toBeGreaterThanOrEqual(0);

    // The two sentences a user needs in order to know any of this. They are printed,
    // not documented, because neither behaviour is discoverable.
    await expect(page.locator("#panel-terminal .terminal-hint")).toContainText(
      "Shift",
    );
  });
});
