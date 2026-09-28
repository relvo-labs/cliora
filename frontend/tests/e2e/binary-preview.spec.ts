import { expect, test, type Page } from "@playwright/test";

import {
  cspViolations,
  generateFixtures,
  mockCentral,
  openFile,
  openWorkspace,
  type Fixtures,
  type PreviewFile,
} from "./binary-preview.harness";

// Images in the read-only binary preview (plan/31/05 BP-06, ADR 0029 §11), in a
// real browser under the production CSP. See binary-preview.harness.ts for what
// the stand-in Central does and does not cover.

let fx: Fixtures;
test.beforeAll(() => {
  fx = generateFixtures();
});
test.afterAll(() => fx?.cleanup());

const shotDir = process.env.E2E_SHOT_DIR;
async function shot(page: Page, name: string): Promise<void> {
  if (shotDir) await page.screenshot({ path: `${shotDir}/${name}.png` });
}

function images(): PreviewFile[] {
  return [
    {
      name: "ok.png",
      path: "ok.png",
      answer: {
        mime: "image/png",
        kind: "image",
        width: 1200,
        height: 800,
        bytes: fx.read("ok.png"),
      },
    },
    {
      name: "rotated.jpg",
      path: "rotated.jpg",
      answer: {
        mime: "image/jpeg",
        kind: "image",
        width: 64,
        height: 32,
        bytes: fx.read("ok-orientation6.jpg"),
      },
    },
    {
      name: "anim.gif",
      path: "anim.gif",
      answer: {
        mime: "image/gif",
        kind: "image",
        width: 48,
        height: 24,
        bytes: fx.read("ok-animated.gif"),
      },
    },
    {
      name: "huge.png",
      path: "huge.png",
      answer: {
        status: 413,
        code: "FILE_PREVIEW_LIMIT",
        details: { reason: "pixels" },
      },
    },
  ];
}

// Grey level of one canvas pixel, in canvas (backing store) coordinates
// expressed as fractions of its size.
async function grey(page: Page, fx: number, fy: number): Promise<number> {
  return page.evaluate(
    ([x, y]) => {
      const canvas =
        document.querySelector<HTMLCanvasElement>("canvas[role=img]")!;
      const context = canvas.getContext("2d")!;
      const px = context.getImageData(
        Math.floor(canvas.width * x),
        Math.floor(canvas.height * y),
        1,
        1,
      ).data;
      return Math.round((px[0] + px[1] + px[2]) / 3);
    },
    [fx, fy] as const,
  );
}

async function noSaveAffordance(page: Page): Promise<void> {
  for (const selector of ["img", "a[download]", "iframe", "object", "embed"]) {
    await expect(page.locator(selector), selector).toHaveCount(0);
  }
  await expect(page.locator("#panel-preview")).not.toContainText("下載");
}

for (const size of [
  { width: 390, height: 844 },
  { width: 1440, height: 900 },
]) {
  const narrow = size.width < 768;
  test.describe(`images at ${size.width}x${size.height}`, () => {
    test.beforeEach(async ({ page }) => {
      await page.setViewportSize(size);
    });

    test("a PNG fits the width, on a canvas, with nothing that saves it", async ({
      page,
      context,
    }) => {
      const central = await mockCentral(context, images());
      await openWorkspace(page, narrow);
      await openFile(page, "ok.png", narrow);

      const canvas = page.locator("canvas[role=img]");
      await expect(canvas).toHaveAttribute(
        "aria-label",
        "ok.png，1200×800 像素",
      );
      const box = (await canvas.boundingBox())!;
      const viewport = page.viewportSize()!;
      expect(box.width).toBeLessThanOrEqual(viewport.width);
      // The page itself never scrolls sideways.
      const overflow = await page.evaluate(
        () =>
          document.documentElement.scrollWidth -
          document.documentElement.clientWidth,
      );
      expect(overflow).toBeLessThanOrEqual(0);

      await noSaveAffordance(page);
      // The path went in the body, never the URL.
      expect(central.previewBodies).toEqual([
        JSON.stringify({ path: "ok.png" }),
      ]);
      expect(central.requests.filter((u) => u.includes("ok.png"))).toEqual([]);
      // Right-click on the canvas is swallowed (Firefox offers "Save Image As").
      const prevented = await canvas.evaluate((el) => {
        const event = new MouseEvent("contextmenu", {
          bubbles: true,
          cancelable: true,
        });
        el.dispatchEvent(event);
        return event.defaultPrevented;
      });
      expect(prevented).toBe(true);

      // Toolbar controls reach the touch floor as real boxes.
      for (const name of ["縮小", "符合寬度", "放大"]) {
        const b = (await page
          .getByRole("button", { name, exact: true })
          .boundingBox())!;
        expect(b.width, name).toBeGreaterThanOrEqual(44);
        expect(b.height, name).toBeGreaterThanOrEqual(44);
      }
      await page.getByRole("button", { name: "放大", exact: true }).click();
      await expect
        .poll(async () => (await canvas.boundingBox())!.width)
        .toBeGreaterThan(box.width);
      await shot(page, `png-${size.width}`);
      expect(await cspViolations(page)).toEqual([]);
    });

    test("EXIF orientation is applied: stored 64x32, shown 32x64, dark half on top", async ({
      page,
      context,
    }) => {
      await mockCentral(context, images());
      await openWorkspace(page, narrow);
      await openFile(page, "rotated.jpg", narrow);
      const canvas = page.locator("canvas[role=img]");
      await expect(canvas).toHaveAttribute(
        "aria-label",
        "rotated.jpg，32×64 像素",
      );
      expect(await grey(page, 0.5, 0.2)).toBeLessThan(100);
      expect(await grey(page, 0.5, 0.8)).toBeGreaterThan(160);
      expect(await cspViolations(page)).toEqual([]);
    });

    test("an animated GIF shows its first frame only, and says so", async ({
      page,
      context,
    }) => {
      await mockCentral(context, images());
      await openWorkspace(page, narrow);
      await openFile(page, "anim.gif", narrow);
      await expect(page.getByText("動畫僅顯示第一幀")).toBeVisible();
      // Frame 1 is dark on the left; frame 2 would be dark on the right.
      await page.waitForTimeout(1200);
      expect(await grey(page, 0.1, 0.5)).toBeLessThan(100);
      expect(await grey(page, 0.9, 0.5)).toBeGreaterThan(160);
      await shot(page, `gif-${size.width}`);
    });

    test("a refusal names the limit and offers no download", async ({
      page,
      context,
    }) => {
      await mockCentral(context, images());
      await openWorkspace(page, narrow);
      await openFile(page, "huge.png", narrow);
      await expect(
        page.getByRole("heading", { name: "超過預覽上限" }),
      ).toBeVisible();
      await expect(page.getByText(/像素數超過預覽上限/)).toBeVisible();
      await noSaveAffordance(page);
      await shot(page, `limit-${size.width}`);
    });
  });
}

test.describe("images on a phone: coming back", () => {
  test("back returns to the list with focus on the row that opened the preview", async ({
    page,
    context,
  }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    const many: PreviewFile[] = Array.from({ length: 40 }, (_, i) => ({
      name: `shot-${String(i).padStart(2, "0")}.png`,
      path: `shot-${String(i).padStart(2, "0")}.png`,
      answer: {
        mime: "image/png",
        kind: "image",
        width: 1200,
        height: 800,
        bytes: fx.read("ok.png"),
      },
    }));
    await mockCentral(context, many);
    await openWorkspace(page, true);
    const row = page.locator("#file-panel .entry", { hasText: "shot-30.png" });
    await row.scrollIntoViewIfNeeded();
    const before = await page.evaluate(() => {
      const panel = document.querySelector("#file-panel")!;
      const list = document.querySelector("#file-panel .browser")!;
      return { panel: panel.scrollTop, list: list.scrollTop };
    });
    expect(before.panel + before.list).toBeGreaterThan(0);
    await row.click();
    await expect(page.locator("canvas[role=img]")).toBeVisible();
    await expect(page.locator("#file-panel")).toHaveCount(0);

    await page.goBack();
    await expect(page.locator("#file-panel")).toBeVisible();
    await expect(page.locator(":focus")).toContainText("shot-30.png");
    const after = await page.evaluate(() => {
      const panel = document.querySelector("#file-panel")!;
      const list = document.querySelector("#file-panel .browser")!;
      return { panel: panel.scrollTop, list: list.scrollTop };
    });
    expect(after).toEqual(before);
    // Back again leaves the workspace's own history untouched: still here.
    await expect(page).toHaveURL(/\/sessions\//);
  });
});
