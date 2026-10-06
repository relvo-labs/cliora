import { expect, test, type Page } from "@playwright/test";

// Real xterm + FitAddon + #129 settling, mocked Central and WebSocket. The
// injected visualViewport models a keyboard independently of the layout
// viewport. This is emulation; only an iPhone can verify Safari's event timing.
const ID = "44444444-4444-4444-8444-444444444444";
const SHELL = "55555555-5555-4555-8555-555555555555";
const NODE = "11111111-1111-1111-1111-111111111111";

test.use({ viewport: { width: 390, height: 664 } });

async function viewportHeight(page: Page, height: number) {
  await page.evaluate((height) => {
    const viewport = window.visualViewport!;
    Object.defineProperty(viewport, "height", {
      configurable: true,
      value: height,
    });
    viewport.dispatchEvent(new Event("resize"));
    viewport.dispatchEvent(new Event("scroll"));
  }, height);
}

for (const { terminal, delayedFocus } of [
  { terminal: "cli", delayedFocus: false },
  { terminal: "terminal", delayedFocus: false },
  { terminal: "cli", delayedFocus: true },
  { terminal: "unavailable", delayedFocus: false },
] as const) {
  const behavior =
    terminal === "unavailable"
      ? "node without shell has no menu item"
      : delayedFocus
        ? "focusin without viewport events sends only settled sizes"
        : "keyboard keeps >=8 rows, one settled resize per open/close";
  test(`${terminal}: ${behavior}`, async ({ page, context }) => {
    const resizes: Array<{
      rows: number;
      columns: number;
      session_id: string;
    }> = [];
    let connections = 0;
    let attaches = 0;
    const terminations: string[] = [];
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.addInitScript(() => {
      localStorage.setItem("cliora.access_token", "mock-access");
      localStorage.setItem("cliora.refresh_token", "mock-refresh");
      const viewport = new EventTarget();
      Object.defineProperties(viewport, {
        height: { configurable: true, value: 664 },
        scale: { value: 1 },
      });
      Object.defineProperty(window, "visualViewport", { value: viewport });
    });
    const session = {
      id: ID,
      node_id: NODE,
      user_id: "u",
      name: "keyboard-proof",
      runtime: "claude",
      workspace: "/srv/mock",
      status: "running",
      rows: 18,
      columns: 40,
      started_at: "2026-10-04T00:00:00Z",
      last_activity_at: "2026-10-04T00:00:00Z",
      capabilities: {
        can_view: true,
        can_write: true,
        can_browse_files: true,
        can_upload_files: true,
        can_open_shell: true,
        can_terminate: true,
      },
    };
    await page.route(
      (url) => url.pathname.startsWith("/api/"),
      async (route) => {
        const path = new URL(route.request().url()).pathname;
        let body: unknown;
        if (path === "/api/auth/me") {
          body = {
            id: "u",
            username: "mock",
            display_name: "Mock",
            role: "Admin",
            permissions: ["session.view", "file.browse", "terminal.shell"],
          };
        } else if (path === `/api/sessions/${ID}`) body = session;
        else if (path === `/api/nodes/${NODE}`)
          body = {
            id: NODE,
            name: "Mock",
            image_upload: true,
            runtimes:
              terminal === "unavailable"
                ? []
                : [
                    {
                      runtime: "shell",
                      available: true,
                      version: null,
                      binary_path: null,
                      checked_at: "2026-10-04T00:00:00Z",
                      sandbox_bypass: false,
                    },
                  ],
            workspace_roots: [],
          };
        else if (path.endsWith("/attach")) {
          attaches++;
          body = { ticket: "mock-ticket" };
        } else if (path.endsWith("/shell"))
          body = { ...session, id: SHELL, runtime: "shell" };
        else if (path.endsWith("/terminate")) {
          terminations.push(path);
          body = {};
        } else if (path.endsWith("/files/tree"))
          body = {
            path: ".",
            truncated: false,
            entries: [
              {
                name: "readme.txt",
                rel_path: "readme.txt",
                type: "file",
                size: 5,
                modified_at: "2026-10-04T00:00:00Z",
                expandable: false,
                hidden: false,
                symlink: false,
                excluded: false,
              },
            ],
          };
        else if (path.endsWith("/files/content"))
          body = {
            success: true,
            rel_path: "readme.txt",
            content: "hello",
            size: 5,
            encoding: "utf-8",
          };
        else body = {};
        await route.fulfill({ json: body });
      },
    );
    await context.routeWebSocket("**/ws/sessions/*/terminal?*", (socket) => {
      connections++;
      socket.send(
        JSON.stringify({ type: "terminal.role", payload: { role: "writer" } }),
      );
      socket.onMessage((data) => {
        if (typeof data !== "string") return;
        const message = JSON.parse(data);
        if (message.type === "terminal.resize") resizes.push(message.payload);
      });
    });
    await page.goto(`/sessions/${ID}`);
    await expect(page.locator(".status-bar")).toContainText("已連線");
    // The keyboard-closed geometry must still match NewSessionDialog's probe.
    const mainBox = await page.locator("#main").boundingBox();
    const cliBox = await page
      .locator("#panel-cli .terminal-host")
      .boundingBox();
    expect(mainBox!.height - cliBox!.height).toBe(252);
    expect(mainBox!.width - cliBox!.width).toBe(34);
    if (terminal === "unavailable") {
      await page
        .getByRole("button", { name: "Session 操作", exact: true })
        .click();
      await expect(
        page.getByRole("menuitem", { name: "開啟系統 shell", exact: true }),
      ).toHaveCount(0);
      await expect(page.locator("#tab-terminal")).toHaveCount(0);
      expect(connections).toBe(1);
      expect(attaches).toBe(1);
      expect(errors).toEqual([]);
      return;
    }
    if (terminal === "terminal") {
      await page
        .getByRole("button", { name: "Session 操作", exact: true })
        .click();
      await page
        .getByRole("menuitem", { name: "開啟系統 shell", exact: true })
        .click();
      await expect.poll(() => connections).toBe(2);
    }
    const panel = page.locator(`#panel-${terminal}`);
    const input = panel.locator("textarea");
    await input.focus();
    await expect
      .poll(
        () =>
          resizes.filter(
            (r) => r.session_id === (terminal === "cli" ? ID : SHELL),
          ).length,
      )
      .toBe(1);
    // A bounded quiet window lets the initial attach/observer settle finish.
    await page.waitForTimeout(350);
    const initial = resizes.length;
    const beforeConnections = connections;
    const beforeAttaches = attaches;
    if (delayedFocus) {
      // Reviewer repro: visualViewport changes without resize/scroll, then a
      // focusin arrives. Hold longer than #129's settle so an oversize grid
      // cannot hide as a brief intermediate layout (candidate sent 31 rows).
      const expected = [18];
      for (const deliverOpenEvent of [true, false]) {
        await input.evaluate((element) => (element as HTMLElement).blur());
        await page.evaluate(() =>
          Object.defineProperty(window.visualViewport!, "height", {
            configurable: true,
            value: 360,
          }),
        );
        await input.focus();
        await page.waitForTimeout(350);
        expected.push(15);
        expect(resizes.map((size) => size.rows)).toEqual(expected);
        await expect(page.locator(".shell")).toHaveAttribute(
          "data-keyboard-collapsed",
          "",
        );
        expect(
          await page.evaluate(() =>
            document.documentElement.style.getPropertyValue(
              "--viewport-usable-height",
            ),
          ),
        ).toBe("360px");
        if (deliverOpenEvent) {
          await viewportHeight(page, 360);
          await page.waitForTimeout(350);
          expect(resizes.map((size) => size.rows)).toEqual(expected);
        }
        await viewportHeight(page, 664);
        await page.waitForTimeout(350);
        expected.push(18);
        expect(resizes.map((size) => size.rows)).toEqual(expected);
      }
      expect(connections).toBe(beforeConnections);
      expect(attaches).toBe(beforeAttaches);
      expect(errors).toEqual([]);
      console.log(
        JSON.stringify({
          terminal,
          delayedFocus,
          rows: expected,
          connections,
          attaches,
        }),
      );
      return;
    }
    await panel.locator(".xterm").evaluate((element) => {
      element.setAttribute("data-original", "true");
    });
    await viewportHeight(page, 510);
    await page.waitForTimeout(120);
    await viewportHeight(page, 410);
    await page.waitForTimeout(120);
    await viewportHeight(page, 360);
    await expect.poll(() => resizes.length).toBe(initial + 1);
    expect(resizes.at(-1)!.rows).toBeGreaterThanOrEqual(8);
    const openRows = resizes.at(-1)!.rows;
    await expect(page.locator(".shell > header")).toBeHidden();
    await expect(page.locator(".workspace > .head")).toBeHidden();
    await expect(
      page.getByRole("tab", { name: "檔案", exact: true }),
    ).toHaveCount(0);
    await expect(page.locator(".drop-bar")).toBeHidden();
    await expect(page.locator(".status-bar")).toBeHidden();
    await expect(input).toBeFocused();
    if (terminal === "terminal")
      await expect(panel.locator(".shell-notice")).toBeVisible();
    await expect(
      page.getByRole("button", { name: "收起鍵盤", exact: true }),
    ).toBeVisible();
    await page.getByRole("button", { name: "收起鍵盤", exact: true }).click();
    await expect(input).not.toBeFocused();
    await expect(page.locator(`#tab-${terminal}`)).toBeFocused();
    await expect(page.locator(".shell > header")).toBeHidden();
    await viewportHeight(page, 410);
    await page.waitForTimeout(120);
    await viewportHeight(page, 510);
    await page.waitForTimeout(120);
    await viewportHeight(page, 664);
    await expect.poll(() => resizes.length).toBe(initial + 2);
    await page.waitForTimeout(350);
    expect(resizes).toHaveLength(initial + 2);
    console.log(
      JSON.stringify({
        terminal,
        openRows,
        closeRows: resizes.at(-1)!.rows,
        keyboardResizes: resizes.slice(initial),
        connections,
        attaches,
      }),
    );
    expect(connections).toBe(beforeConnections);
    expect(attaches).toBe(beforeAttaches);
    await expect(panel.locator('.xterm[data-original="true"]')).toHaveCount(1);
    await expect(page.locator(".shell > header")).toBeVisible();
    await expect(
      page.getByRole("tab", { name: "檔案", exact: true }),
    ).toBeVisible();
    if (terminal === "terminal") {
      await page
        .getByRole("button", { name: "關閉並終止系統 shell", exact: true })
        .click();
      await expect(page.locator("#tab-cli")).toBeFocused();
      await expect(page.locator("#panel-cli textarea")).not.toBeFocused();
      await expect(page.locator("#tab-terminal")).toHaveCount(0);
      await expect(page.locator(".shell-announcement")).toContainText(
        "已關閉並終止",
      );
      expect(terminations).toEqual([`/api/sessions/${SHELL}/terminate`]);
      expect(attaches).toBe(beforeAttaches);
    }
    await page.getByRole("tab", { name: "檔案", exact: true }).click();
    await page.getByRole("button", { name: /readme.txt/ }).click();
    await expect(page.locator("#panel-preview")).toBeVisible();
    // Read-only preview survives a viewport cycle without being reconstructed.
    await expect(page.locator(".monaco-editor")).toBeVisible();
    await page
      .locator(".monaco-editor")
      .evaluate((element) => element.setAttribute("data-original", "true"));
    await viewportHeight(page, 360);
    await expect(page.locator(".shell > header")).toBeVisible();
    await viewportHeight(page, 664);
    await expect(
      page.locator('.monaco-editor[data-original="true"]'),
    ).toHaveCount(1);
    expect(errors).toEqual([]);
  });
}
