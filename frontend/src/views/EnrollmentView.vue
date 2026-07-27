<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

import { ApiError } from "../api/client";
import {
  ACTION_ENROLLMENT_MANAGE,
  type EnrollmentTokenStatus,
} from "../api/dto";
import AppLayout from "../components/layout/AppLayout.vue";
import AsyncState from "../components/common/AsyncState.vue";
import ConfirmDialog from "../components/common/ConfirmDialog.vue";
import StatusBadge from "../components/common/StatusBadge.vue";
import { useAsyncResource } from "../composables/useAsyncResource";
import { useAuthStore } from "../stores/auth";
import { useEnrollmentStore } from "../stores/enrollment";
import { useNodesStore } from "../stores/nodes";
import { formatInstant } from "../utils/time";

const auth = useAuthStore();
const enrollment = useEnrollmentStore();
const nodesStore = useNodesStore();

const canManage = computed(() => auth.hasPermission(ACTION_ENROLLMENT_MANAGE));
const resource = useAsyncResource(() => enrollment.fetchList());
// Install records reuse the nodes list; summaries carry no registered_at, so
// recency is ordered by last-seen and that is what the column reports.
const nodesResource = useAsyncResource(() => nodesStore.fetchList());

// PRD §10.7 install summary. Platforms are the P1 supported matrix; the daemon
// version falls back to a static current build when no node reports one.
const SUPPORTED_PLATFORMS = [
  "Ubuntu 22.04 LTS",
  "Ubuntu 24.04 LTS",
  "Debian 12",
  "amd64 / arm64",
];
const CURRENT_DAEMON_VERSION = "0.1.0";

const recentNodes = computed(() =>
  [...nodesStore.list]
    .sort((a, b) => (b.last_seen_at ?? "").localeCompare(a.last_seen_at ?? ""))
    .slice(0, 5),
);
const daemonVersion = computed(() => CURRENT_DAEMON_VERSION);

const ttlMinutes = ref(60);
const maxUses = ref(1);
const busy = ref(false);
const formError = ref("");
const copied = ref("");
const revokeTarget = ref<string | null>(null);

// Map token lifecycle to the shared badge palette (colour + text, not colour alone).
const BADGE: Record<EnrollmentTokenStatus, string> = {
  active: "online",
  expired: "offline",
  exhausted: "disabled",
  revoked: "error",
};

const serverUrl = computed(() => window.location.origin);
const installCommand = computed(() => {
  const token = enrollment.lastCreated?.token ?? "";
  return (
    `curl -fsSL ${serverUrl.value}/api/install-script | sudo bash -s -- ` +
    `--server ${serverUrl.value} --token ${token} --name <node-name> --user <user>`
  );
});

onMounted(() => {
  if (canManage.value) {
    void resource.run();
    void nodesResource.run();
  }
});

async function create(): Promise<void> {
  busy.value = true;
  formError.value = "";
  try {
    await enrollment.create({
      ttl_seconds: Math.max(1, Math.round(ttlMinutes.value * 60)),
      max_uses: Math.max(1, Math.round(maxUses.value)),
    });
  } catch (caught) {
    formError.value =
      caught instanceof ApiError ? caught.message : "Could not create token.";
  } finally {
    busy.value = false;
  }
}

async function copy(text: string, label: string): Promise<void> {
  try {
    await navigator.clipboard?.writeText(text);
    copied.value = label;
    window.setTimeout(() => (copied.value = ""), 1800);
  } catch {
    copied.value = "";
  }
}

async function confirmRevoke(): Promise<void> {
  if (!revokeTarget.value) {
    return;
  }
  busy.value = true;
  formError.value = "";
  try {
    await enrollment.revoke(revokeTarget.value);
    revokeTarget.value = null;
  } catch (caught) {
    formError.value =
      caught instanceof ApiError ? caught.message : "Could not revoke token.";
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <AppLayout>
    <header class="head">
      <h1>Enrollment</h1>
      <p>Issue one-time tokens to install and register new nodes.</p>
    </header>

    <AsyncState v-if="!canManage" state="forbidden">
      Only administrators can manage enrollment tokens.
    </AsyncState>

    <template v-else>
      <p v-if="formError" class="banner" role="alert">{{ formError }}</p>

      <section class="panel create">
        <h2>Create a token</h2>
        <form @submit.prevent="create">
          <label>
            Expires in (minutes)
            <input v-model.number="ttlMinutes" type="number" min="1" />
          </label>
          <label>
            Max uses
            <input v-model.number="maxUses" type="number" min="1" />
          </label>
          <button class="primary" type="submit" :disabled="busy">
            Generate token
          </button>
        </form>
      </section>

      <section
        v-if="enrollment.lastCreated"
        class="panel once"
        aria-live="polite"
      >
        <div class="once-head">
          <h2>Token created</h2>
          <button class="link" @click="enrollment.dismissCreated()">
            Dismiss
          </button>
        </div>
        <p class="warn">
          Copy it now — the plaintext token is shown only once.
        </p>
        <div class="copyrow">
          <code>{{ enrollment.lastCreated.token }}</code>
          <button
            class="ghost"
            @click="copy(enrollment.lastCreated.token, 'token')"
          >
            {{ copied === "token" ? "Copied" : "Copy" }}
          </button>
        </div>
        <label class="cmd-label">One-line install command</label>
        <div class="copyrow">
          <code class="cmd">{{ installCommand }}</code>
          <button class="ghost" @click="copy(installCommand, 'command')">
            {{ copied === "command" ? "Copied" : "Copy" }}
          </button>
        </div>
      </section>

      <section class="panel">
        <h2>Tokens</h2>
        <AsyncState v-if="resource.state.value === 'loading'" state="loading"
          >Loading…</AsyncState
        >
        <AsyncState v-else-if="resource.state.value === 'error'" state="error">
          Could not load tokens.
          <button class="link" @click="resource.run()">Retry</button>
        </AsyncState>
        <AsyncState v-else-if="enrollment.list.length === 0" state="empty">
          No tokens yet.
        </AsyncState>
        <div v-else class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Status</th>
                <th>建立者</th>
                <th>Created</th>
                <th>Expires</th>
                <th>Uses</th>
                <th class="actions-col">Actions</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="token in enrollment.list" :key="token.id">
                <td>
                  <StatusBadge :status="BADGE[token.status]" />{{ " "
                  }}<span class="stext">{{ token.status }}</span>
                </td>
                <td>{{ token.created_by }}</td>
                <td :title="token.created_at">
                  {{ formatInstant(token.created_at) }}
                </td>
                <td :title="token.expires_at">
                  {{ formatInstant(token.expires_at) }}
                </td>
                <td>{{ token.used_count }} / {{ token.max_uses }}</td>
                <td class="actions-col">
                  <button
                    v-if="token.status === 'active'"
                    class="link danger"
                    :disabled="busy"
                    @click="revokeTarget = token.id"
                  >
                    Revoke
                  </button>
                  <span v-else class="muted">—</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="panel summary">
        <h2>安裝紀錄 / 支援平台 / Daemon 版本</h2>
        <div class="summary-grid">
          <div class="summary-col">
            <h3>安裝紀錄</h3>
            <AsyncState
              v-if="nodesResource.state.value === 'loading'"
              state="loading"
              >Loading…</AsyncState
            >
            <AsyncState
              v-else-if="nodesResource.state.value === 'error'"
              state="error"
            >
              無法載入節點清單。
              <button class="link" @click="nodesResource.run()">Retry</button>
            </AsyncState>
            <AsyncState v-else-if="recentNodes.length === 0" state="empty">
              尚無已註冊的節點。
            </AsyncState>
            <ul v-else class="records">
              <li v-for="node in recentNodes" :key="node.id">
                <span class="rec-name">{{ node.name }}</span>
                <StatusBadge :status="node.status" />
                <time :title="node.last_seen_at ?? ''" class="rec-time">
                  最後在線 {{ formatInstant(node.last_seen_at) }}
                </time>
              </li>
            </ul>
          </div>

          <div class="summary-col">
            <h3>支援平台</h3>
            <ul class="platforms">
              <li v-for="platform in SUPPORTED_PLATFORMS" :key="platform">
                {{ platform }}
              </li>
            </ul>
          </div>

          <div class="summary-col">
            <h3>Daemon 版本</h3>
            <p class="daemon-ver">{{ daemonVersion }}</p>
            <p class="muted">安裝腳本提供之目前建置版本。</p>
          </div>
        </div>
      </section>
    </template>

    <ConfirmDialog
      :open="revokeTarget !== null"
      :busy="busy"
      danger
      title="Revoke token"
      message="Revoke this enrollment token? Any host that has not yet used it will no longer be able to enrol."
      confirm-label="Revoke"
      @confirm="confirmRevoke"
      @cancel="revokeTarget = null"
    />
  </AppLayout>
</template>

<style scoped>
.head {
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
.banner {
  margin: 0 0 16px;
  padding: 10px 12px;
  border-radius: var(--radius-sm);
  background: #f9eaea;
  color: var(--status-error);
  font-size: 13px;
}
.panel {
  margin-bottom: 16px;
  padding: 18px;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  background: var(--surface-elevated);
}
.panel h2 {
  margin: 0 0 14px;
  font-size: 14px;
}
.create form {
  display: flex;
  align-items: flex-end;
  gap: 14px;
  flex-wrap: wrap;
}
label {
  display: grid;
  gap: 6px;
  font-size: 12px;
  color: var(--text-secondary);
}
input {
  width: 160px;
  padding: 9px 12px;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  background: var(--surface-default);
}
.primary {
  padding: 10px 16px;
  border: 0;
  border-radius: var(--radius-sm);
  background: var(--action-primary);
  color: var(--text-inverse);
  font-weight: 600;
}
.primary:disabled {
  opacity: 0.7;
}
.once {
  border-color: var(--border-focus);
}
.once-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.warn {
  margin: 0 0 12px;
  color: var(--status-busy);
  font-size: 13px;
}
.copyrow {
  display: flex;
  gap: 10px;
  align-items: stretch;
  margin-bottom: 12px;
}
.copyrow code {
  flex: 1;
  padding: 10px 12px;
  overflow-x: auto;
  border-radius: var(--radius-sm);
  background: var(--surface-canvas);
  font-size: 12px;
  white-space: pre;
}
.cmd-label {
  display: block;
  margin-bottom: 6px;
}
.ghost {
  padding: 8px 14px;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  background: var(--surface-default);
  color: var(--text-secondary);
  font-weight: 600;
  white-space: nowrap;
}
.table-wrap {
  overflow-x: auto;
}
table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
th,
td {
  padding: 10px 12px;
  text-align: left;
  border-bottom: 1px solid var(--border-default);
  white-space: nowrap;
}
th {
  color: var(--text-muted);
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.stext {
  text-transform: capitalize;
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
.muted {
  color: var(--text-muted);
  font-size: 12px;
}
.summary-grid {
  display: grid;
  gap: 20px;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
}
.summary-col h3 {
  margin: 0 0 10px;
  font-size: 12px;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.records,
.platforms {
  margin: 0;
  padding: 0;
  list-style: none;
  display: grid;
  gap: 10px;
  font-size: 13px;
}
.records li {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.rec-name {
  font-weight: 600;
}
.rec-time {
  color: var(--text-muted);
  font-size: 12px;
}
.platforms li {
  padding: 6px 10px;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  background: var(--surface-canvas);
}
.daemon-ver {
  margin: 0 0 4px;
  font-size: 20px;
  font-weight: 700;
  font-family: var(--font-mono, monospace);
}
</style>
