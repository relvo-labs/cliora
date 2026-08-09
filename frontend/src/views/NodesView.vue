<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";

import { ApiError } from "../api/client";
import { ACTION_NODE_MANAGE } from "../api/dto";
import AppLayout from "../components/layout/AppLayout.vue";
import AsyncState from "../components/common/AsyncState.vue";
import ConfirmDialog from "../components/common/ConfirmDialog.vue";
import StatusBadge from "../components/common/StatusBadge.vue";
import { useAsyncResource } from "../composables/useAsyncResource";
import { useAuthStore } from "../stores/auth";
import { useNodesStore } from "../stores/nodes";
import { useSessionsStore } from "../stores/sessions";
import { formatInstant } from "../utils/time";

const auth = useAuthStore();
const nodes = useNodesStore();
const sessions = useSessionsStore();
const router = useRouter();

const canManage = computed(() => auth.hasPermission(ACTION_NODE_MANAGE));
const resource = useAsyncResource(() => nodes.fetchList(), {
  isEmpty: (list) => list.length === 0,
});

const actingId = ref<string | null>(null);
const actionError = ref("");
const removeTarget = ref<{ id: string; name: string } | null>(null);

// Fold a post-mutation empty list back into the empty state.
const displayState = computed(() =>
  resource.state.value === "success" && nodes.list.length === 0
    ? "empty"
    : resource.state.value,
);

// Fleet-health caption mapped onto the shared UI-contract states (offline /
// stale / partial). Precedence: any offline node, else any degraded node, else
// an online node still missing a runtime (partial detection). Per-row status is
// carried by StatusBadge; this surfaces the same states at the list level.
const fleetNote = computed<"offline" | "stale" | "partial" | null>(() => {
  if (displayState.value !== "success") {
    return null;
  }
  if (nodes.list.some((node) => node.status === "offline")) {
    return "offline";
  }
  if (nodes.list.some((node) => node.status === "degraded")) {
    return "stale";
  }
  if (
    nodes.list.some(
      (node) =>
        node.status === "online" &&
        (!node.claude_available || !node.codex_available),
    )
  ) {
    return "partial";
  }
  return null;
});

onMounted(() => resource.run());

async function toggleEnabled(id: string, enable: boolean): Promise<void> {
  actingId.value = id;
  actionError.value = "";
  try {
    await nodes.setEnabled(id, enable);
  } catch (caught) {
    actionError.value =
      caught instanceof ApiError ? caught.message : "Action failed.";
  } finally {
    actingId.value = null;
  }
}

async function confirmRemove(): Promise<void> {
  if (!removeTarget.value) {
    return;
  }
  const id = removeTarget.value.id;
  actingId.value = id;
  actionError.value = "";
  try {
    await nodes.remove(id);
    sessions.removeForNode(id);
    removeTarget.value = null;
  } catch (caught) {
    actionError.value =
      caught instanceof ApiError ? caught.message : "Remove failed.";
  } finally {
    actingId.value = null;
  }
}

function open(id: string): void {
  void router.push({ name: "node-detail", params: { id } });
}
</script>

<template>
  <AppLayout>
    <header class="head">
      <div>
        <h1>Nodes</h1>
        <p>Every host connected to this control plane.</p>
      </div>
      <button
        class="ghost"
        :disabled="resource.state.value === 'loading'"
        @click="resource.run()"
      >
        Refresh
      </button>
    </header>

    <p v-if="actionError" class="banner" role="alert">{{ actionError }}</p>

    <AsyncState v-if="displayState === 'loading'" state="loading"
      >Loading nodes…</AsyncState
    >
    <AsyncState v-else-if="displayState === 'forbidden'" state="forbidden">
      You do not have permission to view nodes.
    </AsyncState>
    <AsyncState v-else-if="displayState === 'error'" state="error">
      Could not load nodes.
      <button class="link" @click="resource.run()">Retry</button>
    </AsyncState>
    <AsyncState v-else-if="displayState === 'empty'" state="empty">
      No nodes yet. Create an enrollment token to install one.
    </AsyncState>

    <AsyncState
      v-if="fleetNote === 'offline'"
      state="offline"
      class="fleet-note"
    >
      部分節點目前離線，狀態欄顯示各節點最後在線時間。
    </AsyncState>
    <AsyncState
      v-else-if="fleetNote === 'stale'"
      state="stale"
      class="fleet-note"
    >
      部分節點為降級 (Degraded) 狀態，資料可能不是最新。
    </AsyncState>
    <AsyncState
      v-else-if="fleetNote === 'partial'"
      state="partial"
      class="fleet-note"
    >
      部分線上節點的 runtime 尚未全部偵測到 (Claude / Codex)。
    </AsyncState>

    <div v-if="displayState === 'success'" class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Node</th>
            <th>Status</th>
            <th>Hostname</th>
            <th>OS</th>
            <th>Claude</th>
            <th>Codex</th>
            <th>Sessions</th>
            <th>Last seen</th>
            <th v-if="canManage" class="actions-col">Actions</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="node in nodes.list" :key="node.id">
            <td>
              <button class="name" @click="open(node.id)">
                {{ node.name }}
              </button>
            </td>
            <td><StatusBadge :status="node.status" /></td>
            <td>{{ node.hostname }}</td>
            <td>{{ node.os ?? "—" }}</td>
            <td>{{ node.claude_available ? "Ready" : "—" }}</td>
            <td>{{ node.codex_available ? "Ready" : "—" }}</td>
            <td>{{ node.session_count }}</td>
            <td :title="node.last_seen_at ?? ''">
              {{ formatInstant(node.last_seen_at) }}
            </td>
            <td v-if="canManage" class="actions-col">
              <button class="link" @click="open(node.id)">View</button>
              <button
                v-if="node.status === 'disabled'"
                class="link"
                :disabled="actingId === node.id"
                @click="toggleEnabled(node.id, true)"
              >
                Enable
              </button>
              <button
                v-else
                class="link"
                :disabled="actingId === node.id"
                @click="toggleEnabled(node.id, false)"
              >
                Disable
              </button>
              <button
                class="link danger"
                :disabled="actingId === node.id"
                @click="removeTarget = { id: node.id, name: node.name }"
              >
                Remove
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <ConfirmDialog
      :open="removeTarget !== null"
      :busy="actingId === removeTarget?.id"
      danger
      title="Remove node"
      :message="`Remove ${removeTarget?.name}? All active sessions and tunnels on it will end and leave the fleet lists. Their historical records and audit trail are retained. The credential is revoked, the node id cannot be reused, and the machine must re-enrol to reconnect.`"
      confirm-label="Remove node"
      @confirm="confirmRemove"
      @cancel="removeTarget = null"
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
.ghost {
  padding: 8px 14px;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  background: var(--surface-default);
  color: var(--text-secondary);
}
.banner {
  margin: 0 0 16px;
  padding: 10px 12px;
  border-radius: var(--radius-sm);
  background: #f9eaea;
  color: var(--status-error);
  font-size: 13px;
}
.fleet-note {
  margin-bottom: 16px;
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
.actions-col {
  text-align: right;
}
.link {
  padding: 4px 8px;
  border: 0;
  background: none;
  color: var(--action-primary);
  font-weight: 600;
}
.link.danger {
  color: var(--status-error);
}
.link:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
