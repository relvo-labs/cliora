<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

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
const route = useRoute();
const router = useRouter();

const canCreate = computed(() => auth.hasPermission(ACTION_SESSION_CREATE));
const dialogOpen = ref(false);

// Prefill carried in the query string, which is how a project's binding list opens
// this dialog on a specific node and directory (ProjectDetailView). A query string
// rather than a store: it survives a reload and can be linked to, and the dialog
// stays a component that takes props rather than one that reaches into a store to
// discover why it was opened.
//
// Reading it is what makes that button do anything at all. Without this the push
// lands here and the query is silently ignored — a control that appears to work.
const prefill = computed(() => {
  const asString = (value: unknown): string | undefined =>
    typeof value === "string" && value !== "" ? value : undefined;
  const found = {
    projectId: asString(route.query.project_id),
    nodeId: asString(route.query.node_id),
    workspace: asString(route.query.workspace),
  };
  return found.projectId || found.nodeId || found.workspace ? found : undefined;
});

const resource = useAsyncResource(() => sessions.fetchList(), {
  isEmpty: (list) => list.length === 0,
});

const displayState = computed(() =>
  resource.state.value === "success" && sessions.list.length === 0
    ? "empty"
    : resource.state.value,
);

onMounted(() => {
  void resource.run();
  // Arriving with a prefill means the user already pressed a button that said
  // "open a session here"; making them press "New session" again would be asking
  // twice for one intent.
  if (prefill.value && canCreate.value) dialogOpen.value = true;
});

function open(id: string): void {
  void router.push({ name: "session-workspace", params: { id } });
}

function onCreated(session: SessionDetail): void {
  dialogOpen.value = false;
  open(session.id);
}

function closeDialog(): void {
  dialogOpen.value = false;
  // Drop the prefill from the URL on cancel, so pressing "New session" afterwards
  // opens an empty dialog rather than silently reusing a dismissed intent.
  if (prefill.value) void router.replace({ name: "sessions" });
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
            <th>Project</th>
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
            <td :title="s.project_id ?? 'Ad-hoc'">
              {{ s.project_id ? s.project_id.slice(0, 8) : "Ad-hoc" }}
            </td>
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
      :prefill="prefill"
      @created="onCreated"
      @cancel="closeDialog"
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
