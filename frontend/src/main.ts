// Stylesheet order matters: tokens define the custom properties base.css and every
// scoped component style consume, so it must load first. There is deliberately no
// global class stylesheet — the prototype's was retired in P4-07.
//
// The theme attribute is already on <html> by the time this module runs:
// public/theme-boot.js set it before first paint (ADR 0027 §4). What is left for
// here is the part that needs the stored preference *resolved* — `color-scheme`
// and `theme-color` on the OS-preference path, where the boot script sets no
// attribute at all by design.
import "@xterm/xterm/css/xterm.css";
import "./theme/tokens.css";
import "./theme/base.css";
import { createApp } from "vue";
import { createPinia } from "pinia";
import App from "./App.vue";
import { createAppRouter } from "./router";
import { installAuthStorageSync } from "./stores/auth";
import {
  installPreferencesStorageSync,
  installViewportThemeSync,
  usePreferencesStore,
} from "./stores/preferences";

const app = createApp(App);
app.use(createPinia());
installAuthStorageSync();
usePreferencesStore().init();
// Personal settings are their own page, so a theme change happens in whichever
// tab is showing that page. Without this, a tab holding a live session would
// keep the old colours until it was reloaded — and reloading is exactly what a
// theme switch promises not to require.
installPreferencesStorageSync();
// Rotating a phone or dragging a window across 768px changes which theme is
// painted (plan/29 MS-20). Same reason as the line above: a live session must
// recolour without a reload.
installViewportThemeSync();
app.use(createAppRouter());
app.mount("#app");
