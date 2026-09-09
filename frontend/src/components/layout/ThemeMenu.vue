<script setup lang="ts">
// A compact theme switcher — used only by the dev-only token showcase.
//
// It is deliberately NOT product UI any more. It began as a `<select>` in the
// app header and a second copy in the workspace status bar, and both were
// wrong: a theme is a global preference, so a permanent control on every page
// reads as page-scoped, and two copies of it made that worse. The real home is
// personal settings (`/settings/preferences`), reached from the account menu —
// which is what plan/28 §4 said in the first place.
//
// What survives here is a reviewer's tool: the showcase renders every component
// in every state, and flipping themes without leaving the page is the whole
// point of that page. It ships nowhere near production (`import.meta.env.DEV`
// gates the route).
//
// A native `<select>` rather than a custom menu, for three reasons: it is
// keyboard-operable and screen-reader-labelled without any of it being written
// here, it follows `color-scheme` so its own popup is drawn in the theme being
// chosen, and a custom listbox would be the fifth thing in this ticket needing
// focus management.
//
// Only the two shipped themes appear. The other three have values in the table
// and pass every test, but they have no browser acceptance and no layout
// variant, so offering them would claim more than was verified (ADR 0027 §5).
//
// Switching a theme changes no authorization, interrupts no session and rebuilds
// no terminal (`NFR-006.AC-07`, `FR-TERM-001.AC-15`). It writes one string to
// localStorage and sets one attribute.

import { SHIPPED_THEME_IDS, type ShippedThemeId } from "../../theme/themes";
import { usePreferencesStore } from "../../stores/preferences";

const preferences = usePreferencesStore();

const LABELS: Record<ShippedThemeId, string> = {
  graphite: "石墨（深色）",
  porcelain: "明亮（淺色）",
};

function onChange(event: Event): void {
  preferences.setTheme(
    (event.target as HTMLSelectElement).value as ShippedThemeId,
  );
}
</script>

<template>
  <label class="theme">
    <!-- A visible label, not a placeholder option: the control has to say what
         it is even after a value is chosen. -->
    <span class="sr-only">視覺主題</span>
    <select :value="preferences.theme" aria-label="視覺主題" @change="onChange">
      <option v-for="id in SHIPPED_THEME_IDS" :key="id" :value="id">
        {{ LABELS[id] }}
      </option>
    </select>
  </label>
</template>

<style scoped>
.theme {
  display: inline-flex;
}
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip-path: inset(50%);
  white-space: nowrap;
}
select {
  min-height: var(--density-control);
  padding: 0 8px;
  border: 1px solid var(--border-control);
  border-radius: var(--radius-control);
  background: var(--surface-raised);
  color: var(--text-primary);
  font-size: 12px;
}
</style>
