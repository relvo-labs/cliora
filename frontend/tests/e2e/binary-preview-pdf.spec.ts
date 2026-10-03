import { expect, test, type Page, type Worker } from "@playwright/test";

import {
  cspViolations,
  generateFixtures,
  mockCentral,
  openFile,
  openWorkspace,
  type Fixtures,
  type PreviewFile,
} from "./binary-preview.harness";

// PDFs in the read-only binary preview (plan/31/05 BP-07 §4), in a real
// browser under the production CSP string. The stand-in Central hands the
// bytes over exactly as the real one does (octet-stream, the preview headers);
// what is under test is PDF.js and the console around it. Fixtures come from
// scripts/p31/gen_preview_fixtures.py.

let fx: Fixtures;
test.beforeAll(() => {
  fx = generateFixtures();
});
test.afterAll(() => fx?.cleanup());

const shotDir = process.env.E2E_SHOT_DIR;
async function shot(page: Page, name: string): Promise<void> {
  if (shotDir) await page.screenshot({ path: `${shotDir}/${name}.png` });
}

function pdfFile(name: string, fixture = name): PreviewFile {
  return {
    name,
    path: name,
    answer: { mime: "application/pdf", kind: "pdf", bytes: fx.read(fixture) },
  };
}

const PASSWORD = [
  "password-rc4-40.pdf",
  "password-aes-128.pdf",
  "password-aes-256.pdf",
];
const PERMISSIONS = [
  "permissions-rc4-40.pdf",
  "permissions-aes-128.pdf",
  "permissions-aes-256.pdf",
];

function allPdfs(): PreviewFile[] {
  return [
    "ok.pdf",
    "ok-cjk.pdf",
    "ok-jpx.pdf",
    "active.pdf",
    "cve-2024-4367-shape.pdf",
    "broken-xref.pdf",
    "pages-200.pdf",
    "pages-201.pdf",
    ...PASSWORD,
    ...PERMISSIONS,
  ].map((name) => pdfFile(name));
}

const visibleCanvas = (page: Page) => page.locator("canvas[role=img]:visible");

/** Wait until the visible page canvas has something other than paper on it. */
async function waitForPaint(page: Page): Promise<void> {
  await expect(visibleCanvas(page)).toHaveCount(1, { timeout: 15_000 });
  await expect
    .poll(
      () =>
        page.evaluate(() => {
          const canvas = [
            ...document.querySelectorAll<HTMLCanvasElement>("canvas[role=img]"),
          ].find((c) => c.offsetParent !== null);
          if (!canvas || !canvas.width) return false;
          const data = canvas
            .getContext("2d")!
            .getImageData(0, 0, canvas.width, canvas.height).data;
          for (let i = 0; i < data.length; i += 4 * 97) {
            if (
              data[i + 3] > 0 &&
              (data[i] < 200 || data[i + 1] < 200 || data[i + 2] < 200)
            )
              return true;
          }
          return false;
        }),
      { timeout: 15_000 },
    )
    .toBe(true);
}

/** Wait until PDF.js reports the visible page finished (whatever it drew). */
async function waitForRendered(page: Page): Promise<void> {
  await expect(
    page.locator("canvas[role=img][data-rendered]:visible"),
  ).toHaveCount(1, {
    timeout: 15_000,
  });
}

// Every PDF.js worker the page starts, so a case can prove it was terminated.
function watchWorkers(page: Page): Worker[] {
  const seen: Worker[] = [];
  page.on("worker", (worker) => {
    if (worker.url().includes("pdf.worker")) seen.push(worker);
  });
  return seen;
}

async function workerClosed(worker: Worker): Promise<void> {
  await new Promise<void>((resolve) => {
    worker.once("close", () => resolve());
    // Already gone: `evaluate` on a closed worker rejects.
    worker.evaluate(() => 1).catch(() => resolve());
  });
}

for (const size of [
  { width: 390, height: 844 },
  { width: 1440, height: 900 },
]) {
  const narrow = size.width < 768;
  test.describe(`PDF at ${size.width}x${size.height}`, () => {
    test.beforeEach(async ({ page }) => {
      await page.setViewportSize(size);
    });

    if (narrow) {
      test("phone page-number input uses at least 16px text", async ({
        page,
        context,
      }) => {
        await mockCentral(context, allPdfs());
        await openWorkspace(page, narrow);
        await openFile(page, "ok.pdf", narrow);
        const input = page.getByRole("textbox", { name: "頁碼" });
        // The field appears once PDF.js has opened the document; the same
        // 15 s budget every other PDF.js wait in this file uses.
        await expect(input).toBeVisible({ timeout: 15_000 });
        const fontSize = await input.evaluate((el) =>
          Number.parseFloat(getComputedStyle(el).fontSize),
        );
        expect(fontSize).toBeGreaterThanOrEqual(16);
      });
    }

    test("a 40-page PDF: page 1 of 40, next, jump, zoom, under the real CSP", async ({
      page,
      context,
    }) => {
      const central = await mockCentral(context, allPdfs());
      await openWorkspace(page, narrow);
      await openFile(page, "ok.pdf", narrow);
      await waitForPaint(page);
      await expect(visibleCanvas(page)).toHaveAttribute(
        "aria-label",
        "第 1／40 頁",
      );
      await expect(page.getByText("螢幕報讀器無法讀取內文")).toBeVisible();
      await shot(page, `pdf-${size.width}`);

      await page.getByRole("button", { name: "下一頁", exact: true }).click();
      await expect(visibleCanvas(page)).toHaveAttribute(
        "aria-label",
        "第 2／40 頁",
      );
      const input = page.getByRole("textbox", { name: "頁碼" });
      await input.fill("17");
      await input.press("Enter");
      await expect(visibleCanvas(page)).toHaveAttribute(
        "aria-label",
        "第 17／40 頁",
      );
      await waitForPaint(page);

      const before = (await visibleCanvas(page).boundingBox())!.width;
      await page.getByRole("button", { name: "放大", exact: true }).click();
      // The canvas is replaced while the zoomed page renders, so for a moment
      // there is no visible box; that reads as "not wider yet", not a throw.
      await expect
        .poll(async () => (await visibleCanvas(page).boundingBox())?.width ?? 0)
        .toBeGreaterThan(before);
      expect(await page.locator("canvas").count()).toBeLessThanOrEqual(3);

      // The controls are real 44 px targets, including the page field.
      for (const control of [
        page.getByRole("button", { name: "上一頁", exact: true }),
        page.getByRole("button", { name: "下一頁", exact: true }),
        page.getByRole("button", { name: "放大", exact: true }),
        input,
      ]) {
        const box = (await control.boundingBox())!;
        expect(box.height).toBeGreaterThanOrEqual(44);
      }
      const overflow = await page.evaluate(
        () =>
          document.documentElement.scrollWidth -
          document.documentElement.clientWidth,
      );
      expect(overflow).toBeLessThanOrEqual(0);
      expect(central.previewBodies).toEqual([
        JSON.stringify({ path: "ok.pdf" }),
      ]);
      expect(await cspViolations(page)).toEqual([]);
    });
  });
}

test.describe("PDF: active content, CSP and encryption", () => {
  test.beforeEach(async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
  });

  test("pdf_active_content_inert", async ({ page, context }) => {
    const central = await mockCentral(context, allPdfs());
    const dialogs: string[] = [];
    page.on("dialog", (dialog) => {
      dialogs.push(dialog.message());
      void dialog.dismiss();
    });
    let popups = 0;
    context.on("page", () => (popups += 1));
    await openWorkspace(page, false);
    const url = page.url();
    await openFile(page, "active.pdf", false);
    await waitForPaint(page);

    // Click across the whole page, links and the submit button included.
    const box = (await visibleCanvas(page).boundingBox())!;
    for (let y = 0.05; y < 1; y += 0.1) {
      for (let x = 0.1; x < 1; x += 0.2) {
        await page.mouse.click(box.x + box.width * x, box.y + box.height * y);
      }
    }
    await page.waitForTimeout(500);

    expect(page.url()).toBe(url);
    expect(popups).toBe(0);
    expect(dialogs).toEqual([]);
    expect(
      central.requests.filter((u) => u.includes("example.invalid")),
    ).toEqual([]);
    await expect(page.locator("#panel-preview a")).toHaveCount(0);
    await expect(
      page.locator(".annotationLayer, .textLayer, .xfaLayer"),
    ).toHaveCount(0);
    expect(
      await page.evaluate(
        () =>
          (window as unknown as { __cliora_pwned?: unknown }).__cliora_pwned,
      ),
    ).toBeUndefined();
    expect(await cspViolations(page)).toEqual([]);
  });

  test("no_csp_violation: a CJK PDF (CMap) and a JPX PDF (WebAssembly decoder)", async ({
    page,
    context,
  }) => {
    const central = await mockCentral(context, allPdfs());
    const consoleCsp: string[] = [];
    page.on("console", (message) => {
      if (/content security policy/i.test(message.text()))
        consoleCsp.push(message.text());
    });
    const assetStatus = new Map<string, number>();
    context.on("response", (response) => {
      if (response.url().includes("/pdfjs/"))
        assetStatus.set(new URL(response.url()).pathname, response.status());
    });
    await openWorkspace(page, false);

    await openFile(page, "ok-cjk.pdf", false);
    // Rendered, not necessarily painted: a non-embedded CID font falls back to
    // a system CJK font, and this headless browser has none, so the glyphs are
    // blank here. That they are *correct* is a device check (plan/31/08 BP-10
    // #6); what this case proves is that the CMap path works under the CSP.
    await waitForRendered(page);
    await openFile(page, "ok-jpx.pdf", false);
    await waitForPaint(page);
    await shot(page, "pdf-jpx-1440");

    // The paths under test were really taken, and they were same-origin.
    await expect
      .poll(() => assetStatus.get("/pdfjs/cmaps/UniCNS-UCS2-H.bcmap"))
      .toBe(200);
    await expect
      .poll(() => assetStatus.get("/pdfjs/wasm/openjpeg.wasm"))
      .toBe(200);
    const origins = new Set(central.requests.map((u) => new URL(u).origin));
    expect([...origins]).toEqual([new URL(page.url()).origin]);
    expect(await cspViolations(page)).toEqual([]);
    expect(consoleCsp).toEqual([]);
  });

  test("password_pdf_refused: RC4-40, AES-128, AES-256 with a user password", async ({
    page,
    context,
  }) => {
    await mockCentral(context, allPdfs());
    const workers = watchWorkers(page);
    await openWorkspace(page, false);
    for (const name of PASSWORD) {
      await openFile(page, name, false);
      await expect(
        page.getByRole("heading", {
          name: "此 PDF 需要密碼才能開啟，預覽不支援",
        }),
      ).toBeVisible({
        timeout: 15_000,
      });
      await expect(page.locator('input[type="password"]')).toHaveCount(0);
      await expect(page.locator("canvas")).toHaveCount(0);
      await expect(page.locator("#panel-preview")).not.toContainText("下載");
    }
    // Every worker PDF.js was given has been terminated.
    expect(workers.length).toBe(PASSWORD.length);
    for (const worker of workers) await workerClosed(worker);
    await shot(page, "pdf-password-1440");
  });

  test("permissions_only_pdf_renders: empty user password opens view-only, no print, copy or save", async ({
    page,
    context,
  }) => {
    await mockCentral(context, allPdfs());
    await openWorkspace(page, false);
    for (const name of PERMISSIONS) {
      await openFile(page, name, false);
      await waitForPaint(page);
      await expect(visibleCanvas(page)).toHaveAttribute(
        "aria-label",
        "第 1／1 頁",
      );
      const panel = page.locator("#panel-preview");
      for (const word of ["列印", "複製", "下載", "另存", "Print", "Save"]) {
        await expect(panel).not.toContainText(word);
      }
    }
  });

  test("cve_2024_4367_shape: script in a FontMatrix does not run", async ({
    page,
    context,
  }) => {
    await mockCentral(context, allPdfs());
    await openWorkspace(page, false);
    await openFile(page, "cve-2024-4367-shape.pdf", false);
    await waitForPaint(page);
    expect(
      await page.evaluate(
        () =>
          (window as unknown as { __cliora_pwned?: unknown }).__cliora_pwned,
      ),
    ).toBeUndefined();
    expect(await cspViolations(page)).toEqual([]);
  });

  test("the page limit: 200 pages opens, 201 is refused before a page is drawn", async ({
    page,
    context,
  }) => {
    await mockCentral(context, allPdfs());
    await openWorkspace(page, false);
    await openFile(page, "pages-200.pdf", false);
    await waitForPaint(page);
    await expect(visibleCanvas(page)).toHaveAttribute(
      "aria-label",
      "第 1／200 頁",
    );
    await openFile(page, "pages-201.pdf", false);
    await expect(
      page.getByRole("heading", { name: "PDF 頁數超過預覽上限" }),
    ).toBeVisible({ timeout: 15_000 });
    await expect(
      page.getByText("這份 PDF 有 201 頁，預覽上限為 200 頁。"),
    ).toBeVisible();
    await expect(page.locator("canvas")).toHaveCount(0);
  });

  test("a PDF with a valid envelope that PDF.js cannot open is render_failed, nothing half-drawn", async ({
    page,
    context,
  }) => {
    await mockCentral(context, allPdfs());
    await openWorkspace(page, false);
    await openFile(page, "broken-xref.pdf", false);
    await expect(
      page.getByRole("heading", { name: "此瀏覽器無法顯示這個檔案" }),
    ).toBeVisible({ timeout: 15_000 });
    await expect(page.locator("canvas")).toHaveCount(0);
  });
});

test.describe("bundle", () => {
  test("bundle_initial_chunk_unchanged: the first load carries no PDF.js; the sandbox engine is not served", async ({
    page,
    context,
  }) => {
    await mockCentral(context, []);
    const scripts: string[] = [];
    page.on("response", (response) => {
      if (response.request().resourceType() === "script")
        scripts.push(response.url());
    });
    await page.goto("/login");
    await page.waitForLoadState("networkidle");
    expect(scripts.filter((u) => /pdf|setup-/i.test(u))).toEqual([]);
    for (const url of scripts) {
      const body = await (await page.request.get(url)).text();
      expect(body.includes("GlobalWorkerOptions"), url).toBe(false);
    }
    // Served from a build, the QuickJS engine is simply not there (the SPA
    // fallback answers with the HTML shell, never with the module).
    for (const asset of [
      "/pdfjs/wasm/quickjs-eval.wasm",
      "/pdfjs/wasm/quickjs-eval.js",
    ]) {
      const response = await page.request.get(asset);
      const body = await response.body();
      expect(body.subarray(0, 4).toString("hex"), asset).not.toBe("0061736d");
      expect(body.toString("utf8"), asset).not.toContain("QuickJS");
    }
  });
});
