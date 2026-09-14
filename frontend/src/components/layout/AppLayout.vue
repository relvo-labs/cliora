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

import { useBreakpoint } from "../../composables/useBreakpoint";
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
//
// The widths themselves are no longer written here (plan/29 MS-01): they lived
// in three files that had already drifted apart by 76px, so they now have one
// owner.
const { isNarrow, belowWide } = useBreakpoint();
// Automatic below 1440, and the user's choice above it. Not the other way
// round: at 1024 an expanded rail costs the terminal 144px of width, and that
// is a measurement rather than a preference.
const collapsed = computed(() => preferences.navCollapsed || belowWide.value);

// Software keyboards do not shrink `100dvh` (plan/29 MS-02). `visualViewport`
// is the only thing that reports the height actually left over, so the shell —
// which owns the window's height and is the only place that does (plan/09 D1) —
// owns this dimension too. A second owner here would recreate exactly the 16px
// disagreement plan/09 removed.
//
// Non-persistent by construction: it is a style property on the root element,
// never a store, never storage. If the browser has no `visualViewport` the
// property is never set at all, so `var(--viewport-usable-height, 100dvh)`
// falls back rather than being handed a guess.
//
// Deliberately NOT combined with `env(safe-area-inset-bottom)` here:
// `visualViewport.height` already excludes the keyboard but its treatment of
// the home indicator differs by platform and has not been measured yet
// (plan/29 MS-OM-03). Subtracting both would cut a strip that is not there. The
// bottom inset is applied by whichever element actually sits against the
// bottom edge.
const USABLE_HEIGHT = "--viewport-usable-height";
let viewport: VisualViewport | undefined;
function syncUsableHeight(): void {
  if (!viewport) return;
  document.documentElement.style.setProperty(
    USABLE_HEIGHT,
    `${viewport.height}px`,
  );
}
onMounted(() => {
  viewport = window.visualViewport ?? undefined;
  if (!viewport) return;
  syncUsableHeight();
  viewport.addEventListener("resize", syncUsableHeight);
  // `scroll` as well as `resize`: iOS reports a keyboard-driven change by
  // scrolling the visual viewport, not by resizing it.
  viewport.addEventListener("scroll", syncUsableHeight);
});
onBeforeUnmount(() => {
  if (!viewport) return;
  viewport.removeEventListener("resize", syncUsableHeight);
  viewport.removeEventListener("scroll", syncUsableHeight);
  // Removed, not left behind: the login page has no shell, and a stale height
  // from the last session would size it.
  document.documentElement.style.removeProperty(USABLE_HEIGHT);
  viewport = undefined;
});

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
        sessions-first
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
  /* Three layers, each the fallback for the one after it. 100vh is the floor;
     dvh also tracks a collapsing mobile URL bar, which style.md §24's narrow
     breakpoints meet; and --viewport-usable-height is the only one of the three
     that shrinks when a software keyboard opens (plan/29 MS-02). A browser that
     does not set the custom property simply keeps the dvh answer. */
  height: 100vh;
  height: 100dvh;
  height: var(--viewport-usable-height, 100dvh);
  /* Top and sides only. The bottom inset belongs to whatever actually touches
     the bottom edge, because subtracting it here as well as inside
     visualViewport's answer would remove the same strip twice (MS-OM-03). */
  padding-top: env(safe-area-inset-top, 0px);
  padding-left: env(safe-area-inset-left, 0px);
  padding-right: env(safe-area-inset-right, 0px);
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
  /* The scrim is not a scrollable surface, and on touch a drag over it would
     otherwise scroll the page underneath while the menu is open. */
  touch-action: none;
  overscroll-behavior: contain;
}
.menu-panel {
  position: fixed;
  inset: 0 auto 0 0;
  z-index: 26;
  width: min(280px, 86vw);
  box-shadow: var(--shadow-overlay);
  /* Its own insets, not the shell's: `position: fixed` takes it out of the
     shell's padding box entirely, so without these it runs under the notch at
     the top and the home indicator at the bottom (plan/29 MS-03). This is also
     an element that touches the bottom edge, which under MS-02 is exactly who
     is supposed to apply the bottom inset. */
  padding-top: env(safe-area-inset-top, 0px);
  padding-bottom: env(safe-area-inset-bottom, 0px);
  padding-left: env(safe-area-inset-left, 0px);
  /* Seven items plus a brand can exceed a short landscape viewport once the
     insets are added, and a nav you cannot reach the bottom of is a nav with
     missing items. */
  overflow-y: auto;
  /* Stops the scroll chaining to the page behind. `overscroll-behavior` rather
     than `position: fixed` on the body: the shell's `main` is the app's one
     scrolling container, and pinning the body would throw away its scroll
     position on every open. */
  overscroll-behavior: contain;
}
.menu-panel :deep(.rail) {
  height: 100%;
}
</style>
