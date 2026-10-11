import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { afterEach, describe, expect, it } from "vitest";

import { contrastRatio } from "../../theme/contrast";
import { THEMES, type ColorToken } from "../../theme/themes";

// jsdom has no custom-property resolution. Resolve the real component CSS
// using the theme table (bound to tokens.css by theme.contract.test.ts), then
// measure inheritance/background selection. Browser coverage uses the mounted
// component too, including the desktop workspace behind it.
const here = dirname(fileURLToPath(import.meta.url));
function styles(file: string): string {
  return readFileSync(file, "utf8")
    .split("<style scoped>")[1]
    .split("</style>")[0];
}

afterEach(() => {
  document.body.innerHTML = "";
  document.head
    .querySelectorAll("[data-preview-proof]")
    .forEach((el) => el.remove());
});

describe("PreviewPane — Porcelain contrast (#97)", () => {
  for (const selector of [".file", ".readonly", ".meta"]) {
    it(`${selector} is readable on its painted surface`, () => {
      const css =
        styles(join(here, "PreviewPane.vue")) +
        styles(join(here, "../../views/SessionWorkspaceView.vue"));
      const sheet = document.createElement("style");
      sheet.dataset.previewProof = "";
      sheet.textContent = css.replace(
        /var\(--([\w-]+)\)/g,
        (match, token: string) =>
          THEMES.porcelain[token as ColorToken] ?? match,
      );
      document.head.appendChild(sheet);
      document.body.innerHTML =
        '<div class="center"><section class="preview"><header class="head"><h2><span class="file">app.ts</span><span class="readonly">唯讀</span></h2></header><p class="meta">src/app.ts · typescript · utf-8</p></section></div>';
      const el = document.querySelector(selector)!;
      let surface: Element | null = el;
      while (
        surface &&
        ["", "rgba(0, 0, 0, 0)"].includes(
          getComputedStyle(surface).backgroundColor,
        )
      )
        surface = surface.parentElement;
      const hex = (rgb: string) =>
        "#" +
        rgb
          .match(/\d+/g)!
          .slice(0, 3)
          .map((n) => Number(n).toString(16).padStart(2, "0"))
          .join("");
      const fg = hex(getComputedStyle(el).color);
      const bg = hex(getComputedStyle(surface!).backgroundColor);
      expect(
        contrastRatio(fg, bg),
        `${selector}: ${fg} on ${bg}`,
      ).toBeGreaterThanOrEqual(4.5);
    });
  }
});
