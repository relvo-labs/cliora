// Applying a theme: one attribute, plus the two browser-chrome hints that do
// not read custom properties.
//
// This is deliberately not a Pinia store. It is called from the preferences
// store (which owns persistence) and from theme-boot.js's equivalent path on a
// cold load, and it must be callable before any Vue app exists.

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
  const light = id === "porcelain" || id === "studio";
  root.style.colorScheme = light ? "light" : "dark";
  setMeta("theme-color", THEMES[id]["surface-canvas"]);
}
