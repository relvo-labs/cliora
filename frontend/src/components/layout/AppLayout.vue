<script setup lang="ts">
import { computed } from "vue";
import { RouterLink, useRouter } from "vue-router";

import {
  ACTION_AUDIT_VIEW,
  ACTION_ENROLLMENT_MANAGE,
  ACTION_INTEGRATION_MANAGE,
  ACTION_PROJECT_VIEW,
  FEATURE_PROJECTS,
} from "../../api/dto";
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
// Platform-level third-party settings: Admin only, and hidden for everyone else so the rail
// does not offer a page that answers 403 (ADR 0022).
const canManageIntegrations = computed(() =>
  auth.hasPermission(ACTION_INTEGRATION_MANAGE),
);
// Two independent conditions, ANDed: `features` says whether this *deployment* has
// the project layer, `permissions` whether this *person* may see it. Neither alone
// is authorization — the server refuses regardless (ADR 0027).
const showProjects = computed(
  () =>
    auth.hasFeature(FEATURE_PROJECTS) &&
    auth.hasPermission(ACTION_PROJECT_VIEW),
);

interface NavEntry {
  kind: "link" | "group";
  label: string;
  icon?: string;
  route?: string;
}

// Built as data rather than as `v-if`s in the template, because there are two
// arrangements and they differ in *order*, not only in membership.
//
// With the project layer off, the rail must be the pre-V2 rail exactly — same six
// entries, same order, no group rule. "Regrouped minus one row" is not the same
// thing as "unchanged", and the flag-off screenshot baseline compares against the
// latter (plan/16 exit condition 6).
const entries = computed<NavEntry[]>(() => {
  const infrastructure: NavEntry[] = [
    { kind: "link", label: "Dashboard", icon: "◈", route: "dashboard" },
    { kind: "link", label: "Nodes", icon: "▣", route: "nodes" },
    ...(canManageEnrollment.value
      ? [
          {
            kind: "link" as const,
            label: "Enrollment",
            icon: "◉",
            route: "enrollment",
          },
        ]
      : []),
    ...(canViewAudit.value
      ? [{ kind: "link" as const, label: "Audit", icon: "☰", route: "audit" }]
      : []),
    ...(canManageIntegrations.value
      ? [
          {
            kind: "link" as const,
            label: "Integrations",
            icon: "⇄",
            route: "integrations",
          },
        ]
      : []),
  ];

  const sessions: NavEntry = {
    kind: "link",
    label: "Sessions",
    icon: "▷",
    route: "sessions",
  };

  if (!showProjects.value) {
    // The original flat rail, in its original order.
    return [
      infrastructure[0],
      infrastructure[1],
      sessions,
      ...infrastructure.slice(2),
    ];
  }

  // `Projects` and `Sessions` are single-entry groups, so they render as plain rows
  // — a heading whose only child repeats it is two rows saying one thing. Only
  // `Infrastructure` is genuinely two levels.
  return [
    { kind: "link", label: "Projects", icon: "▦", route: "projects" },
    sessions,
    { kind: "group", label: "Infrastructure" },
    ...infrastructure,
  ];
});

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
      <!--
        Three groups, and the grouping is the *only* thing that changed: every
        existing href is byte-identical, so bookmarks and the e2e suite still
        resolve (ADR 0027, plan/16 D11).

        `Projects` and `Sessions` are single-entry groups, so they render as plain
        rows with no heading — a heading whose only child repeats it is two rows
        saying one thing. Only `Infrastructure` is genuinely two levels, and it is
        a divider with a small label rather than an indented block: children stay
        flush left, which measured 147px at the widest against a 208px rail (61px
        of headroom) and leaves room for the `Agents` entry V2.2 adds.

        The group is never collapsible. Persisting that state, handling "the
        current route is inside a collapsed group" and animating it is not worth
        it for an eight-row rail.
      -->
      <nav aria-label="Primary">
        <template v-for="entry in entries" :key="entry.label">
          <p v-if="entry.kind === 'group'" class="group" data-nav-group>
            {{ entry.label }}
          </p>
          <RouterLink v-else :to="{ name: entry.route }">
            {{ entry.icon }} <span>{{ entry.label }}</span>
          </RouterLink>
        </template>
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
/* A divider with a label, not an indented block. Children stay flush left, so the
 * hierarchy costs one row of height and no width — which is what keeps the rail at
 * 208px while V2.2 adds a sixth entry underneath (plan/16 §1.3). */
nav .group {
  margin: 10px 0 2px;
  padding: 8px 11px 0;
  border-top: 1px solid var(--border-default);
  color: var(--text-muted);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.04em;
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
  /* The rail collapses to icons here, and a 64px column has no room for a word.
   * The rule stays a divider, so the grouping survives without the label — the
   * alternative, letting it wrap, would push every icon below it out of line. */
  nav .group {
    padding: 8px 0 0;
    font-size: 0;
  }
}
</style>
