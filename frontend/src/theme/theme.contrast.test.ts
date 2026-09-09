// Contrast is measured, not claimed.
//
// Before this test the repository had no way to disagree with a colour choice,
// and five failures had shipped: the site-wide focus ring at 2.85:1, the
// Terminate confirm button at 4.09:1, every input border at 1.37:1, and six of
// the eight status badges under 4.5:1. None of them was waived — there was
// simply nothing that could go red.
//
// Every pair prints its measured value on success as well as failure. A test
// that only says "pass" turns into a rubber stamp; the numbers are the evidence
// the exit report quotes (plan/28 06-…md §3, `contrast.txt`).

import { afterAll, describe, expect, it } from "vitest";

import {
  BADGE_EDGE_FLOOR,
  DECORATIVE_EDGE_FLOOR,
  NON_TEXT_TARGET,
  PAIRS,
  TEXT_TARGET,
  contrastRatio,
} from "./contrast";
import { COLOR_TOKENS, THEME_IDS, THEMES, type ColorToken } from "./themes";

const STATUS_KINDS = [
  "success",
  "warning",
  "error",
  "info",
  "neutral",
] as const;

/** Collected so the whole table can be printed once, in evidence order. */
const measured: string[] = [];

describe("declared pairs reference real tokens", () => {
  it("every pair names tokens that exist", () => {
    // Guards against the quiet failure where a renamed token turns a pair into
    // `undefined / undefined`, which would compute a ratio of 1 and fail
    // loudly — or worse, be deleted to make the suite green.
    for (const pair of PAIRS) {
      expect(COLOR_TOKENS, pair.what).toContain(pair.fg as ColorToken);
      expect(COLOR_TOKENS, pair.what).toContain(pair.bg as ColorToken);
    }
  });

  it("covers the pair the five design documents missed", () => {
    // accent.primary on accent.subtle — the selected state of nav and tabs.
    // Regression guard on the *list*, not on a value: dropping this row is how
    // the omission happened the first time.
    const found = PAIRS.some(
      (p) => p.fg === "accent-strong" && p.bg === "accent-subtle",
    );
    expect(found).toBe(true);
  });
});

for (const id of THEME_IDS) {
  describe(`${id} contrast`, () => {
    const theme = THEMES[id];

    for (const pair of PAIRS) {
      const label = `${pair.fg} / ${pair.bg} — ${pair.what} (${pair.component})`;
      it(`${label} >= ${pair.target}:1`, () => {
        const fg = theme[pair.fg as ColorToken];
        const bg = theme[pair.bg as ColorToken];
        const ratio = contrastRatio(fg, bg);
        measured.push(
          `${id.padEnd(11)} ${String(ratio).padStart(6)}:1  (>= ${pair.target})  ` +
            `${pair.fg} ${fg} / ${pair.bg} ${bg}  — ${pair.what}`,
        );
        expect(
          ratio,
          `${id}: ${label} measured ${ratio}:1, needs ${pair.target}:1`,
        ).toBeGreaterThanOrEqual(pair.target);
      });
    }

    it("the decorative hairline on the terminal is visible but quiet", () => {
      const edge = contrastRatio(
        theme["border-on-terminal"],
        theme["terminal-background"],
      );
      measured.push(
        `${id.padEnd(11)} ${String(edge).padStart(6)}:1  (>= ${DECORATIVE_EDGE_FLOOR})  ` +
          `border-on-terminal ${theme["border-on-terminal"]} / ` +
          `terminal-background ${theme["terminal-background"]}  — decorative hairline`,
      );
      expect(edge).toBeGreaterThanOrEqual(DECORATIVE_EDGE_FLOOR);
      // And quiet: past the control floor it competes with terminal output,
      // which is the one thing on screen the user is actually reading.
      expect(edge).toBeLessThan(NON_TEXT_TARGET);
    });

    for (const kind of STATUS_KINDS) {
      it(`status.${kind} outline is the pill's strongest edge`, () => {
        const border = theme[`status-${kind}-border` as ColorToken];
        const fill = theme[`status-${kind}-bg` as ColorToken];
        const panel = theme["surface-default"];
        const edge = contrastRatio(border, fill);
        const outerEdge = contrastRatio(border, panel);
        const fillAgainstPanel = contrastRatio(fill, panel);
        measured.push(
          `${id.padEnd(11)} ${String(edge).padStart(6)}:1  (>= ${BADGE_EDGE_FLOOR})  ` +
            `status-${kind}-border ${border} / -bg ${fill}  — pill outline ` +
            `(outer ${outerEdge}, fill-vs-panel ${fillAgainstPanel})`,
        );
        expect(
          edge,
          `${id} status.${kind}: outline vs its own fill`,
        ).toBeGreaterThanOrEqual(BADGE_EDGE_FLOOR);
        // The load-bearing half: the fill against the panel is only ~1.15, so
        // if the outline is not a stronger edge than the fill, the pill has no
        // perceptible extent and the label floats on the panel.
        expect(
          outerEdge,
          `${id} status.${kind}: outline (${outerEdge}) must out-edge the fill ` +
            `(${fillAgainstPanel}) against the panel`,
        ).toBeGreaterThan(fillAgainstPanel);
      });
    }
  });
}

describe("the fixed baseline this replaces", () => {
  // The five measured failures from before plan/28, asserted as history. If a
  // future edit reintroduces one of these exact values, this goes red and names
  // it — which is more useful than "contrast regressed somewhere".
  const OLD = {
    borderFocus: "#67a2ae",
    surfaceElevated: "#ffffff",
    surfaceCanvas: "#f4f6f8",
    textInverse: "#ffffff",
    statusError: "#d25454",
    borderDefault: "#d7dde4",
    badgeOnlineFg: "#2f9b63",
    badgeOnlineBg: "#e8f5ee",
    badgeDegradedFg: "#c68c37",
    badgeDegradedBg: "#fbf2e4",
  };

  it("records what was actually wrong", () => {
    expect(contrastRatio(OLD.borderFocus, OLD.surfaceElevated)).toBe(2.85);
    expect(contrastRatio(OLD.borderFocus, OLD.surfaceCanvas)).toBe(2.64);
    expect(contrastRatio(OLD.textInverse, OLD.statusError)).toBe(4.09);
    expect(contrastRatio(OLD.borderDefault, OLD.surfaceElevated)).toBe(1.37);
    expect(contrastRatio(OLD.badgeOnlineFg, OLD.badgeOnlineBg)).toBe(3.13);
    expect(contrastRatio(OLD.badgeDegradedFg, OLD.badgeDegradedBg)).toBe(2.63);
  });

  it("shows each replacement clears its target with room", () => {
    for (const id of ["graphite", "porcelain"] as const) {
      const t = THEMES[id];
      // The focus ring, which used to fail on both surfaces.
      expect(
        contrastRatio(t["focus-ring"], t["surface-default"]),
      ).toBeGreaterThanOrEqual(NON_TEXT_TARGET);
      expect(
        contrastRatio(t["focus-ring"], t["surface-canvas"]),
      ).toBeGreaterThanOrEqual(NON_TEXT_TARGET);
      // The Terminate confirm button.
      expect(
        contrastRatio(t["danger-fg"], t["danger-bg"]),
      ).toBeGreaterThanOrEqual(TEXT_TARGET);
      // Every input border.
      expect(
        contrastRatio(t["border-control"], t["surface-default"]),
      ).toBeGreaterThanOrEqual(NON_TEXT_TARGET);
      // All five status foregrounds, where six of eight badges used to fail.
      for (const kind of STATUS_KINDS) {
        expect(
          contrastRatio(t[`status-${kind}-fg`], t[`status-${kind}-bg`]),
          `${id} ${kind}`,
        ).toBeGreaterThanOrEqual(TEXT_TARGET);
      }
    }
  });

  it("goes red if text.secondary moves two steps toward its background", () => {
    // The check ADR 0027 promises: a plausible-looking edit must fail, or none
    // of the numbers above mean anything.
    //
    // "Two steps toward the background", not "two steps lighter": on Graphite,
    // lighter secondary text on a near-black canvas *raises* contrast to 9.63:1.
    // Direction depends on the theme, and only the direction that reduces
    // contrast is a regression.
    const twoStepsQuieter = {
      graphite: "#69737A", // toward #111518
      porcelain: "#8A95A0", // toward #F9FAFC
    };
    for (const id of ["graphite", "porcelain"] as const) {
      const current = contrastRatio(
        THEMES[id]["text-secondary"],
        THEMES[id]["surface-canvas"],
      );
      const quieter = contrastRatio(
        twoStepsQuieter[id],
        THEMES[id]["surface-canvas"],
      );
      expect(current, `${id} currently ${current}`).toBeGreaterThanOrEqual(
        TEXT_TARGET,
      );
      expect(
        quieter,
        `${id} two steps quieter would measure ${quieter} — the suite must reject it`,
      ).toBeLessThan(TEXT_TARGET);
    }
  });
});

// Printed once, after the assertions, so `vitest run src/theme` output is the
// contrast.txt the evidence pack needs rather than a list of check marks.
afterAll(() => {
  if (!process.env.VITEST_CONTRAST_TABLE) return;
  measured.sort();
  console.log(`\n${measured.length} measured pairs:\n${measured.join("\n")}`);
});
