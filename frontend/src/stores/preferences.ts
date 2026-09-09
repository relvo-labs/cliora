// Display preferences: theme, terminal font size, file-panel width, nav collapse.
//
// Deliberately client-only. There is no preferences API and plan/28 does not add
// one: a visual refresh has no reason to touch the authorization surface, and
// "add a column while we're here" is how a display setting ends up needing an
// answer to "does changing it enter the audit log". The honest cost is written
// down rather than discovered: **preferences do not follow the user to another
// machine or another browser.** Cross-device sync is a separate ticket.
//
// Every value here is a display preference and nothing more. None of them is a
// capability, none of them is sent to the server, and none of them may be read
// as permission for anything (`NFR-006.AC-07`). What is stored is four things —
// a theme id, a boolean, a number and a number — and specifically NOT the last
// opened directory: a width is a number, a path is user data.
//
// This store is the only writer of these keys. Reads that must happen before
// Vue exists (the first paint) go through public/theme-boot.js, which reads the
// theme key directly and is kept in step by theme.contract.test.ts.

import { defineStore } from "pinia";

import {
  THEME_STORAGE_KEY,
  applyTheme,
  effectiveTheme,
  readStoredTheme,
} from "../theme/applyTheme";
import { isShippedThemeId, type ShippedThemeId } from "../theme/themes";

const KEYS = {
  theme: THEME_STORAGE_KEY,
  terminalFontSize: "cliora-terminal-font-size",
  inspectorWidth: "cliora-inspector-width",
  navCollapsed: "cliora-nav-collapsed",
} as const;

// Bounds are the contract, not a suggestion: a stored value outside them is
// treated as absent rather than clamped into something the user never chose.
// They match the tokens (--layout-inspector-min/max) and style.md §18.
export const TERMINAL_FONT_MIN = 12;
export const TERMINAL_FONT_MAX = 20;
export const TERMINAL_FONT_DEFAULT = 14;
export const INSPECTOR_MIN = 220;
export const INSPECTOR_MAX = 360;
export const INSPECTOR_DEFAULT = 258;

function readNumber(
  key: string,
  min: number,
  max: number,
  fallback: number,
): number {
  try {
    const raw = localStorage.getItem(key);
    if (raw === null) return fallback;
    const value = Number(raw);
    if (!Number.isFinite(value) || value < min || value > max) return fallback;
    return Math.round(value);
  } catch {
    return fallback;
  }
}

function readBoolean(key: string, fallback: boolean): boolean {
  try {
    const raw = localStorage.getItem(key);
    return raw === null ? fallback : raw === "true";
  } catch {
    return fallback;
  }
}

// Storage can throw (private mode, a blocked origin). A preference that cannot
// be saved must still apply for this session, so every write is best-effort and
// the in-memory value is authoritative.
function write(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* Applies for this session only. */
  }
}

// Removing a key is how a preference returns to "not chosen", which is a
// different state from any value it could hold.
function remove(key: string): void {
  try {
    localStorage.removeItem(key);
  } catch {
    /* Applies for this session only. */
  }
}

interface PreferencesState {
  // The theme in force. Not the stored one: with nothing stored, the OS
  // preference decides, and the terminal still needs to know which palette that
  // resolved to.
  theme: ShippedThemeId;
  // Whether the user has chosen explicitly. Kept apart from `theme` because
  // "following the OS" is a third state, and collapsing it would turn the first
  // visit into a silent explicit choice that then ignores the OS forever.
  themeIsExplicit: boolean;
  terminalFontSize: number;
  inspectorWidth: number;
  navCollapsed: boolean;
}

// Mirror a preference change made in another tab, following the pattern
// `installAuthStorageSync` established for tokens.
//
// This is not a nicety. Personal settings are their own page, so changing a
// theme means leaving whatever you were looking at — and on the session
// workspace, leaving unmounts the terminal, which is then rebuilt on return.
// Without this listener there would be **no path at all** through which a theme
// changes while a terminal is alive, which would make the phase's central
// mechanism — recolour in place, never `new Terminal()` — unreachable in the
// product and untestable end to end.
//
// With it, the honest workflow works: open settings in a second tab, change the
// theme, and the tab holding the live session recolours without losing its
// scrollback, its scroll position or anything half-typed.
//
// Only display state is mirrored, and it is applied through the same actions a
// local change uses, so there is one code path rather than two.
export function installPreferencesStorageSync(): () => void {
  const handler = (event: StorageEvent): void => {
    // `null` means the whole store was cleared, which must re-read everything.
    if (
      event.key !== null &&
      !Object.values(KEYS).includes(event.key as never)
    ) {
      return;
    }
    const preferences = usePreferencesStore();
    const storedTheme = readStoredTheme();
    if (storedTheme === undefined) {
      preferences.themeIsExplicit = false;
      preferences.theme = effectiveTheme();
    } else {
      preferences.themeIsExplicit = true;
      preferences.theme = storedTheme;
    }
    applyTheme(preferences.theme);
    preferences.terminalFontSize = readNumber(
      KEYS.terminalFontSize,
      TERMINAL_FONT_MIN,
      TERMINAL_FONT_MAX,
      TERMINAL_FONT_DEFAULT,
    );
    preferences.inspectorWidth = readNumber(
      KEYS.inspectorWidth,
      INSPECTOR_MIN,
      INSPECTOR_MAX,
      INSPECTOR_DEFAULT,
    );
    preferences.navCollapsed = readBoolean(KEYS.navCollapsed, false);
  };
  window.addEventListener("storage", handler);
  return () => window.removeEventListener("storage", handler);
}

export const usePreferencesStore = defineStore("preferences", {
  state: (): PreferencesState => ({
    theme: effectiveTheme(),
    themeIsExplicit: readStoredTheme() !== undefined,
    terminalFontSize: readNumber(
      KEYS.terminalFontSize,
      TERMINAL_FONT_MIN,
      TERMINAL_FONT_MAX,
      TERMINAL_FONT_DEFAULT,
    ),
    inspectorWidth: readNumber(
      KEYS.inspectorWidth,
      INSPECTOR_MIN,
      INSPECTOR_MAX,
      INSPECTOR_DEFAULT,
    ),
    navCollapsed: readBoolean(KEYS.navCollapsed, false),
  }),
  actions: {
    // Called once from main.ts. On a cold load theme-boot.js has already set the
    // attribute, so this is a no-op for the theme; it exists so `color-scheme`
    // and `theme-color` are set even on the OS-preference path, where
    // theme-boot.js deliberately sets no attribute at all.
    init(): void {
      applyTheme(this.theme);
    },
    setTheme(id: ShippedThemeId): void {
      if (!isShippedThemeId(id)) return;
      this.theme = id;
      this.themeIsExplicit = true;
      write(KEYS.theme, id);
      applyTheme(id);
    },
    // Go back to following the operating system.
    //
    // Without this, "follow the OS" is a state the user can leave but never
    // return to: the first explicit choice writes the key, and from then on the
    // app ignores the OS forever. The state already existed in this store
    // (`themeIsExplicit`); it just had no way out, because the only UI was a
    // two-option select that could not express a third value.
    followSystemTheme(): void {
      remove(KEYS.theme);
      this.themeIsExplicit = false;
      this.theme = effectiveTheme();
      applyTheme(this.theme);
    },
    setTerminalFontSize(size: number): void {
      const next = Math.min(
        TERMINAL_FONT_MAX,
        Math.max(TERMINAL_FONT_MIN, Math.round(size)),
      );
      this.terminalFontSize = next;
      write(KEYS.terminalFontSize, String(next));
    },
    setInspectorWidth(width: number): void {
      const next = Math.min(
        INSPECTOR_MAX,
        Math.max(INSPECTOR_MIN, Math.round(width)),
      );
      this.inspectorWidth = next;
      write(KEYS.inspectorWidth, String(next));
    },
    setNavCollapsed(collapsed: boolean): void {
      this.navCollapsed = collapsed;
      write(KEYS.navCollapsed, String(collapsed));
    },
  },
});
