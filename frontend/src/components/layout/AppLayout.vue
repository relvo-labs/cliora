<script setup lang="ts">
import { computed } from "vue";
import { RouterLink, useRouter } from "vue-router";

import { ACTION_AUDIT_VIEW, ACTION_ENROLLMENT_MANAGE } from "../../api/dto";
import { useAuthStore } from "../../stores/auth";
import { useFavoritesStore } from "../../stores/favorites";

// `fill`: this view *is* a fixed layout that owns the viewport (the Session
// Workspace), so main must not scroll and must not spend the generous padding a
// table page wants. Anything that scrolls does so inside the view's own panels.
defineProps<{ fill?: boolean }>();

const auth = useAuthStore();
const favorites = useFavoritesStore();
const router = useRouter();

const productName =
  (import.meta.env.VITE_PRODUCT_NAME as string | undefined) ?? "Cliora";
const canManageEnrollment = computed(() =>
  auth.hasPermission(ACTION_ENROLLMENT_MANAGE),
);
// Hiding the entry is a courtesy for roles that cannot use it; the server refuses
// the request regardless (ADR 0016).
const canViewAudit = computed(() => auth.hasPermission(ACTION_AUDIT_VIEW));

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
  <div class="shell">
    <header>
      <div class="brand">
        <span aria-hidden="true">◫</span>{{ productName }}
      </div>
      <div class="spacer" />
      <div v-if="auth.user" class="account">
        <span class="who">{{ auth.user.display_name }}</span>
        <span class="role">{{ auth.user.role }}</span>
        <button type="button" class="logout" @click="logout">Sign out</button>
      </div>
    </header>
    <aside>
      <nav aria-label="Primary">
        <RouterLink :to="{ name: 'dashboard' }"
          >◈ <span>Dashboard</span></RouterLink
        >
        <RouterLink :to="{ name: 'nodes' }">▣ <span>Nodes</span></RouterLink>
        <RouterLink :to="{ name: 'sessions' }"
          >▷ <span>Sessions</span></RouterLink
        >
        <RouterLink v-if="canManageEnrollment" :to="{ name: 'enrollment' }">
          ◉ <span>Enrollment</span>
        </RouterLink>
        <RouterLink v-if="canViewAudit" :to="{ name: 'audit' }">
          ☰ <span>Audit</span>
        </RouterLink>
      </nav>
    </aside>
    <main :data-fill="fill ? '' : undefined"><slot /></main>
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
     which style.md §24's read-only tablet mode will meet. */
  height: 100vh;
  height: 100dvh;
}
.shell > header {
  grid-column: 1 / -1;
  height: var(--layout-header);
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 0 20px;
  background: var(--surface-elevated);
  border-bottom: 1px solid var(--border-default);
}
.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  font-weight: 700;
}
.brand span {
  display: grid;
  width: 30px;
  height: 30px;
  place-items: center;
  border-radius: 7px;
  color: var(--text-inverse);
  background: var(--action-primary);
}
.spacer {
  flex: 1;
}
.account {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 13px;
}
.account .who {
  font-weight: 600;
}
.account .role {
  padding: 2px 8px;
  border-radius: 999px;
  background: var(--surface-canvas);
  color: var(--text-muted);
  font-size: 11px;
  text-transform: capitalize;
}
.logout {
  padding: 6px 12px;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  background: var(--surface-default);
  color: var(--text-secondary);
}
.logout:hover {
  border-color: var(--border-focus);
}
.shell > aside {
  /* Width comes from the grid column; height from the grid row. `overflow-y`
     keeps the nav reachable on a very short window. */
  min-height: 0;
  overflow-y: auto;
  padding: 16px 12px;
  background: var(--surface-elevated);
  border-right: 1px solid var(--border-default);
}
nav {
  display: grid;
  gap: 5px;
}
nav a {
  display: flex;
  gap: 11px;
  padding: 11px;
  border-radius: 8px;
  color: var(--text-secondary);
  text-decoration: none;
  font-size: 13px;
}
nav a.router-link-active {
  background: var(--surface-canvas);
  color: var(--action-primary);
  font-weight: 600;
}
/* The one scrolling container in the app. The header and the rail no longer
 * scroll away with the content, and no view has to leave room for them. */
.shell > main {
  min-height: 0;
  overflow: auto;
  padding: 24px 28px 40px;
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
@media (max-width: 900px) {
  .shell {
    grid-template-columns: 64px minmax(0, 1fr);
  }
  .shell > aside span {
    display: none;
  }
}
</style>
