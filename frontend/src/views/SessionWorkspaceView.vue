<script setup lang="ts">
import {
  computed,
  defineAsyncComponent,
  nextTick,
  onMounted,
  ref,
  watch,
} from "vue";
import { useRouter } from "vue-router";

import { ApiError } from "../api/client";
import type { SessionDetail } from "../api/dto";
import AppLayout from "../components/layout/AppLayout.vue";
import AsyncState from "../components/common/AsyncState.vue";
import ConfirmDialog from "../components/common/ConfirmDialog.vue";
import StatusBadge from "../components/common/StatusBadge.vue";
import FileTree from "../components/file/FileTree.vue";

// Monaco is a large dependency and only the preview needs it, so the pane (and
// with it the whole editor bundle) loads on the first file the user opens.
const PreviewPane = defineAsyncComponent(
  () => import("../components/file/PreviewPane.vue"),
);
import { useAsyncResource } from "../composables/useAsyncResource";
import { useTerminalSession } from "../composables/useTerminalSession";
import { api } from "../stores/auth";
import { useSessionsStore } from "../stores/sessions";

const props = defineProps<{ id: string }>();
const router = useRouter();
const sessions = useSessionsStore();

// Capabilities come from the session payload, computed server-side from the role
// *and* ownership (ADR 0016) — a Developer may see a colleague's session but not
// terminate or take it over, which a role-only check cannot express. Until the
// session loads, assume nothing.
const capabilities = computed(() => session.value?.capabilities);
const canTerminate = computed(() => capabilities.value?.can_terminate === true);
const canTakeover = computed(() => capabilities.value?.can_takeover === true);
const canBrowseFiles = computed(
  () => capabilities.value?.can_browse_files === true,
);

// The file panel keys off the session id; a null id (or a dead session) means it
// binds nothing and issues no request.
const filesSessionId = computed(() =>
  session.value?.id === props.id ? props.id : null,
);

// Workspace root label: the folder name only. The node's absolute workspace path
// never reaches the tree (P3 no-absolute-path rule).
const workspaceLabel = computed(() => {
  const path = session.value?.workspace ?? "";
  const parts = path.split("/").filter(Boolean);
  return parts.length ? parts[parts.length - 1] : "workspace";
});

// A session in a terminal state has no daemon-side workspace to browse.
const TERMINAL_STATUSES = new Set(["exited", "failed", "terminated"]);
const filesDisabledReason = computed(() =>
  session.value && TERMINAL_STATUSES.has(session.value.status)
    ? "Session 已結束，檔案瀏覽不再可用。"
    : undefined,
);

// The file currently open in the preview pane. Cleared when the tree clears
// (session switch) so no previous session's content stays on screen.
const previewPath = ref<string | null>(null);

const host = ref<HTMLElement | null>(null);
const terminateOpen = ref(false);
const actionError = ref("");
const busy = ref(false);

const resource = useAsyncResource<SessionDetail>(() =>
  sessions.fetchSession(props.id),
);

// The composable owns the xterm + socket; it mints a fresh single-use ws-ticket
// on every (re)connect via the API client.
const terminal = useTerminalSession((sessionId) =>
  api()
    .attachSession(sessionId)
    .then((res) => res.ticket),
);

const session = computed(() => sessions.current);

onMounted(async () => {
  await resource.run();
  if (resource.state.value === "success") {
    await nextTick();
    if (host.value) {
      terminal.mount(host.value);
      void terminal.connect(props.id);
    }
  }
});

// Switching to another session id re-attaches cleanly (dispose is handled by the
// composable's scope teardown on unmount; here we just reconnect).
watch(
  () => props.id,
  async (next, prev) => {
    if (next && next !== prev) {
      await resource.run();
      void terminal.connect(next);
    }
  },
);

async function confirmTerminate(): Promise<void> {
  busy.value = true;
  actionError.value = "";
  try {
    await sessions.terminate(props.id);
    terminateOpen.value = false;
  } catch (caught) {
    actionError.value =
      caught instanceof ApiError ? caught.message : "Terminate failed.";
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <AppLayout>
    <AsyncState v-if="resource.state.value === 'loading'" state="loading"
      >Loading session…</AsyncState
    >
    <AsyncState
      v-else-if="resource.state.value === 'forbidden'"
      state="forbidden"
    >
      You do not have permission to view this session.
    </AsyncState>
    <AsyncState
      v-else-if="resource.state.value === 'error' || !session"
      state="error"
    >
      Could not load this session.
      <button class="link" @click="resource.run()">Retry</button>
    </AsyncState>

    <div v-else class="workspace">
      <header class="head">
        <div class="meta">
          <h1>{{ session.name }}</h1>
          <span class="dim">{{ session.runtime }}</span>
          <span class="dim" :title="session.workspace">{{
            session.workspace
          }}</span>
          <StatusBadge :status="session.status" />
          <StatusBadge :status="terminal.status.value" />
          <span class="role" :data-role="terminal.role.value">{{
            terminal.role.value === "writer" ? "Writer" : "Viewer (read-only)"
          }}</span>
        </div>
        <div class="actions">
          <button
            v-if="canTakeover && terminal.role.value === 'viewer'"
            class="ghost"
            @click="terminal.takeover()"
          >
            Request control
          </button>
          <button
            v-if="terminal.canRetry.value"
            class="ghost"
            @click="terminal.retry()"
          >
            Reconnect
          </button>
          <button
            v-if="canTerminate"
            class="danger"
            :disabled="busy"
            @click="terminateOpen = true"
          >
            Terminate
          </button>
          <button class="ghost" @click="router.push({ name: 'sessions' })">
            Back
          </button>
        </div>
      </header>

      <p v-if="actionError" class="banner" role="alert">{{ actionError }}</p>
      <p
        v-if="terminal.gap.value"
        class="banner gap"
        role="status"
        aria-live="polite"
      >
        顯示最新輸出片段（先前歷史已截斷）。
      </p>

      <div class="grid">
        <aside class="rail sessions-rail">
          <h2>Sessions</h2>
          <p class="dim small">切換自 Sessions 清單。</p>
        </aside>

        <div class="center" :data-split="previewPath ? 'preview' : 'terminal'">
          <section class="terminal-pane">
            <div
              ref="host"
              class="terminal-host"
              aria-label="Interactive CLI terminal"
            />
          </section>

          <!-- Read-only file preview: mounted only while a file is open, so the
               editor and its models are disposed as soon as it is closed. -->
          <section v-if="previewPath" class="preview-pane">
            <button
              class="close"
              type="button"
              aria-label="關閉預覽"
              @click="previewPath = null"
            >
              關閉預覽
            </button>
            <PreviewPane :session-id="filesSessionId" :rel-path="previewPath" />
          </section>
        </div>

        <aside class="rail workspace-rail">
          <FileTree
            :session-id="filesSessionId"
            :root-label="workspaceLabel"
            :can-browse="canBrowseFiles"
            :disabled-reason="filesDisabledReason"
            @open="(relPath) => (previewPath = relPath)"
            @clear="previewPath = null"
          />
        </aside>
      </div>
    </div>

    <ConfirmDialog
      :open="terminateOpen"
      :busy="busy"
      danger
      title="Terminate session"
      :message="`Terminate ${session?.name}? The CLI process is stopped on the node.`"
      confirm-label="Terminate"
      @confirm="confirmTerminate"
      @cancel="terminateOpen = false"
    />
  </AppLayout>
</template>

<style scoped>
.workspace {
  display: flex;
  flex-direction: column;
  height: calc(100vh - var(--layout-header) - 48px);
}
.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.meta {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.meta h1 {
  margin: 0;
  font-size: 18px;
}
.dim {
  color: var(--text-muted);
  font-size: 13px;
}
.small {
  font-size: 12px;
}
.role {
  font-size: 12px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 999px;
  border: 1px solid var(--border-default);
}
.role[data-role="writer"] {
  color: var(--status-online);
  border-color: var(--status-online);
}
.actions {
  display: flex;
  gap: 8px;
}
.ghost,
.danger {
  padding: 6px 12px;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  background: var(--surface-default);
  color: var(--text-secondary);
  font-weight: 600;
}
.danger {
  color: var(--status-error);
  border-color: var(--status-error);
}
.banner {
  margin: 0 0 8px;
  padding: 8px 12px;
  border-radius: var(--radius-sm);
  background: #f9eaea;
  color: var(--status-error);
  font-size: 13px;
}
.banner.gap {
  background: #fbf3e3;
  color: var(--status-busy);
}
.grid {
  display: grid;
  grid-template-columns: 200px 1fr 300px;
  gap: 12px;
  flex: 1;
  min-height: 0;
}
/* Terminal stays the primary surface; the preview takes the lower 45% only
   while a file is open. */
.center {
  display: grid;
  grid-template-rows: 1fr;
  gap: 8px;
  min-height: 0;
  min-width: 0;
}
.center[data-split="preview"] {
  grid-template-rows: minmax(0, 1fr) minmax(0, 45%);
}
.preview-pane {
  display: grid;
  grid-template-rows: auto 1fr;
  gap: 4px;
  min-height: 0;
}
.close {
  justify-self: end;
  border: 0;
  background: none;
  color: var(--action-primary);
  font-size: 11px;
  font-weight: 600;
}
.rail {
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  background: var(--surface-elevated);
  padding: 12px;
  overflow: auto;
}
.rail h2 {
  margin: 0 0 8px;
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--text-muted);
}
.terminal-pane {
  min-width: 0;
  background: var(--terminal-background);
  border-radius: var(--radius-md);
  overflow: hidden;
}
.terminal-host {
  width: 100%;
  height: 100%;
}
.link {
  border: 0;
  background: none;
  color: var(--action-primary);
  font-weight: 600;
}
@media (max-width: 1100px) {
  .grid {
    grid-template-columns: 1fr;
  }
  .workspace-rail,
  .sessions-rail {
    display: none;
  }
}
</style>
