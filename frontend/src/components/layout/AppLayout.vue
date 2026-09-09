<script setup lang="ts">
// The app shell. It owns the window's height, and it is the *only* place that
// does (plan/09 D1) — that part is unchanged and load-bearing.
//
// What plan/28 adds:
//
//   * The rail collapses. Manually at any width, and automatically below
//     1440px. Automatic collapse existed before at 900px; the difference is
//     that the user can now override it, and the choice persists.
//   * A skip link, as the shell's first focusable element. Without it the
//     keyboard route from the address bar to the terminal runs through six nav
//     items and the account menu, every single time.
//   * Below 768px the rail becomes a menu overlay rather than a 64px column,
//     because at that width a 64px column plus a terminal is not a layout.
//
// The status bar is deliberately NOT a third row here. Its content — session
// state, browser connection, control — only means anything on the session
// workspace; the other ten pages have no session to report on. As a shell row
// it would either render an empty 28px on ten pages or require the shell to
// know which route is current, and a shell that knows about routes has started
// to know about the business. It belongs to the workspace page (style.md §9 was
// revised to say so).

import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { Menu, X } from "lucide-vue-next";

import { useFocusTrap } from "../../composables/useFocusTrap";
import { useAuthStore } from "../../stores/auth";
import { useFavoritesStore } from "../../stores/favorites";
import { usePreferencesStore } from "../../stores/preferences";
import UiIconButton from "../ui/UiIconButton.vue";
import UiToastHost from "../ui/UiToastHost.vue";
import AccountMenu from "./AccountMenu.vue";
import PrimaryNav from "./PrimaryNav.vue";

// `fill`: this view *is* a fixed layout that owns the viewport (the Session
// Workspace), so main must not scroll and must not spend the generous padding a
// table page wants. Anything that scrolls does so inside the view's own panels.
defineProps<{ fill?: boolean }>();

const auth = useAuthStore();
const favorites = useFavoritesStore();
const preferences = usePreferencesStore();
const router = useRouter();

const productName =
  (import.meta.env.VITE_PRODUCT_NAME as string | undefined) ?? "Cliora";

// Three layout modes rather than two. `narrow` is not "collapsed but smaller":
// a 64px rail beside a terminal at 390px leaves the terminal 326px, so the rail
// goes away entirely and comes back as an overlay.
const width = ref(typeof window === "undefined" ? 1440 : window.innerWidth);
function onResize(): void {
  width.value = window.innerWidth;
}
onMounted(() => window.addEventListener("resize", onResize));
onBeforeUnmount(() => window.removeEventListener("resize", onResize));

const isNarrow = computed(() => width.value < 768);
// Automatic below 1440, and the user's choice above it. Not the other way
// round: at 1024 an expanded rail costs the terminal 144px of width, and that
// is a measurement rather than a preference.
const collapsed = computed(
  () => preferences.navCollapsed || width.value < 1440,
);

const menuOpen = ref(false);
const menuPanel = ref<HTMLElement>();

// The narrow-viewport menu is an overlay, so it owes the same three things a
// dialog does: contain focus while it is open, close on Escape, and hand focus
// back to the button that opened it. Same composable as the file drawer —
// writing this twice is how one of the two ends up missing a piece.
useFocusTrap(menuPanel, menuOpen, { onEscape: () => (menuOpen.value = false) });

async function logout(): Promise<void> {
  await auth.logout();
  // Favourites are per-user workspace paths held in memory. Without this, signing
  // in as someone else on the same page load would briefly show the previous
  // user's paths before the next fetch replaced them.
  favorites.clear();
  await router.push({ name: "login" });
}
</script>

<template>
  <div
    class="shell"
    :data-collapsed="collapsed ? '' : undefined"
    :data-narrow="isNarrow ? '' : undefined"
  >
    <!-- First focusable element in the document. -->
    <a class="skip-link" href="#main">跳至主要內容</a>
    <header>
      <UiIconButton
        v-if="isNarrow"
        class="menu-toggle"
        :label="menuOpen ? '關閉主導覽' : '開啟主導覽'"
        :expanded="menuOpen"
        controls="primary-nav"
        @click="menuOpen = !menuOpen"
      >
        <X v-if="menuOpen" />
        <Menu v-else />
      </UiIconButton>
      <span v-if="isNarrow" class="header-brand">{{ productName }}</span>
      <div class="spacer" />
      <!-- Personal settings live behind the account menu, not in the header.
           A theme is a global preference; a permanent header control makes it
           read as something that applies to the page you happen to be on, and
           it left the other three preferences with nowhere to live. -->
      <AccountMenu
        v-if="auth.user"
        :display-name="auth.user.display_name"
        :role="auth.user.role"
        @logout="logout"
      />
    </header>
    <!-- Not `v-if` on the desktop rail: it stays in the grid so its column
         width is what the collapse animates, and so nothing inside it is
         unmounted by a resize. -->
    <PrimaryNav
      v-if="!isNarrow"
      :collapsed="collapsed"
      :product-name="productName"
      @update:collapsed="preferences.setNavCollapsed($event)"
    />
    <main id="main" :data-fill="fill ? '' : undefined"><slot /></main>

    <!-- Narrow-viewport navigation. `position: fixed; inset: 0` rather than any
         viewport-unit height: plan/09 D1 keeps viewport height in the shell
         alone, and an overlay that names 100dvh is a second source of it. -->
    <div
      v-if="isNarrow && menuOpen"
      class="menu-scrim"
      @click="menuOpen = false"
    />
    <div v-if="isNarrow && menuOpen" ref="menuPanel" class="menu-panel">
      <!-- :collapsible="false" — the rail is already at full width here, so a
           collapse control would be a button that does nothing. -->
      <PrimaryNav
        :collapsed="false"
        :collapsible="false"
        :product-name="productName"
        @update:collapsed="() => {}"
      />
    </div>

    <UiToastHost />
  </div>
</template>

<style scoped>
/* The shell owns the window's height, and it is the *only* place that does.
 * Before plan/09 the header and the rail were `position: fixed` and main made
 * room for them with padding, which left main's height implicit — every view
 * that wanted to fill the window had to re-derive it, and
 * SessionWorkspaceView's derivation disagreed by 16px, so the workspace grew a
 * permanent page scrollbar. A grid gives main a definite height instead, so a
 * view only needs `height: 100%` (plan/09 D1). */
.shell {
  display: grid;
  /* minmax(0, 1fr), not 1fr: `1fr`'s floor is `auto`, so one wide child (Monaco,
     a wide table) would push the column past the viewport — the horizontal
     overflow plan/08 locked down. */
  grid-template-columns: var(--layout-sidebar) minmax(0, 1fr);
  /* `auto` rather than var(--layout-header) for the header row: its content
     wraps on a narrow window, and a fixed row height would let it spill over
     main — invisible while it was `fixed`, obvious now. The header keeps its own
     height, so the row is 56px in the normal case. */
  grid-template-rows: auto minmax(0, 1fr);
  /* 100vh first as the fallback: dvh also tracks a collapsing mobile URL bar,
     which style.md §24's narrow breakpoints meet. */
  height: 100vh;
  height: 100dvh;
}
.shell[data-collapsed] {
  grid-template-columns: var(--layout-sidebar-collapsed) minmax(0, 1fr);
}
/* Below 768px the rail is gone from the grid entirely, so main gets the width. */
.shell[data-narrow] {
  grid-template-columns: minmax(0, 1fr);
}
@media (prefers-reduced-motion: no-preference) {
  .shell {
    transition: grid-template-columns var(--motion-base) ease;
  }
}

.shell > header {
  grid-column: 1 / -1;
  height: var(--layout-header);
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0 16px;
  background: var(--surface-default);
  border-bottom: 1px solid var(--border-subtle);
}
.header-brand {
  font-weight: 650;
  font-size: 15px;
}
.spacer {
  flex: 1;
}

/* The one scrolling container in the app. The header and the rail no longer
 * scroll away with the content, and no view has to leave room for them. */
.shell > main {
  min-height: 0;
  overflow: auto;
  padding: 24px 28px 40px;
}
@media (max-width: 1439px) {
  .shell > main {
    padding: 18px 20px 32px;
  }
}
@media (max-width: 767px) {
  .shell > main {
    padding: 14px 14px 24px;
  }
}
/* Fill mode. `hidden` rather than `auto` on purpose: a fill page has no page
 * scroll at all, so a panel that miscalculates its height shows up as visible
 * clipping instead of "the page can be scrolled a little" — which is exactly how
 * the 16px discrepancy this replaces managed to survive. The narrow padding is
 * not cosmetic either: every 8px here is a row of terminal (style.md §12/§18). */
.shell > main[data-fill] {
  overflow: hidden;
  padding: 12px 16px;
  display: grid;
  grid-template-rows: minmax(0, 1fr);
}

.menu-scrim {
  position: fixed;
  inset: 0;
  z-index: 25;
  background: var(--surface-scrim);
}
.menu-panel {
  position: fixed;
  inset: 0 auto 0 0;
  z-index: 26;
  width: min(280px, 86vw);
  box-shadow: var(--shadow-overlay);
}
.menu-panel :deep(.rail) {
  height: 100%;
}
</style>
