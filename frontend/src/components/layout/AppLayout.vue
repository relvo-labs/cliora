<script setup lang="ts">
import { computed } from "vue";
import { RouterLink, useRouter } from "vue-router";

import { ACTION_AUDIT_VIEW, ACTION_ENROLLMENT_MANAGE } from "../../api/dto";
import { useAuthStore } from "../../stores/auth";
import { useFavoritesStore } from "../../stores/favorites";

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
    <main><slot /></main>
  </div>
</template>

<style scoped>
.shell > header {
  position: fixed;
  z-index: 3;
  inset: 0 0 auto;
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
  position: fixed;
  z-index: 2;
  top: var(--layout-header);
  bottom: 0;
  width: var(--layout-sidebar);
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
.shell > main {
  min-height: 100vh;
  margin-left: var(--layout-sidebar);
  padding: calc(var(--layout-header) + 24px) 28px 40px;
}
@media (max-width: 900px) {
  .shell > aside {
    width: 64px;
  }
  .shell > aside span {
    display: none;
  }
  .shell > main {
    margin-left: 64px;
  }
}
</style>
