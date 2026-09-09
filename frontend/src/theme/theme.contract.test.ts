// The fuse for a deliberate cost.
//
// ADR 0027 §2 keeps colour in two files because two consumers cannot take a CSS
// custom property (xterm's `terminal.options.theme`, Monaco's `defineTheme()`).
// Two files that could drift is the price. This test is what makes the price
// bearable: it reads tokens.css as *text* and compares it to THEMES key by key.
//
// Reading the text rather than the computed style is deliberate — jsdom has no
// cascade worth trusting for custom properties, and the failure this catches
// ("someone edited one file") is a textual fact, not a rendering one.

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import {
  COLOR_TOKENS,
  DEFAULT_LIGHT_THEME,
  DEFAULT_THEME,
  THEME_IDS,
  THEMES,
} from "./themes";

const HERE = dirname(fileURLToPath(import.meta.url));
const CSS = readFileSync(join(HERE, "tokens.css"), "utf8");

// Strip comments first: several of them contain hex values as evidence ("blue
// #3465A4 measures 3.13:1"), and a declaration parser that reads those would
// report drift that does not exist.
const WITHOUT_COMMENTS = CSS.replace(/\/\*[\s\S]*?\*\//g, "");

/** Declarations inside the first rule whose selector matches `selector`. */
function block(selector: string): Record<string, string> {
  const at = WITHOUT_COMMENTS.indexOf(selector);
  if (at === -1)
    throw new Error(`selector not found in tokens.css: ${selector}`);
  const open = WITHOUT_COMMENTS.indexOf("{", at);
  const close = WITHOUT_COMMENTS.indexOf("}", open);
  if (open === -1 || close === -1) {
    throw new Error(`unterminated rule for ${selector}`);
  }
  const out: Record<string, string> = {};
  for (const line of WITHOUT_COMMENTS.slice(open + 1, close).split(";")) {
    const m = /^\s*(--[a-zA-Z0-9-]+)\s*:\s*(.+?)\s*$/.exec(line);
    if (m) out[m[1].slice(2)] = m[2];
  }
  return out;
}

// Case and inner whitespace are normalised before comparing, because neither is
// drift: Prettier lowercases hex in CSS but not in a TypeScript string literal,
// so an unnormalised comparison reports every single value as a mismatch the
// first time the formatter runs — and the only way to make that green again is
// to stop trusting the test.
function normalise(value: string): string {
  return value.toLowerCase().replace(/\s+/g, " ").trim();
}

/** Only the colour tokens of a block, so the shared scale does not interfere. */
function colours(selector: string): Record<string, string> {
  const all = block(selector);
  const out: Record<string, string> = {};
  for (const token of COLOR_TOKENS) {
    if (token in all) out[token] = normalise(all[token]);
  }
  return out;
}

function expectedColours(themeId: keyof typeof THEMES): Record<string, string> {
  const out: Record<string, string> = {};
  for (const token of COLOR_TOKENS) {
    out[token] = normalise(THEMES[themeId][token]);
  }
  return out;
}

const CASES: Array<[string, string, keyof typeof THEMES]> = [
  // The four rules from ADR 0027 §4, each checked against the table it claims.
  [":root (no choice, OS dark)", ":root {", DEFAULT_THEME],
  [
    ":root:not([data-theme]) under prefers-color-scheme: light",
    ":root:not([data-theme])",
    DEFAULT_LIGHT_THEME,
  ],
  ...THEME_IDS.map(
    (id) =>
      [`:root[data-theme="${id}"]`, `:root[data-theme="${id}"]`, id] as [
        string,
        string,
        keyof typeof THEMES,
      ],
  ),
];

describe("tokens.css agrees with themes.ts", () => {
  for (const [label, selector, themeId] of CASES) {
    it(`${label} defines every colour token, and every value matches ${themeId}`, () => {
      const actual = colours(selector);
      // toEqual, not toMatchObject: a missing token is the failure mode this
      // whole test exists for, and containment would pass it.
      expect(actual).toEqual(expectedColours(themeId));
    });
  }
});

describe("tokens.css structural rules", () => {
  it("has no chained var() fallback anywhere", () => {
    // `var(--x, #ccc)` is how a missing token gets covered up instead of fixed.
    expect(WITHOUT_COMMENTS).not.toMatch(/var\(\s*--[a-zA-Z0-9-]+\s*,/);
  });

  it("never redefines the theme-independent scale inside a theme block", () => {
    // A theme that changed a row height or a radius would be a layout change
    // wearing a colour change's clothes.
    const scale = Object.keys(block(":root {")).filter(
      (token) => !(COLOR_TOKENS as readonly string[]).includes(token),
    );
    expect(scale.length).toBeGreaterThan(0);
    for (const id of THEME_IDS) {
      const themeBlock = block(`:root[data-theme="${id}"]`);
      for (const token of scale) {
        expect(token in themeBlock, `${id} redefines --${token}`).toBe(false);
      }
    }
  });

  it("declares a color-scheme for every theme block", () => {
    // Without it the scrollbars and form controls stay in the previous scheme
    // while everything else moves.
    for (const id of THEME_IDS) {
      const at = CSS.indexOf(`:root[data-theme="${id}"]`);
      const body = CSS.slice(at, CSS.indexOf("}", at));
      expect(body, id).toMatch(/color-scheme:\s*(light|dark);/);
    }
  });

  it("keeps the light-preference rule scoped to :not([data-theme])", () => {
    // Drop the :not() and an explicit dark choice on a light OS stops holding —
    // which is the one case a CSS-only solution cannot express at all, and the
    // reason theme-boot.js exists.
    expect(CSS).toMatch(
      /@media \(prefers-color-scheme: light\) \{\s*:root:not\(\[data-theme\]\)/,
    );
  });
});

describe("theme-boot.js", () => {
  const BOOT = readFileSync(join(HERE, "../../public/theme-boot.js"), "utf8");
  // Comments stripped: the file's own header says it "imports nothing", and a
  // check that reads prose finds the word it is looking for in the sentence
  // promising not to do it.
  const BOOT_CODE = BOOT.replace(/\/\*[\s\S]*?\*\//g, "").replace(
    /\/\/.*$/gm,
    "",
  );

  it("imports nothing and does no I/O beyond localStorage", () => {
    // It runs before the CSP-governed module graph exists and blocks first
    // paint. Anything more than reading a key and setting an attribute belongs
    // in main.ts.
    expect(BOOT_CODE).not.toMatch(/\bimport\b|\brequire\(|\bfetch\(|\beval\(/);
  });

  it("stays short enough to review at a glance", () => {
    // The cost ADR 0027 accepts is "one unbundled script in public/", and it is
    // only acceptable while the script is small enough that reading it is the
    // whole audit. GATE-VR-NO-GLYPH-ICON checks the same bound in CI.
    const code = BOOT_CODE.split("\n").filter((l) => l.trim()).length;
    expect(code).toBeLessThanOrEqual(12);
  });

  it("accepts exactly the shipped theme ids", () => {
    // A stale or hand-edited localStorage value must not become a data-theme
    // attribute that no CSS rule matches — that renders the default theme's
    // colours under a non-default attribute, and the switcher then disagrees
    // with the screen.
    expect(BOOT).toContain('t === "graphite"');
    expect(BOOT).toContain('t === "porcelain"');
  });

  it("reads the same storage key applyTheme writes", () => {
    expect(BOOT).toContain('"cliora-theme"');
  });
});
