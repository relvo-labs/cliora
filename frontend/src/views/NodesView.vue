<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";

import { ApiError } from "../api/client";
import { ACTION_NODE_MANAGE } from "../api/dto";
import AppLayout from "../components/layout/AppLayout.vue";
import UiActionMenu from "../components/ui/UiActionMenu.vue";
import UiButton from "../components/ui/UiButton.vue";
import UiDataTable from "../components/ui/UiDataTable.vue";
import UiEmptyState from "../components/ui/UiEmptyState.vue";
import UiInlineNotice from "../components/ui/UiInlineNotice.vue";
import UiLoadingState from "../components/ui/UiLoadingState.vue";
import ConfirmDialog from "../components/common/ConfirmDialog.vue";
import StatusBadge from "../components/common/StatusBadge.vue";
import { useAsyncResource } from "../composables/useAsyncResource";
import { useAuthStore } from "../stores/auth";
import { useNodesStore } from "../stores/nodes";
import { formatInstant } from "../utils/time";

const auth = useAuthStore();
const nodes = useNodesStore();
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

    <UiInlineNotice v-if="actionError" tone="error" :message="actionError" />

    <UiLoadingState v-if="displayState === 'loading'" label="Loading nodes" />
    <UiInlineNotice
      v-else-if="displayState === 'forbidden'"
      tone="error"
      title="無法存取"
      >You do not have permission to view nodes.</UiInlineNotice
    >
    <UiInlineNotice
      v-else-if="displayState === 'error'"
      tone="error"
      title="載入失敗"
      >Could not load nodes.
      <button class="link" @click="resource.run()">
        Retry
      </button></UiInlineNotice
    >
    <UiEmptyState
      v-else-if="displayState === 'empty'"
      variant="empty"
      title="沒有資料"
      >No nodes yet. Create an enrollment token to install one.</UiEmptyState
    >

    <UiInlineNotice
      v-if="fleetNote === 'offline'"
      class="fleet-note"
      tone="warning"
      title="來源目前離線"
      >部分節點目前離線，狀態欄顯示各節點最後在線時間。</UiInlineNotice
    >
    <UiInlineNotice
      v-else-if="fleetNote === 'stale'"
      class="fleet-note"
      tone="stale"
      title="資料可能不是最新"
      >部分節點為降級 (Degraded) 狀態，資料可能不是最新。</UiInlineNotice
    >
    <UiInlineNotice
      v-else-if="fleetNote === 'partial'"
      class="fleet-note"
      tone="stale"
      title="部分資料無法取得"
      >部分線上節點的 runtime 尚未全部偵測到 (Claude / Codex)。</UiInlineNotice
    >

    <UiDataTable
      v-if="displayState === 'success'"
      label="Nodes"
      :columns="
        canManage
          ? [
              'NODE / HOSTNAME',
              '狀態',
              'OS',
              'RUNTIME',
              'SESSIONS',
              '最後在線',
              '',
            ]
          : ['NODE / HOSTNAME', '狀態', 'OS', 'RUNTIME', 'SESSIONS', '最後在線']
      "
    >
      <tr v-for="node in nodes.list" :key="node.id">
        <td>
          <UiButton variant="quiet" @click="open(node.id)">
            {{ node.name }}
          </UiButton>
          <!-- The hostname as a second line rather than a second column, for
               the same reason paths are: its longest value would otherwise set
               the column width. -->
          <small>{{ node.hostname }}</small>
        </td>
        <td><StatusBadge :status="node.status" kind="node" /></td>
        <td>{{ node.os ?? "無資料" }}</td>
        <td class="runtimes">
          <!-- Runtime availability as two named badges rather than two columns
               of "Ready" or an em dash. "—" in a column headed Claude does not
               say whether the runtime is missing or the node never reported. -->
          <StatusBadge
            :status="node.claude_available ? 'available' : 'unavailable'"
            kind="runtime"
          />
          <span class="rt-name">Claude</span>
          <StatusBadge
            :status="node.codex_available ? 'available' : 'unavailable'"
            kind="runtime"
          />
          <span class="rt-name">Codex</span>
        </td>
        <td class="num">{{ node.session_count }}</td>
        <td :title="node.last_seen_at ?? ''">
          {{ formatInstant(node.last_seen_at) }}
        </td>
        <td v-if="canManage">
          <!-- Behind a menu: Remove used to sit inline in every row, one pixel
               from View. Same permission check, same actions. -->
          <UiActionMenu :label="`${node.name} 的操作`">
            <template #default="{ close }">
              <button
                type="button"
                @click="
                  close();
                  open(node.id);
                "
              >
                查看節點
              </button>
              <button
                v-if="node.status === 'disabled'"
                type="button"
                :disabled="actingId === node.id"
                @click="
                  close();
                  toggleEnabled(node.id, true);
                "
              >
                啟用
              </button>
              <button
                v-else
                type="button"
                :disabled="actingId === node.id"
                @click="
                  close();
                  toggleEnabled(node.id, false);
                "
              >
                停用
              </button>
              <button
                type="button"
                data-danger
                :disabled="actingId === node.id"
                @click="
                  close();
                  removeTarget = { id: node.id, name: node.name };
                "
              >
                移除節點…
              </button>
            </template>
          </UiActionMenu>
        </td>
      </tr>
    </UiDataTable>

    <ConfirmDialog
      :open="removeTarget !== null"
      :busy="actingId === removeTarget?.id"
      danger
      title="Remove node"
      :message="`Remove ${removeTarget?.name}? The node record and its audit history are kept (soft delete) and its credential is revoked. The node id can never be reused, and it must re-enrol to reconnect.`"
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
  color: var(--text-secondary);
  font-size: 13px;
}
.ghost {
  padding: 8px 14px;
  border: 1px solid var(--border-control);
  border-radius: var(--radius-control);
  background: var(--surface-raised);
  color: var(--text-primary);
}
.fleet-note {
  margin-bottom: 16px;
}
.runtimes {
  display: flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
}
.rt-name {
  color: var(--text-secondary);
  font-size: 11px;
  margin-right: 6px;
}
.num {
  font-variant-numeric: tabular-nums;
}
</style>
