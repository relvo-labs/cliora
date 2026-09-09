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

// One ANSI set for every theme, verified against all five terminal
// backgrounds. black/brBlack are deliberately dim — see tokens.css.
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
    ...TERMINAL_ANSI,
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
