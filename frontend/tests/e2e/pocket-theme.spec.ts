import { expect, test } from "@playwright/test";

import { mockCentral, openFile, SESSION_ID } from "./binary-preview.harness";

// Real xterm and Monaco in a browser, with only Central and the relay replaced
// by local fixtures. CSS tokens alone cannot catch a stale renderer palette.
test("the phone paints pocket in xterm and Monaco, then repaints in place at desktop width", async ({
  page,
  context,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await context.addInitScript(() => {
    localStorage.setItem("cliora-theme", "graphite");
  });
  await mockCentral(context, [
    {
      name: "note.txt",
      path: "note.txt",
      answer: { status: 404, code: "NOT_USED" },
    },
  ]);
  await context.route(`**/api/sessions/${SESSION_ID}/attach`, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ ticket: "local-ticket" }),
    }),
  );
  await context.route(
    `**/api/sessions/${SESSION_ID}/files/content?*`,
    (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          success: true,
          rel_path: "note.txt",
          size: 12,
          encoding: "utf-8",
          language_hint: "plaintext",
          content: "Pocket theme",
        }),
      }),
  );
  let sockets = 0;
  await context.routeWebSocket(
    `**/ws/sessions/${SESSION_ID}/terminal?*`,
    (ws) => {
      sockets += 1;
      ws.send(
        JSON.stringify({ type: "terminal.role", payload: { role: "writer" } }),
      );
    },
  );

  await page.goto(`/sessions/${SESSION_ID}`);
  const viewport = page.locator("#panel-cli .xterm-viewport");
  const screen = page.locator("#panel-cli .xterm-screen");
  await expect(viewport).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "pocket");
  await expect
    .poll(() => viewport.evaluate((el) => getComputedStyle(el).backgroundColor))
    .toBe("rgb(255, 255, 255)");
  const originalScreen = await screen.elementHandle();
  await expect.poll(() => sockets).toBe(1);

  await page.getByRole("tab", { name: "檔案" }).click();
  await openFile(page, "note.txt", true);
  const editor = page.locator("#panel-preview .monaco-editor");
  await expect(page.locator("#panel-preview .view-lines")).toContainText(
    "Pocket theme",
  );
  await expect
    .poll(() => editor.evaluate((el) => getComputedStyle(el).backgroundColor))
    .toBe("rgb(255, 255, 255)");
  const originalEditor = await editor.elementHandle();

  // Simulate a choice changed in another tab: pocket remains painted here.
  await page.evaluate(() => {
    localStorage.setItem("cliora-theme", "porcelain");
    window.dispatchEvent(new StorageEvent("storage", { key: "cliora-theme" }));
  });
  await expect(page.locator("html")).toHaveAttribute("data-theme", "pocket");
  await expect
    .poll(() => viewport.evaluate((el) => getComputedStyle(el).backgroundColor))
    .toBe("rgb(255, 255, 255)");
  await expect
    .poll(() => editor.evaluate((el) => getComputedStyle(el).backgroundColor))
    .toBe("rgb(255, 255, 255)");

  await page.setViewportSize({ width: 1440, height: 900 });
  await expect(page.locator("html")).toHaveAttribute("data-theme", "porcelain");
  await expect
    .poll(() => viewport.evaluate((el) => getComputedStyle(el).backgroundColor))
    .toBe("rgb(16, 20, 22)");
  await expect
    .poll(() => editor.evaluate((el) => getComputedStyle(el).backgroundColor))
    .toBe("rgb(16, 20, 22)");
  expect(
    await originalScreen?.evaluate(
      (el) =>
        el.isConnected &&
        el === document.querySelector("#panel-cli .xterm-screen"),
    ),
  ).toBe(true);
  expect(
    await originalEditor?.evaluate(
      (el) =>
        el.isConnected &&
        el === document.querySelector("#panel-preview .monaco-editor"),
    ),
  ).toBe(true);
  expect(sockets).toBe(1);

  await page.evaluate(() => {
    localStorage.setItem("cliora-theme", "graphite");
    window.dispatchEvent(new StorageEvent("storage", { key: "cliora-theme" }));
  });
  await expect(page.locator("html")).toHaveAttribute("data-theme", "graphite");
  await expect
    .poll(() => viewport.evaluate((el) => getComputedStyle(el).backgroundColor))
    .toBe("rgb(16, 20, 22)");
  await expect
    .poll(() => editor.evaluate((el) => getComputedStyle(el).backgroundColor))
    .toBe("rgb(16, 20, 22)");
  expect(sockets).toBe(1);

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.locator("html")).toHaveAttribute("data-theme", "pocket");
  await expect
    .poll(() => viewport.evaluate((el) => getComputedStyle(el).backgroundColor))
    .toBe("rgb(255, 255, 255)");
  await expect
    .poll(() => editor.evaluate((el) => getComputedStyle(el).backgroundColor))
    .toBe("rgb(255, 255, 255)");
  expect(sockets).toBe(1);
});
