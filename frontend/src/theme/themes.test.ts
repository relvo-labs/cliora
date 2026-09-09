// Every theme defines every token — asserted by key-set equality, not
// containment.
//
// The distinction is the whole point. A theme that omits a token does not blow
// up; it inherits whatever `:root` said, so the symptom is "that one area kept
// the previous theme's colour". In a screenshot review that reads as slightly
// odd rather than broken, which makes it the failure most likely to ship. The
// shared design foundation says the same thing as a rule ("每個主題必須明確定義,
// 不用鏈式fallback掩蓋缺漏"); this is that rule with teeth.

import { describe, expect, it } from "vitest";

import {
  COLOR_TOKENS,
  DEFAULT_LIGHT_THEME,
  DEFAULT_THEME,
  SHIPPED_THEME_IDS,
  THEME_IDS,
  THEMES,
  TERMINAL_ANSI,
  isShippedThemeId,
  isThemeId,
  monacoColors,
  xtermTheme,
} from "./themes";

const HEX = /^#[0-9A-F]{6}([0-9A-F]{2})?$/;

describe("theme table completeness", () => {
  it("defines a table for every declared theme id and nothing more", () => {
    expect(Object.keys(THEMES).sort()).toEqual([...THEME_IDS].sort());
  });

  for (const id of THEME_IDS) {
    it(`${id} defines exactly the colour tokens, no gaps and no extras`, () => {
      expect(Object.keys(THEMES[id]).sort()).toEqual([...COLOR_TOKENS].sort());
    });

    it(`${id} has no value that defers to another token`, () => {
      // A `var(...)` here would reintroduce the chained fallback the token
      // contract forbids, and xterm/Monaco cannot resolve one anyway.
      for (const [token, value] of Object.entries(THEMES[id])) {
        expect(value, `${id}.${token}`).not.toMatch(/var\(/);
      }
    });

    it(`${id} colour values are all opaque-or-alpha hex`, () => {
      for (const token of COLOR_TOKENS) {
        if (token === "shadow-overlay") continue; // a shadow, not a colour
        expect(THEMES[id][token], `${id}.${token}`).toMatch(HEX);
      }
    });
  }
});

describe("shipped set", () => {
  it("ships only themes that have a table", () => {
    for (const id of SHIPPED_THEME_IDS) expect(THEME_IDS).toContain(id);
  });

  it("ships exactly the two themes the acceptance matrix covers", () => {
    // Adding a third would silently claim browser acceptance that ADR 0027 §5
    // records as not done. Widening the switcher is a decision, not a tweak.
    expect([...SHIPPED_THEME_IDS]).toEqual(["graphite", "porcelain"]);
  });

  it("has a dark default and a light fallback, both shipped", () => {
    expect(isShippedThemeId(DEFAULT_THEME)).toBe(true);
    expect(isShippedThemeId(DEFAULT_LIGHT_THEME)).toBe(true);
    expect(DEFAULT_THEME).not.toBe(DEFAULT_LIGHT_THEME);
  });

  it("guards reject unknown ids", () => {
    expect(isThemeId("solarized")).toBe(false);
    expect(isThemeId(undefined)).toBe(false);
    expect(isShippedThemeId("midnight")).toBe(false);
    expect(isThemeId("midnight")).toBe(true);
  });
});

describe("terminal palette", () => {
  it("keeps one ANSI set for every theme", () => {
    expect(Object.keys(TERMINAL_ANSI)).toHaveLength(16);
    for (const value of Object.values(TERMINAL_ANSI)) {
      expect(value).toMatch(HEX);
    }
  });

  it("does not turn the terminal light in a light theme", () => {
    // The shared foundation is explicit: text, cursor and search inside the
    // terminal must not inherit a light frame's dark text. Porcelain gets
    // --text-on-terminal for the UI that sits *on* the terminal instead.
    expect(THEMES.porcelain["terminal-background"]).toBe(
      THEMES.graphite["terminal-background"],
    );
    expect(THEMES.porcelain["terminal-foreground"]).toBe(
      THEMES.graphite["terminal-foreground"],
    );
  });

  for (const id of THEME_IDS) {
    it(`${id} produces a complete xterm theme`, () => {
      const t = xtermTheme(id);
      expect(t.background).toBe(THEMES[id]["terminal-background"]);
      expect(t.cursor).toBe(THEMES[id]["terminal-cursor"]);
      // All 16 ANSI slots present: leaving any of them out drops that slot back
      // to xterm's default, and two of those defaults are the ones the palette
      // exists to replace.
      for (const key of Object.keys(TERMINAL_ANSI)) {
        expect(t[key], `${id}.${key}`).toMatch(HEX);
      }
    });

    it(`${id} produces Monaco colours with no undefined value`, () => {
      for (const [key, value] of Object.entries(monacoColors(id))) {
        expect(value, `${id}.${key}`).toMatch(HEX);
      }
    });
  }
});
