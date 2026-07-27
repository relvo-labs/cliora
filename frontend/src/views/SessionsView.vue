<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";

import { ACTION_SESSION_CREATE } from "../api/dto";
import type { SessionDetail } from "../api/dto";
import AppLayout from "../components/layout/AppLayout.vue";
import AsyncState from "../components/common/AsyncState.vue";
import StatusBadge from "../components/common/StatusBadge.vue";
import NewSessionDialog from "../components/session/NewSessionDialog.vue";
import { useAsyncResource } from "../composables/useAsyncResource";
import { useAuthStore } from "../stores/auth";
import { useSessionsStore } from "../stores/sessions";
import { formatInstant } from "../utils/time";

const auth = useAuthStore();
const sessions = useSessionsStore();
const router = useRouter();

const canCreate = computed(() => auth.hasPermission(ACTION_SESSION_CREATE));
const dialogOpen = ref(false);

const resource = useAsyncResource(() => sessions.fetchList(), {
  isEmpty: (list) => list.length === 0,
});

const displayState = computed(() =>
  resource.state.value === "success" && sessions.list.length === 0
    ? "empty"
    : resource.state.value,
);

onMounted(() => resource.run());

function open(id: string): void {
  void router.push({ name: "session-workspace", params: { id } });
}

function onCreated(session: SessionDetail): void {
  dialogOpen.value = false;
  open(session.id);
}
</script>

<template>
  <AppLayout>
    <header class="head">
      <div>
        <h1>Sessions</h1>
        <p>CLI sessions running across your nodes.</p>
      </div>
      <div class="head-actions">
        <button
          class="ghost"
          :disabled="resource.state.value === 'loading'"
          @click="resource.run()"
        >
          Refresh
        </button>
        <button v-if="canCreate" class="primary" @click="dialogOpen = true">
          New session
        </button>
      </div>
    </header>

    <AsyncState v-if="displayState === 'loading'" state="loading"
      >Loading sessions…</AsyncState
    >
    <AsyncState v-else-if="displayState === 'forbidden'" state="forbidden">
      You do not have permission to view sessions.
    </AsyncState>
    <AsyncState v-else-if="displayState === 'error'" state="error">
      Could not load sessions.
      <button class="link" @click="resource.run()">Retry</button>
    </AsyncState>
    <AsyncState v-else-if="displayState === 'empty'" state="empty">
      No sessions yet.
      <span v-if="canCreate">Start one with “New session”.</span>
    </AsyncState>

    <div v-if="displayState === 'success'" class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Name</th>
            <th>Runtime</th>
            <th>Workspace</th>
            <th>Status</th>
            <th>Started</th>
            <th>Last activity</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="s in sessions.list" :key="s.id">
            <td>
              <button class="name" @click="open(s.id)">{{ s.name }}</button>
            </td>
            <td>{{ s.runtime }}</td>
            <td class="path" :title="s.workspace">{{ s.workspace }}</td>
            <td><StatusBadge :status="s.status" /></td>
            <td :title="s.started_at ?? ''">
              {{ formatInstant(s.started_at) }}
            </td>
            <td :title="s.last_activity_at ?? ''">
              {{ formatInstant(s.last_activity_at) }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <NewSessionDialog
      :open="dialogOpen"
      @created="onCreated"
      @cancel="dialogOpen = false"
    />
  </AppLayout>
</template>

<style scoped>
.head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  margin-bottom: 20px;
}
.head h1 {
  margin: 0;
  font-size: 24px;
}
.head p {
  margin: 4px 0 0;
  color: var(--text-muted);
  font-size: 13px;
}
.head-actions {
  display: flex;
  gap: 10px;
}
.ghost,
.primary {
  padding: 8px 14px;
  border-radius: var(--radius-sm);
  font-weight: 600;
}
.ghost {
  border: 1px solid var(--border-default);
  background: var(--surface-default);
  color: var(--text-secondary);
}
.primary {
  border: 0;
  background: var(--action-primary);
  color: var(--text-inverse);
}
.table-wrap {
  overflow-x: auto;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  background: var(--surface-elevated);
}
table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
th,
td {
  padding: 12px 14px;
  text-align: left;
  border-bottom: 1px solid var(--border-default);
  white-space: nowrap;
}
th {
  color: var(--text-muted);
  font-weight: 600;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
tbody tr:last-child td {
  border-bottom: 0;
}
.name {
  padding: 0;
  border: 0;
  background: none;
  color: var(--action-primary);
  font-weight: 600;
}
.path {
  max-width: 280px;
  overflow: hidden;
  text-overflow: ellipsis;
}
.link {
  border: 0;
  background: none;
  color: var(--action-primary);
  font-weight: 600;
}
</style>
