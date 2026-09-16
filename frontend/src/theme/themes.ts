// The JS side of the token contract (ADR 0027 §2).
//
// Two consumers cannot take a CSS custom property: xterm's
// `terminal.options.theme` and Monaco's `defineTheme()` both need resolved
// colour strings. So the same table exists here and in theme/tokens.css, and
// theme.contract.test.ts parses that file's text and compares it against this
// one key by key. That test is the fuse for a deliberate cost — without it,
// this is just two files that will drift.
//
// Values are not edited here alone. Change both files, or the contract test
// fails, which is the point.

export const THEME_IDS = [
  "graphite",
  "porcelain",
  "midnight",
  "studio",
  "industrial",
  "pocket",
] as const;
export type ThemeId = (typeof THEME_IDS)[number];

// Offered in the switcher and covered by the acceptance matrix. The other
// three have values (and pass the tests) but no browser acceptance and no
// layout variant, so offering them would be claiming more than was
// verified (ADR 0027 §5).
export const SHIPPED_THEME_IDS = ["graphite", "porcelain"] as const;
export type ShippedThemeId = (typeof SHIPPED_THEME_IDS)[number];
export const DEFAULT_THEME: ShippedThemeId = "graphite";
// Used when nothing was ever chosen and the OS prefers light. Kept next to
// DEFAULT_THEME so the pair cannot drift from the two CSS rules.
export const DEFAULT_LIGHT_THEME: ShippedThemeId = "porcelain";

export function isThemeId(value: unknown): value is ThemeId {
  return (THEME_IDS as readonly string[]).includes(value as string);
}

export function isShippedThemeId(value: unknown): value is ShippedThemeId {
  return (SHIPPED_THEME_IDS as readonly string[]).includes(value as string);
}

export const COLOR_TOKENS = [
  "surface-canvas",
  "surface-default",
  "surface-raised",
  "surface-scrim",
  "border-subtle",
  "border-control",
  "focus-ring",
  "text-primary",
  "text-secondary",
  "text-on-accent",
  "text-on-terminal",
  "text-disabled",
  "accent-primary",
  "accent-strong",
  "accent-subtle",
  "accent-hover",
  "danger-bg",
  "danger-fg",
  "danger-hover",
  "status-success-fg",
  "status-success-bg",
  "status-success-border",
  "status-warning-fg",
  "status-warning-bg",
  "status-warning-border",
  "status-error-fg",
  "status-error-bg",
  "status-error-border",
  "status-info-fg",
  "status-info-bg",
  "status-info-border",
  "status-neutral-fg",
  "status-neutral-bg",
  "status-neutral-border",
  "terminal-background",
  "terminal-foreground",
  "terminal-input",
  "terminal-cursor",
  "terminal-selection",
  "text-on-terminal-dim",
  "border-on-terminal",
  "border-on-terminal-control",
  "surface-on-terminal",
  "shadow-overlay",
] as const;
export type ColorToken = (typeof COLOR_TOKENS)[number];

// Record, not Partial: a theme that omits a token does not compile.
export type Theme = Record<ColorToken, string>;

export const THEMES: Record<ThemeId, Theme> = {
  graphite: {
    // Surfaces and boundaries
    "surface-canvas": "#111518",
    "surface-default": "#191E22",
    "surface-raised": "#20272C",
    "surface-scrim": "#00000099",
    "border-subtle": "#2B3339",
    "border-control": "#647784",
    "focus-ring": "#81C9B9",
    // Text
    "text-primary": "#E4E9EB",
    "text-secondary": "#8E9AA3",
    "text-on-accent": "#111518",
    "text-on-terminal": "#C9D3D8",
    "text-disabled": "#6D767D",
    // Accent and actions
    "accent-primary": "#81C9B9",
    "accent-strong": "#81C9B9",
    "accent-subtle": "#233A36",
    "accent-hover": "#93D3C4",
    "danger-bg": "#F08C8C",
    "danger-fg": "#111518",
    "danger-hover": "#F5A3A3",
    // Status: five semantics, three values each
    "status-success-fg": "#6FC79B",
    "status-success-bg": "#17302A",
    "status-success-border": "#2E5648",
    "status-warning-fg": "#E0AE5E",
    "status-warning-bg": "#332918",
    "status-warning-border": "#5A4A2B",
    "status-error-fg": "#F08C8C",
    "status-error-bg": "#3A2020",
    "status-error-border": "#603A3A",
    "status-info-fg": "#8CB6E8",
    "status-info-bg": "#182B3D",
    "status-info-border": "#31485F",
    "status-neutral-fg": "#A6B0B8",
    "status-neutral-bg": "#262B30",
    "status-neutral-border": "#434A50",
    // Terminal and editor
    "terminal-background": "#101416",
    "terminal-foreground": "#C9D3D8",
    "terminal-input": "#E4EEEB",
    "terminal-cursor": "#FFFFFF",
    "terminal-selection": "#78AAFF40",
    "text-on-terminal-dim": "#A2ACB8",
    "border-on-terminal": "#3A424D",
    "border-on-terminal-control": "#68727E",
    "surface-on-terminal": "#1C2027",
    // Elevation
    "shadow-overlay": "0 12px 32px #00000066",
  },
  porcelain: {
    // Surfaces and boundaries
    "surface-canvas": "#F9FAFC",
    "surface-default": "#FFFFFF",
    "surface-raised": "#EEF2F7",
    "surface-scrim": "#25313C73",
    "border-subtle": "#E0E5EB",
    "border-control": "#838689",
    "focus-ring": "#286BF0",
    // Text
    "text-primary": "#25313C",
    "text-secondary": "#5E6B78",
    "text-on-accent": "#FFFFFF",
    "text-on-terminal": "#C9D3D8",
    "text-disabled": "#78899A",
    // Accent and actions
    "accent-primary": "#286BF0",
    "accent-strong": "#1B54C4",
    "accent-subtle": "#E9F0FF",
    "accent-hover": "#1B54C4",
    "danger-bg": "#B03434",
    "danger-fg": "#FFFFFF",
    "danger-hover": "#8E2727",
    // Status: five semantics, three values each
    "status-success-fg": "#1F7A54",
    "status-success-bg": "#E4F3EA",
    "status-success-border": "#B8DCC8",
    "status-warning-fg": "#7E5712",
    "status-warning-bg": "#FAF0DC",
    "status-warning-border": "#E0C68C",
    "status-error-fg": "#B03434",
    "status-error-bg": "#FBE9E9",
    "status-error-border": "#E8B8B8",
    "status-info-fg": "#1F5C96",
    "status-info-bg": "#E8F0FA",
    "status-info-border": "#B6CDE6",
    "status-neutral-fg": "#5E6B78",
    "status-neutral-bg": "#EEF1F4",
    "status-neutral-border": "#CBD3DA",
    // Terminal and editor
    "terminal-background": "#101416",
    "terminal-foreground": "#C9D3D8",
    "terminal-input": "#E4EEEB",
    "terminal-cursor": "#FFFFFF",
    "terminal-selection": "#78AAFF40",
    "text-on-terminal-dim": "#A2ACB8",
    "border-on-terminal": "#3A424D",
    "border-on-terminal-control": "#68727E",
    "surface-on-terminal": "#1C2027",
    // Elevation
    "shadow-overlay": "0 8px 28px #25313C1F",
  },
  // The mobile-only light theme (plan/29 MS-18). Not offered in the switcher:
  // it is selected from the viewport, not from a preference (MS-D-05), so it is
  // in THEME_IDS but not in SHIPPED_THEME_IDS.
  //
  // Non-terminal values are Porcelain's, unchanged and deliberately so — they
  // are already measured and already shipping, and re-deriving them would put a
  // second light palette in the product for no reason. What pocket exists to
  // change is the nine terminal tokens below, which in Porcelain are still
  // dark: a light workbench with a dark terminal is the thing #62 rejected.
  pocket: {
    // Surfaces and boundaries
    "surface-canvas": "#F9FAFC",
    "surface-default": "#FFFFFF",
    "surface-raised": "#EEF2F7",
    "surface-scrim": "#25313C73",
    "border-subtle": "#E0E5EB",
    "border-control": "#838689",
    "focus-ring": "#286BF0",
    // Text
    "text-primary": "#25313C",
    "text-secondary": "#5E6B78",
    "text-on-accent": "#FFFFFF",
    "text-on-terminal": "#2B333B",
    "text-disabled": "#78899A",
    // Accent and actions
    "accent-primary": "#286BF0",
    "accent-strong": "#1B54C4",
    "accent-subtle": "#E9F0FF",
    "accent-hover": "#1B54C4",
    "danger-bg": "#B03434",
    "danger-fg": "#FFFFFF",
    "danger-hover": "#8E2727",
    // Status: five semantics, three values each
    "status-success-fg": "#1F7A54",
    "status-success-bg": "#E4F3EA",
    "status-success-border": "#B8DCC8",
    "status-warning-fg": "#7E5712",
    "status-warning-bg": "#FAF0DC",
    "status-warning-border": "#E0C68C",
    "status-error-fg": "#B03434",
    "status-error-bg": "#FBE9E9",
    "status-error-border": "#E8B8B8",
    "status-info-fg": "#1F5C96",
    "status-info-bg": "#E8F0FA",
    "status-info-border": "#B6CDE6",
    "status-neutral-fg": "#5E6B78",
    "status-neutral-bg": "#EEF1F4",
    "status-neutral-border": "#CBD3DA",
    // Terminal and editor. The terminal is the brightest surface here, not the
    // darkest: on a light workbench the thing being read takes the "paper"
    // role and the canvas recedes behind it.
    "terminal-background": "#FFFFFF",
    "terminal-foreground": "#2B333B",
    "terminal-input": "#10161B",
    "terminal-cursor": "#16324F",
    "terminal-selection": "#286BF033",
    "text-on-terminal-dim": "#5B6670",
    "border-on-terminal": "#DFE4EA",
    "border-on-terminal-control": "#8A949D",
    "surface-on-terminal": "#EEF1F5",
    // Elevation
    "shadow-overlay": "0 8px 28px #25313C1F",
  },
  midnight: {
    // Surfaces and boundaries
    "surface-canvas": "#0B1322",
    "surface-default": "#111E32",
    "surface-raised": "#1A2D48",
    "surface-scrim": "#00000099",
    "border-subtle": "#243752",
    "border-control": "#517BB8",
    "focus-ring": "#94BFF5",
    // Text
    "text-primary": "#E0EAFA",
    "text-secondary": "#8B9FB9",
    "text-on-accent": "#111518",
    "text-on-terminal": "#C9D3D8",
    "text-disabled": "#6C7B90",
    // Accent and actions
    "accent-primary": "#94BFF5",
    "accent-strong": "#94BFF5",
    "accent-subtle": "#213552",
    "accent-hover": "#A2CBFF",
    "danger-bg": "#F08C8C",
    "danger-fg": "#111518",
    "danger-hover": "#F5A3A3",
    // Status: five semantics, three values each
    "status-success-fg": "#6FC79B",
    "status-success-bg": "#17302A",
    "status-success-border": "#2E5648",
    "status-warning-fg": "#E0AE5E",
    "status-warning-bg": "#332918",
    "status-warning-border": "#5A4A2B",
    "status-error-fg": "#F08C8C",
    "status-error-bg": "#3A2020",
    "status-error-border": "#603A3A",
    "status-info-fg": "#8CB6E8",
    "status-info-bg": "#182B3D",
    "status-info-border": "#31485F",
    "status-neutral-fg": "#A6B0B8",
    "status-neutral-bg": "#262B30",
    "status-neutral-border": "#434A50",
    // Terminal and editor
    "terminal-background": "#0A1323",
    "terminal-foreground": "#C9D3D8",
    "terminal-input": "#E4EEEB",
    "terminal-cursor": "#FFFFFF",
    "terminal-selection": "#78AAFF40",
    "text-on-terminal-dim": "#A2ACB8",
    "border-on-terminal": "#3A424D",
    "border-on-terminal-control": "#68727E",
    "surface-on-terminal": "#1C2027",
    // Elevation
    "shadow-overlay": "0 12px 32px #00000066",
  },
  studio: {
    // Surfaces and boundaries
    "surface-canvas": "#F4F1EB",
    "surface-default": "#FAF8F3",
    "surface-raised": "#EAE5DD",
    "surface-scrim": "#25313C73",
    "border-subtle": "#DED8CE",
    "border-control": "#807D77",
    "focus-ring": "#B6653F",
    // Text
    "text-primary": "#35332E",
    "text-secondary": "#6C6256",
    "text-on-accent": "#FFFFFF",
    "text-on-terminal": "#C9D3D8",
    "text-disabled": "#897C6D",
    // Accent and actions
    "accent-primary": "#B6653F",
    "accent-strong": "#984D2E",
    "accent-subtle": "#F1E2D7",
    "accent-hover": "#7D3F26",
    "danger-bg": "#B03434",
    "danger-fg": "#FFFFFF",
    "danger-hover": "#8E2727",
    // Status: five semantics, three values each
    "status-success-fg": "#1F7048",
    "status-success-bg": "#E6F0E4",
    "status-success-border": "#BAD6B6",
    "status-warning-fg": "#7A5310",
    "status-warning-bg": "#F7EBD5",
    "status-warning-border": "#DEC188",
    "status-error-fg": "#A93430",
    "status-error-bg": "#F8E7E3",
    "status-error-border": "#E5B6AF",
    "status-info-fg": "#1D5580",
    "status-info-bg": "#E5EEF4",
    "status-info-border": "#B4CCDD",
    "status-neutral-fg": "#615A4E",
    "status-neutral-bg": "#EDE9E1",
    "status-neutral-border": "#CFC7B9",
    // Terminal and editor
    "terminal-background": "#252420",
    "terminal-foreground": "#C9D3D8",
    "terminal-input": "#E4EEEB",
    "terminal-cursor": "#FFFFFF",
    "terminal-selection": "#78AAFF40",
    "text-on-terminal-dim": "#A2ACB8",
    "border-on-terminal": "#3A424D",
    "border-on-terminal-control": "#68727E",
    "surface-on-terminal": "#1C2027",
    // Elevation
    "shadow-overlay": "0 8px 28px #25313C1F",
  },
  industrial: {
    // Surfaces and boundaries
    "surface-canvas": "#121416",
    "surface-default": "#191B1D",
    "surface-raised": "#25282A",
    "surface-scrim": "#00000099",
    "border-subtle": "#363A3D",
    "border-control": "#6E767C",
    "focus-ring": "#E9BB44",
    // Text
    "text-primary": "#E7E7E4",
    "text-secondary": "#9B9C95",
    "text-on-accent": "#111518",
    "text-on-terminal": "#C9D3D8",
    "text-disabled": "#757670",
    // Accent and actions
    "accent-primary": "#E9BB44",
    "accent-strong": "#E9BB44",
    "accent-subtle": "#393323",
    "accent-hover": "#FED059",
    "danger-bg": "#F08C8C",
    "danger-fg": "#111518",
    "danger-hover": "#F5A3A3",
    // Status: five semantics, three values each
    "status-success-fg": "#6FC79B",
    "status-success-bg": "#17302A",
    "status-success-border": "#2E5648",
    "status-warning-fg": "#E0AE5E",
    "status-warning-bg": "#332918",
    "status-warning-border": "#5A4A2B",
    "status-error-fg": "#F08C8C",
    "status-error-bg": "#3A2020",
    "status-error-border": "#603A3A",
    "status-info-fg": "#8CB6E8",
    "status-info-bg": "#182B3D",
    "status-info-border": "#31485F",
    "status-neutral-fg": "#A6B0B8",
    "status-neutral-bg": "#262B30",
    "status-neutral-border": "#434A50",
    // Terminal and editor
    "terminal-background": "#101214",
    "terminal-foreground": "#C9D3D8",
    "terminal-input": "#E4EEEB",
    "terminal-cursor": "#FFFFFF",
    "terminal-selection": "#78AAFF40",
    "text-on-terminal-dim": "#A2ACB8",
    "border-on-terminal": "#3A424D",
    "border-on-terminal-control": "#68727E",
    "surface-on-terminal": "#1C2027",
    // Elevation
    "shadow-overlay": "0 12px 32px #00000066",
  },
};

// ANSI, per theme family (plan/29 MS-18 §0.1).
//
// This used to be one table for every theme, and the comment said it was
// "verified against all five terminal backgrounds". All five were dark —
// Porcelain included, because Porcelain's terminal is still #101416. The moment
// a theme put a light surface under these, brWhite (#E8EEF0) sat at 1.06:1 on
// it.
//
// The split is deliberately conservative: every dark theme keeps this exact
// table, byte for byte, so nothing that ships today changes colour.
// themes.test.ts asserts that equality, because "we refactored the palette" is
// not something to take on trust.
//
// The rule the old table already followed, without saying so: fourteen of the
// sixteen are readable (5.79-16.02:1) and two — black and brBlack — are
// deliberately dim, because they are the end of the ramp that sits nearest the
// background. A light theme does not need a new rule, it needs that one
// mirrored: the dim end moves from the dark end to the light end.
export const TERMINAL_ANSI = {
  black: "#3A4145",
  red: "#E8807F",
  green: "#8FCB9B",
  yellow: "#DFBE72",
  blue: "#8FB6E8",
  magenta: "#C3A0DC",
  cyan: "#79C6C9",
  white: "#C9D3D8",
  brBlack: "#6B7478",
  brRed: "#F09B9A",
  brGreen: "#A8DCB2",
  brYellow: "#EDD08C",
  brBlue: "#A9CAF2",
  brMagenta: "#D5B8E8",
  brCyan: "#96DADC",
  brWhite: "#E8EEF0",
} as const;

// The same sixteen roles against a light terminal (plan/29 07-…md §1.2).
//
// Three rules produced these, and they are worth stating because the obvious
// alternative is wrong in a way that looks clever:
//
//   1. The ramp keeps its direction. black is still the darkest and brWhite
//      still the lightest. Mapping black to a pale grey and white to a dark one
//      would make both ends "readable" and would render `\e[30;47m` — black on
//      white, a pairing the CLI authored as a pair — as light on dark. That is
//      not a contrast problem, it is the palette lying about its own order.
//   2. The twelve chromatic colours all clear 4.5:1. They are where CLI output
//      carries meaning: the error is red, the diff is green.
//   3. `bright` goes *darker* here, not lighter. For the four greys `bright`
//      means a position on the ramp, so they stay in order; for the twelve
//      colours it means emphasis, and on a light surface "lighter" is less
//      contrast, which would make the emphasised span the hardest one to read.
//
// Measured against #FFFFFF: chromatics 5.35-9.28, black 14.90, brBlack 10.23,
// white 3.66, brWhite 1.69. The last two are the dim end, the mirror of
// black/brBlack above.
export const POCKET_ANSI = {
  black: "#22282D",
  red: "#B62B2B",
  green: "#1F7A45",
  yellow: "#7A5A12",
  blue: "#1F5FD0",
  magenta: "#9333A8",
  cyan: "#0F6F77",
  white: "#7D8790",
  brBlack: "#39424A",
  brRed: "#8F1F1F",
  brGreen: "#155C33",
  brYellow: "#5C430D",
  brBlue: "#16469C",
  brMagenta: "#72237F",
  brCyan: "#0A5359",
  brWhite: "#C2C8CE",
} as const;

/**
 * The two ANSI slots each theme deliberately leaves dim, named rather than
 * inferred.
 *
 * Inferring them from "is this theme light or dark" would silently pick the
 * wrong pair the first time someone adds a theme whose terminal surface is a
 * mid-tone, and the symptom would be a contrast test that passes while two
 * colours are invisible.
 */
export const TERMINAL_DIM_ANSI: Record<ThemeId, readonly [string, string]> = {
  graphite: ["black", "brBlack"],
  porcelain: ["black", "brBlack"],
  midnight: ["black", "brBlack"],
  studio: ["black", "brBlack"],
  industrial: ["black", "brBlack"],
  pocket: ["white", "brWhite"],
};

/**
 * Whether this theme's terminal surface is light.
 *
 * Read from the token, not from a list of theme ids: xterm, Monaco and
 * `color-scheme` all need the same answer, and three hand-maintained lists
 * would be three chances to disagree. The threshold is sRGB relative luminance
 * rather than a "looks light" judgement, and 0.5 is the midpoint rather than a
 * tuned value — every terminal surface in the table is far from it (pocket is
 * 1.0, the darkest is 0.006).
 */
export function isLightTerminal(id: ThemeId): boolean {
  const hex = THEMES[id]["terminal-background"].replace("#", "").slice(0, 6);
  const channel = (v: number): number => {
    const c = v / 255;
    return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
  };
  const luminance =
    0.2126 * channel(parseInt(hex.slice(0, 2), 16)) +
    0.7152 * channel(parseInt(hex.slice(2, 4), 16)) +
    0.0722 * channel(parseInt(hex.slice(4, 6), 16));
  return luminance > 0.5;
}

/** The sixteen ANSI colours this theme renders with. */
export function terminalAnsi(id: ThemeId): Record<string, string> {
  return id === "pocket" ? { ...POCKET_ANSI } : { ...TERMINAL_ANSI };
}

// What xterm gets. Assigned as `terminal.options.theme = xtermTheme(id)`,
// never `new Terminal()`: measured in chromium on 2026-09-08, that assignment
// repaints in place and leaves buffer length, viewportY, cursorX and rows all
// unchanged, which is what makes "switching theme does not interrupt work"
// true (plan/28 08-…md §2).
export function xtermTheme(id: ThemeId): Record<string, string> {
  const t = THEMES[id];
  return {
    background: t["terminal-background"],
    foreground: t["terminal-foreground"],
    cursor: t["terminal-cursor"],
    cursorAccent: t["terminal-background"],
    selectionBackground: t["terminal-selection"],
    ...terminalAnsi(id),
  };
}

// What Monaco gets. The preview stays dark in every theme (style.md §19: it
// shares the terminal's dark surface) — a light editor inside a light theme
// would put two different code backgrounds in one workspace.
export function monacoColors(id: ThemeId): Record<string, string> {
  const t = THEMES[id];
  return {
    "editor.background": t["terminal-background"],
    "editor.foreground": t["terminal-foreground"],
    "editorLineNumber.foreground": t["text-disabled"],
    "editorLineNumber.activeForeground": t["terminal-foreground"],
    "editor.selectionBackground": t["terminal-selection"],
    "editor.lineHighlightBackground": t["surface-raised"],
    "editorCursor.foreground": t["terminal-cursor"],
    "editorGutter.background": t["terminal-background"],
    "editorWidget.background": t["surface-raised"],
    "editorWidget.border": t["border-subtle"],
  };
}
