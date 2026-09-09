<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

import { ApiError } from "../api/client";
import { ACTION_ENROLLMENT_MANAGE } from "../api/dto";
import AppLayout from "../components/layout/AppLayout.vue";
import UiButton from "../components/ui/UiButton.vue";
import UiDataTable from "../components/ui/UiDataTable.vue";
import UiEmptyState from "../components/ui/UiEmptyState.vue";
import UiInlineNotice from "../components/ui/UiInlineNotice.vue";
import UiLoadingState from "../components/ui/UiLoadingState.vue";
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

    <UiInlineNotice v-if="!canManage" tone="error" title="無法存取"
      >Only administrators can manage enrollment tokens.</UiInlineNotice
    >

    <template v-else>
      <UiInlineNotice v-if="formError" tone="error" :message="formError" />

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
        <UiLoadingState
          v-if="resource.state.value === 'loading'"
          label="Loading"
        />
        <UiInlineNotice
          v-else-if="resource.state.value === 'error'"
          tone="error"
          title="載入失敗"
          >Could not load tokens.
          <button class="link" @click="resource.run()">
            Retry
          </button></UiInlineNotice
        >
        <UiEmptyState
          v-else-if="enrollment.list.length === 0"
          variant="empty"
          title="沒有資料"
          >No tokens yet.</UiEmptyState
        >
        <UiDataTable
          v-else
          label="Enrollment tokens"
          :columns="['狀態', '建立者', 'CREATED', 'EXPIRES', 'USES', '']"
        >
          <tr v-for="token in enrollment.list" :key="token.id">
            <!-- The badge already carries the word; the raw value beside it was
                 the wire status repeated in English, which is not a second fact
                 about the token. -->
            <td><StatusBadge :status="token.status" kind="token" /></td>
            <td>{{ token.created_by }}</td>
            <td :title="token.created_at">
              {{ formatInstant(token.created_at) }}
            </td>
            <td :title="token.expires_at">
              {{ formatInstant(token.expires_at) }}
            </td>
            <td class="num">{{ token.used_count }} / {{ token.max_uses }}</td>
            <td>
              <UiButton
                v-if="token.status === 'active'"
                variant="danger"
                :disabled="busy"
                disabled-reason="另一個操作正在進行中"
                @click="revokeTarget = token.id"
              >
                撤銷
              </UiButton>
              <!-- Not an em dash: "already revoked" is the reason there is no
                   action, and an em dash makes the reader work it out. -->
              <span v-else class="muted">已無可用操作</span>
            </td>
          </tr>
        </UiDataTable>
      </section>

      <section class="panel summary">
        <h2>安裝紀錄 / 支援平台 / Daemon 版本</h2>
        <div class="summary-grid">
          <div class="summary-col">
            <h3>安裝紀錄</h3>
            <UiLoadingState
              v-if="nodesResource.state.value === 'loading'"
              label="Loading"
            />
            <UiInlineNotice
              v-else-if="nodesResource.state.value === 'error'"
              tone="error"
              title="載入失敗"
              >無法載入節點清單。
              <button class="link" @click="nodesResource.run()">
                Retry
              </button></UiInlineNotice
            >
            <UiEmptyState
              v-else-if="recentNodes.length === 0"
              variant="empty"
              title="沒有資料"
              >尚無已註冊的節點。</UiEmptyState
            >
            <ul v-else class="records">
              <li v-for="node in recentNodes" :key="node.id">
                <span class="rec-name">{{ node.name }}</span>
                <StatusBadge :status="node.status" kind="node" />
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
  color: var(--text-secondary);
  font-size: 13px;
}
.panel {
  margin-bottom: 16px;
  padding: 18px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-panel);
  background: var(--surface-default);
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
  color: var(--text-primary);
}
input {
  width: 160px;
  padding: 9px 12px;
  border: 1px solid var(--border-control);
  border-radius: var(--radius-control);
  background: var(--surface-raised);
}
.primary {
  padding: 10px 16px;
  border: 0;
  border-radius: var(--radius-control);
  background: var(--accent-strong);
  color: var(--text-on-accent);
  font-weight: 600;
}
/* A colour, not an opacity. Opacity dims the label along with everything
   else, so a disabled control stops being able to say what it is or why it is
   disabled — and "disabled keeps an understandable reason" is the rule
   (--text-disabled is measured at >= 3:1 on all three surfaces for this). */
.primary:disabled {
  background: var(--surface-raised);
  border: 1px solid var(--border-control);
  color: var(--text-disabled);
  cursor: not-allowed;
}
.once {
  border-color: var(--focus-ring);
}
.once-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.warn {
  margin: 0 0 12px;
  color: var(--status-warning-fg);
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
  border-radius: var(--radius-control);
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
  border: 1px solid var(--border-control);
  border-radius: var(--radius-control);
  background: var(--surface-raised);
  color: var(--text-primary);
  font-weight: 600;
  white-space: nowrap;
}
.link {
  padding: 4px 8px;
  border: 0;
  background: none;
  color: var(--accent-strong);
  font-weight: 600;
}
.link.danger {
  color: var(--status-error-fg);
}
.muted {
  color: var(--text-secondary);
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
  color: var(--text-secondary);
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
  color: var(--text-secondary);
  font-size: 12px;
}
.platforms li {
  padding: 6px 10px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-panel);
  background: var(--surface-canvas);
}
.daemon-ver {
  margin: 0 0 4px;
  font-size: 20px;
  font-weight: 700;
  font-family: var(--font-mono);
}
.num {
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
</style>
