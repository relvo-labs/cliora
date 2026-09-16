// Applying a theme: one attribute, plus the two browser-chrome hints that do
// not read custom properties.
//
// This is deliberately not a Pinia store. It is called from the preferences
// store (which owns persistence) and from theme-boot.js's equivalent path on a
// cold load, and it must be callable before any Vue app exists.

import { NARROW } from "../composables/useBreakpoint";
import {
  DEFAULT_LIGHT_THEME,
  DEFAULT_THEME,
  THEMES,
  isShippedThemeId,
  type ShippedThemeId,
  type ThemeId,
} from "./themes";

export const THEME_STORAGE_KEY = "cliora-theme";

// Kept in step with public/theme-boot.js on purpose: the boot script cannot
// import this module (it must not import anything at all), so the two agree by
// review and by the E2E that drives the real localStorage path.
export function readStoredTheme(): ShippedThemeId | undefined {
  try {
    const raw = localStorage.getItem(THEME_STORAGE_KEY);
    return isShippedThemeId(raw) ? raw : undefined;
  } catch {
    // Private mode, or an origin where storage is blocked. Not an error: the
    // user simply has no stored preference.
    return undefined;
  }
}

export function prefersLight(): boolean {
  return (
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-color-scheme: light)").matches
  );
}

// The theme actually in force, which is not the same as the stored one: with
// nothing stored, the OS decides. Used by the switcher to show the current
// value and by xterm/Monaco to pick their palette.
export function effectiveTheme(): ShippedThemeId {
  return (
    readStoredTheme() ?? (prefersLight() ? DEFAULT_LIGHT_THEME : DEFAULT_THEME)
  );
}

// The mobile viewport overrides the stored choice (plan/29 MS-D-05/MS-D-06).
//
// One condition, `NARROW`, shared with the CSS breakpoints and with
// useBreakpoint — not `pointer: coarse`, which would flip a touchscreen laptop
// to a palette #62 never approved, and not a second width literal, which is how
// the layout breakpoints drifted apart in the first place.
//
// The stored choice is NOT overwritten. `readStoredTheme` keeps returning what
// the user picked, so moving between a phone and a desktop does not silently
// edit a preference the user set somewhere else; only what gets painted
// changes.
export function prefersPocket(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia(NARROW).matches
  );
}

/**
 * What is actually painted, which is not the same as what was chosen.
 *
 * Every caller that applies a theme goes through this; `effectiveTheme()` still
 * answers "which of the two shipped themes does this user want", and that is
 * the value the switcher shows.
 */
export function renderedTheme(chosen: ThemeId): ThemeId {
  return prefersPocket() ? "pocket" : chosen;
}

function setMeta(name: string, content: string): void {
  let el = document.querySelector<HTMLMetaElement>(`meta[name="${name}"]`);
  if (!el) {
    el = document.createElement("meta");
    el.name = name;
    document.head.appendChild(el);
  }
  el.content = content;
}

// Everything that has to move when the theme moves, in one place.
//
// `color-scheme` and `theme-color` are here rather than in CSS because neither
// the scrollbar nor a mobile address bar reads a custom property — leave them
// behind and the page changes colour while its scrollbars and browser chrome do
// not.
export function applyTheme(id: ThemeId): void {
  const root = document.documentElement;
  root.setAttribute("data-theme", id);
  const light = id === "porcelain" || id === "studio" || id === "pocket";
  root.style.colorScheme = light ? "light" : "dark";
  setMeta("theme-color", THEMES[id]["surface-canvas"]);
}
