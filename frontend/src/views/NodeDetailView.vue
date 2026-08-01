<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";

import { ApiError } from "../api/client";
import { ACTION_INTEGRATION_MANAGE, ACTION_NODE_MANAGE } from "../api/dto";
import AppLayout from "../components/layout/AppLayout.vue";
import AsyncState from "../components/common/AsyncState.vue";
import ConfirmDialog from "../components/common/ConfirmDialog.vue";
import StatusBadge from "../components/common/StatusBadge.vue";
import {
  deriveNodeState,
  useAsyncResource,
} from "../composables/useAsyncResource";
import { api, useAuthStore } from "../stores/auth";
import { useNodesStore } from "../stores/nodes";
import { formatDuration, formatInstant } from "../utils/time";

const props = defineProps<{ id: string }>();

const auth = useAuthStore();
const nodes = useNodesStore();
const router = useRouter();

const canManage = computed(() => auth.hasPermission(ACTION_NODE_MANAGE));
const canManageIntegration = computed(() =>
  auth.hasPermission(ACTION_INTEGRATION_MANAGE),
);
const resource = useAsyncResource(() => nodes.fetchNode(props.id));
const node = computed(() => nodes.current);

// Derived UI-contract state (offline / stale / partial) layered on top of the
// request lifecycle once the node is loaded, so those AsyncState affordances
// actually surface. Null means the node is healthy (plain success).
const derived = computed(() =>
  node.value ? deriveNodeState(node.value.status, node.value.runtimes) : null,
);

// cpu/memory/disk are reported as percentages (heartbeat schema: number ≥ 0).
function formatPercent(value: number | null): string {
  return value === null || !Number.isFinite(value)
    ? "—"
    : `${value.toFixed(1)}%`;
}

function formatLoad(value: number | null): string {
  return value === null || !Number.isFinite(value) ? "—" : value.toFixed(2);
}

const busy = ref(false);
const actionError = ref("");
const confirm = ref<"disable" | "enable" | "remove" | null>(null);

// --- Daemon update (P4-10) ---
const updateTarget = ref("");
const updateBusy = ref(false);
const updateError = ref("");
const updateNotice = ref("");

// Versions offered in the picker: distinct versions from the release manifest. The
// node's own architecture decides which artifact the daemon downloads, so the list
// is by version rather than by artifact.
const availableVersions = computed(() => [
  ...new Set((nodes.releases?.artifacts ?? []).map((a) => a.version)),
]);

// The stable `UPDATE_*` code is only meaningful on a failure; on success
// `last_result` just repeats the status.
const showLastResult = computed(() => {
  const status = node.value?.update_status;
  return Boolean(
    status?.last_result && status.last_result !== "succeeded" && status.status,
  );
});

const UPDATE_STATE_LABELS: Record<string, string> = {
  in_progress: "進行中",
  succeeded: "成功",
  failed: "失敗",
  rolled_back: "已回復（更新失敗，已還原舊版）",
  unknown: "結果不明",
};

function updateStateLabel(status: string): string {
  return UPDATE_STATE_LABELS[status] ?? status;
}

// --- Port forwarding summary (P11). The full page is /nodes/:id/tunnels. ---
// `disabled` is a first-class outcome, not a failure: with the integration off the routes
// answer 404, and the section says so rather than showing an error nobody can act on.
const tunnelSummary = ref<
  "loading" | "ok" | "disabled" | "forbidden" | "error"
>("loading");
const tunnelCount = ref(0);

async function loadTunnelSummary(): Promise<void> {
  try {
    tunnelCount.value = (await api().listTunnels({ node_id: props.id })).length;
    tunnelSummary.value = "ok";
  } catch (caught) {
    if (
      caught instanceof ApiError &&
      caught.code === "TUNNEL_INTEGRATION_DISABLED"
    ) {
      tunnelSummary.value = "disabled";
    } else if (caught instanceof ApiError && caught.status === 403) {
      tunnelSummary.value = "forbidden";
    } else {
      tunnelSummary.value = "error";
    }
  }
}

onMounted(async () => {
  await resource.run();
  await loadTunnelSummary();
  // Best-effort: a Central without published releases still renders the page, it
  // just has nothing to offer in the picker.
  try {
    await nodes.fetchReleases();
  } catch {
    /* the picker shows "nothing published" */
  }
});

async function runUpdate(): Promise<void> {
  if (!updateTarget.value) {
    return;
  }
  updateBusy.value = true;
  updateError.value = "";
  updateNotice.value = "";
  try {
    const updated = await nodes.requestUpdate(props.id, {
      target_version: updateTarget.value,
    });
    // A 200 does not mean it finished: the daemon restarts mid-update, so
    // `in_progress` is a legitimate, non-error outcome and the page must say so
    // rather than implying success.
    updateNotice.value =
      updated.update_status.status === "in_progress"
        ? "已送出更新要求。Daemon 會在重啟後回報結果；現有 tmux session 不受影響。"
        : `更新結果：${updateStateLabel(updated.update_status.status ?? "unknown")}`;
  } catch (caught) {
    updateError.value =
      caught instanceof ApiError ? caught.message : "無法送出更新要求。";
  } finally {
    updateBusy.value = false;
  }
}

async function runAction(): Promise<void> {
  if (!confirm.value || !node.value) {
    return;
  }
  const action = confirm.value;
  busy.value = true;
  actionError.value = "";
  try {
    if (action === "remove") {
      await nodes.remove(props.id);
      await router.push({ name: "nodes" });
    } else {
      await nodes.setEnabled(props.id, action === "enable");
    }
    confirm.value = null;
  } catch (caught) {
    actionError.value =
      caught instanceof ApiError ? caught.message : "Action failed.";
  } finally {
    busy.value = false;
  }
}

const confirmMessage = computed(() => {
  if (confirm.value === "remove") {
    return "The node record and audit history are kept (soft delete) and its credential is revoked. The node id can never be reused.";
  }
  if (confirm.value === "disable") {
    return "The daemon stays connected but new operations are rejected until it is re-enabled.";
  }
  return "The node will accept operations again.";
});
</script>

<template>
  <AppLayout>
    <button class="back" @click="router.push({ name: 'nodes' })">
      ← Nodes
    </button>

    <AsyncState v-if="resource.state.value === 'loading'" state="loading"
      >Loading node…</AsyncState
    >
    <AsyncState
      v-else-if="resource.state.value === 'forbidden'"
      state="forbidden"
    >
      You do not have permission to view this node.
    </AsyncState>
    <AsyncState
      v-else-if="resource.state.value === 'error' || !node"
      state="error"
    >
      Could not load this node.
      <button class="link" @click="resource.run()">Retry</button>
    </AsyncState>

    <template v-else>
      <header class="head">
        <div>
          <h1>{{ node.name }}</h1>
          <p>{{ node.hostname }}</p>
        </div>
        <StatusBadge :status="node.status" />
        <div v-if="canManage" class="actions">
          <button
            v-if="node.status === 'disabled'"
            class="ghost"
            @click="confirm = 'enable'"
          >
            Enable
          </button>
          <button v-else class="ghost" @click="confirm = 'disable'">
            Disable
          </button>
          <button class="danger" @click="confirm = 'remove'">Remove</button>
        </div>
      </header>

      <p v-if="actionError" class="banner" role="alert">{{ actionError }}</p>

      <AsyncState v-if="derived === 'offline'" state="offline" class="derived">
        節點目前離線，以下為最後一次 heartbeat 的資料，最後在線
        {{ formatInstant(node.last_seen_at) }}。
      </AsyncState>
      <AsyncState v-else-if="derived === 'stale'" state="stale" class="derived">
        節點為降級 (Degraded) 狀態，資料可能不是最新，最後在線
        {{ formatInstant(node.last_seen_at) }}。
      </AsyncState>
      <AsyncState
        v-else-if="derived === 'partial'"
        state="partial"
        class="derived"
      >
        部分 runtime 偵測失敗，詳見下方 Runtimes 逐項狀態。
      </AsyncState>

      <div class="grid">
        <section class="panel">
          <h2>System</h2>
          <dl>
            <div>
              <dt>OS</dt>
              <dd>{{ node.os_version ?? node.os ?? "—" }}</dd>
            </div>
            <div>
              <dt>Architecture</dt>
              <dd>{{ node.architecture ?? "—" }}</dd>
            </div>
            <div>
              <dt>Run user</dt>
              <dd>{{ node.run_user ?? "—" }}</dd>
            </div>
            <div>
              <dt>Daemon version</dt>
              <dd>{{ node.daemon_version ?? "—" }}</dd>
            </div>
            <div>
              <dt>Registered</dt>
              <dd :title="node.registered_at">
                {{ formatInstant(node.registered_at) }}
              </dd>
            </div>
            <div>
              <dt>Last heartbeat</dt>
              <dd :title="node.last_seen_at ?? ''">
                {{ formatInstant(node.last_seen_at) }}
              </dd>
            </div>
            <div>
              <dt>Sessions</dt>
              <dd>{{ node.session_count }} (available in P2)</dd>
            </div>
          </dl>
        </section>

        <section class="panel">
          <h2>Runtimes</h2>
          <ul class="runtimes">
            <li v-for="rt in node.runtimes" :key="rt.runtime">
              <span class="rt-name">{{ rt.runtime }}</span>
              <StatusBadge :status="rt.available ? 'online' : 'offline'" />
              <span class="rt-ver">{{
                rt.available ? (rt.version ?? "detected") : "unavailable"
              }}</span>
            </li>
            <li v-if="node.runtimes.length === 0" class="muted">
              No runtimes reported.
            </li>
          </ul>
        </section>

        <section class="panel">
          <h2>Workspace roots</h2>
          <ul class="roots">
            <li v-for="root in node.workspace_roots" :key="root.path">
              <code>{{ root.path }}</code>
              <span v-if="!root.is_enabled" class="muted">(disabled)</span>
            </li>
            <li v-if="node.workspace_roots.length === 0" class="muted">
              None configured.
            </li>
          </ul>
        </section>

        <section class="panel">
          <h2>系統資源</h2>
          <AsyncState
            v-if="!node.resources"
            :state="node.status === 'offline' ? 'offline' : 'empty'"
          >
            {{
              node.status === "offline"
                ? "節點離線，暫無系統資源資料。"
                : "尚未收到系統資源樣本。"
            }}
          </AsyncState>
          <dl v-else>
            <div>
              <dt>CPU</dt>
              <dd>{{ formatPercent(node.resources.cpu_usage) }}</dd>
            </div>
            <div>
              <dt>Memory</dt>
              <dd>{{ formatPercent(node.resources.memory_usage) }}</dd>
            </div>
            <div>
              <dt>Disk</dt>
              <dd>{{ formatPercent(node.resources.disk_usage) }}</dd>
            </div>
            <div>
              <dt>Load average</dt>
              <dd>{{ formatLoad(node.resources.load_average) }}</dd>
            </div>
            <div>
              <dt>Daemon uptime</dt>
              <dd>{{ formatDuration(node.resources.daemon_uptime) }}</dd>
            </div>
          </dl>
        </section>

        <section class="panel">
          <h2>安裝與更新狀態</h2>
          <dl>
            <div>
              <dt>目前版本</dt>
              <dd>
                {{
                  node.update_status.current_version ??
                  node.daemon_version ??
                  "—"
                }}
              </dd>
            </div>
            <div>
              <dt>最新可用版本</dt>
              <dd>
                {{ node.update_status.latest_version ?? "尚未發佈任何版本" }}
              </dd>
            </div>
            <div>
              <dt>上次更新</dt>
              <!-- Null status means this node has never been asked to update — a
                   different fact from a successful update, and worth saying. -->
              <dd v-if="!node.update_status.status">尚未執行過更新</dd>
              <dd v-else>
                {{ updateStateLabel(node.update_status.status) }}
                <span v-if="node.update_status.target_version">
                  → {{ node.update_status.target_version }}
                </span>
                <code v-if="showLastResult">{{
                  node.update_status.last_result
                }}</code>
                <time
                  v-if="node.update_status.updated_at"
                  :datetime="node.update_status.updated_at"
                  :title="node.update_status.updated_at"
                >
                  （{{ formatInstant(node.update_status.updated_at) }}）
                </time>
              </dd>
            </div>
            <div>
              <dt>自動更新</dt>
              <!-- Not a limitation to fix later: MVP updates are explicitly
                   triggered, never scheduled (ADR 0017). -->
              <dd>停用（更新一律由人明確觸發）</dd>
            </div>
          </dl>

          <div v-if="canManage" class="update-actions">
            <label>
              <span>更新至</span>
              <!-- A select over the manifest, never a free-text field: the version
                   must be an allowlisted release, and there is deliberately no way
                   to name a URL or a file (SEC-002). -->
              <select v-model="updateTarget" :disabled="updateBusy">
                <option value="" disabled>選擇版本</option>
                <option
                  v-for="version in availableVersions"
                  :key="version"
                  :value="version"
                >
                  {{ version }}
                </option>
              </select>
            </label>
            <button
              class="primary"
              type="button"
              :disabled="!updateTarget || updateBusy"
              @click="runUpdate"
            >
              {{ updateBusy ? "更新中…" : "更新" }}
            </button>
            <p v-if="availableVersions.length === 0" class="hint">
              此 Central 尚未發佈任何 release，因此沒有可安裝的版本。
            </p>
            <p v-if="updateNotice" class="hint" role="status">
              {{ updateNotice }}
            </p>
            <p v-if="updateError" class="banner" role="alert">
              {{ updateError }}
              <a
                href="https://github.com/cliora/cliora/blob/main/docs/runbooks/update-failure.md"
                >update-failure runbook</a
              >
            </p>
          </div>
        </section>

        <!-- Port forwarding: a summary and a link, with the settings, list and create form on
             their own page (plan/11 PG-11). Shown even when the integration is off, because
             "why is this feature missing" is a question the page should answer rather than
             leave to a support conversation. -->
        <section class="panel">
          <h2>埠轉發</h2>
          <AsyncState v-if="tunnelSummary === 'disabled'" state="empty">
            埠轉發整合尚未啟用。
            <RouterLink
              v-if="canManageIntegration"
              :to="{ name: 'integrations' }"
            >
              前往整合設定
            </RouterLink>
          </AsyncState>
          <AsyncState
            v-else-if="tunnelSummary === 'forbidden'"
            state="forbidden"
          >
            你沒有檢視埠轉發的權限。
          </AsyncState>
          <template v-else>
            <dl>
              <div>
                <dt>目前的隧道</dt>
                <dd>{{ tunnelCount }}</dd>
              </div>
            </dl>
            <RouterLink
              class="link"
              :to="{ name: 'node-tunnels', params: { id: props.id } }"
            >
              管理埠轉發 →
            </RouterLink>
          </template>
        </section>

        <section class="panel">
          <h2>最近錯誤</h2>
          <AsyncState v-if="node.recent_errors.length === 0" state="empty">
            目前沒有回報的錯誤。
          </AsyncState>
          <ul v-else class="errors">
            <li v-for="(err, i) in node.recent_errors" :key="i">
              <time :datetime="err.occurred_at" :title="err.occurred_at">
                {{ formatInstant(err.occurred_at) }}
              </time>
              <span class="err-msg">{{ err.message }}</span>
            </li>
          </ul>
        </section>
      </div>
    </template>

    <ConfirmDialog
      :open="confirm !== null"
      :busy="busy"
      :danger="confirm === 'remove'"
      :title="
        confirm === 'remove'
          ? 'Remove node'
          : confirm === 'disable'
            ? 'Disable node'
            : 'Enable node'
      "
      :message="confirmMessage"
      :confirm-label="
        confirm === 'remove'
          ? 'Remove node'
          : confirm === 'disable'
            ? 'Disable'
            : 'Enable'
      "
      @confirm="runAction"
      @cancel="confirm = null"
    />
  </AppLayout>
</template>

<style scoped>
.back {
  margin-bottom: 16px;
  padding: 0;
  border: 0;
  background: none;
  color: var(--action-primary);
  font-weight: 600;
}
.head {
  display: flex;
  align-items: center;
  gap: 16px;
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
.head .actions {
  margin-left: auto;
  display: flex;
  gap: 10px;
}
.ghost,
.danger {
  padding: 8px 14px;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  background: var(--surface-default);
  color: var(--text-secondary);
  font-weight: 600;
}
.danger {
  border-color: var(--border-danger);
  color: var(--status-error);
}
.banner {
  margin: 0 0 16px;
  padding: 10px 12px;
  border-radius: var(--radius-sm);
  background: #f9eaea;
  color: var(--status-error);
  font-size: 13px;
}
.update-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: 10px;
  margin-top: 14px;
  padding-top: 14px;
  border-top: 1px solid var(--border-default);
}
.update-actions label {
  display: grid;
  gap: 4px;
  font-size: 12px;
}
.update-actions label span {
  color: var(--text-muted);
}
.update-actions select {
  padding: 6px 8px;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  background: var(--surface-default);
  color: var(--text-primary);
  font-size: 13px;
}
.update-actions .primary {
  padding: 8px 14px;
  border: 0;
  border-radius: var(--radius-sm);
  background: var(--action-primary);
  color: var(--text-inverse);
  font-weight: 600;
}
.update-actions .primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.hint {
  flex-basis: 100%;
  margin: 0;
  color: var(--text-muted);
  font-size: 12px;
}
.update-actions .banner {
  flex-basis: 100%;
  margin: 0;
}
.grid {
  display: grid;
  gap: 16px;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
}
.panel {
  padding: 18px;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  background: var(--surface-elevated);
}
.panel h2 {
  margin: 0 0 12px;
  font-size: 14px;
}
dl {
  margin: 0;
  display: grid;
  gap: 10px;
}
dl div {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  font-size: 13px;
}
dt {
  color: var(--text-muted);
}
dd {
  margin: 0;
  text-align: right;
}
.runtimes,
.roots {
  margin: 0;
  padding: 0;
  list-style: none;
  display: grid;
  gap: 10px;
  font-size: 13px;
}
.runtimes li {
  display: flex;
  align-items: center;
  gap: 10px;
}
.rt-name {
  width: 64px;
  text-transform: capitalize;
  font-weight: 600;
}
.rt-ver {
  color: var(--text-muted);
}
.muted {
  color: var(--text-muted);
}
.derived {
  margin-bottom: 16px;
}
.errors {
  margin: 0;
  padding: 0;
  list-style: none;
  display: grid;
  gap: 10px;
  font-size: 13px;
}
.errors li {
  display: grid;
  gap: 2px;
}
.errors time {
  color: var(--text-muted);
  font-size: 12px;
}
.err-msg {
  color: var(--status-error);
}
.link {
  padding: 0 6px;
  border: 0;
  background: none;
  color: var(--action-primary);
  font-weight: 600;
}
</style>
