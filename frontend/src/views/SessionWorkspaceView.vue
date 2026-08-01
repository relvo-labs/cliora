<script setup lang="ts">
import {
  computed,
  defineAsyncComponent,
  nextTick,
  onBeforeUnmount,
  onMounted,
  ref,
  watch,
} from "vue";
import { useRouter } from "vue-router";

import { ApiError } from "../api/client";
import type { NodeDetail, SessionDetail } from "../api/dto";
import AppLayout from "../components/layout/AppLayout.vue";
import AsyncState from "../components/common/AsyncState.vue";
import ConfirmDialog from "../components/common/ConfirmDialog.vue";
import StatusBadge from "../components/common/StatusBadge.vue";
import FileTree from "../components/file/FileTree.vue";
import WorkspaceTabs from "../components/session/WorkspaceTabs.vue";

// Monaco is a large dependency and only the preview needs it, so the pane (and
// with it the whole editor bundle) loads on the first file the user opens.
const PreviewPane = defineAsyncComponent(
  () => import("../components/file/PreviewPane.vue"),
);
import { useAsyncResource } from "../composables/useAsyncResource";
import { useTerminalSession } from "../composables/useTerminalSession";
import { api } from "../stores/auth";
import { useNodesStore } from "../stores/nodes";
import { useSessionsStore } from "../stores/sessions";

const props = defineProps<{ id: string }>();
const router = useRouter();
const sessions = useSessionsStore();
const nodes = useNodesStore();

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
// Whether a TERMINAL tab exists at all. The server already combined the action,
// ownership and the node's own veto into this flag; recombining it here with
// `hasPermission()` would show the tab on a colleague's session and only fail
// when it was pressed.
const canOpenShell = computed(
  () => capabilities.value?.can_open_shell === true,
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
// (session switch) so no previous session's content stays on screen. There is
// at most one preview at a time, so at most one `[filename]` tab (WT-03, D2).
const previewPath = ref<string | null>(null);

// Centre-pane tab selection. `cli` always exists; `preview` only while a file
// is open, so a closed preview always falls back to the terminal.
type CentreTab = "cli" | "preview" | "terminal";
const activeTab = ref<CentreTab>("cli");

const tabs = computed(() => [
  { id: "cli", label: "CLI" },
  ...(previewPath.value
    ? [
        {
          id: "preview",
          // Basename only. The full workspace-relative path goes in the
          // tooltip; a node absolute path never reaches the browser (P3).
          label: previewPath.value.split("/").pop() ?? previewPath.value,
          title: previewPath.value,
          closable: true,
        },
      ]
    : []),
  ...(canOpenShell.value
    ? [
        {
          id: "terminal",
          label: "TERMINAL",
          title: "此 Node 上的系統終端機",
          closable: shellSession.value !== null,
        },
      ]
    : []),
]);

function openPreview(relPath: string): void {
  previewPath.value = relPath;
  activeTab.value = "preview";
}

function closePreview(): void {
  previewPath.value = null;
  activeTab.value = "cli";
}

function closeTab(id: string): void {
  if (id === "preview") closePreview();
  if (id === "terminal") void closeShell();
}

// Re-measure on the way into either terminal: while a panel is hidden its host
// measures 0x0, so the composable deliberately refuses to fit it.
watch(activeTab, async (tab) => {
  if (tab === "cli") {
    await nextTick();
    terminal.fit();
    terminal.focus();
    return;
  }
  if (tab === "terminal") {
    await openShellTab();
  }
});

// --- System terminal (FR-SHELL-001) ---------------------------------------
//
// A second, independent instance of the same composable: the shell is an
// ordinary session over the same relay, so nothing about the transport differs.
const shellTerminal = useTerminalSession((sessionId) =>
  api()
    .attachSession(sessionId)
    .then((res) => res.ticket),
);
const shellSession = ref<SessionDetail | null>(null);
const shellHost = ref<HTMLElement | null>(null);
const shellState = ref<"idle" | "starting" | "ready" | "error">("idle");
const shellError = ref("");

watch(
  shellHost,
  (element) => {
    if (element) shellTerminal.mount(element);
  },
  { immediate: true },
);

// Started on first use, not on page load: a shell nobody opened would still
// consume a slot against the node and user session caps (D8).
async function openShellTab(): Promise<void> {
  if (shellState.value === "starting") return;
  if (shellSession.value) {
    await nextTick();
    shellTerminal.fit();
    shellTerminal.focus();
    return;
  }
  shellState.value = "starting";
  shellError.value = "";
  try {
    // The panel was just revealed by `v-show`; it has no layout until the DOM
    // updates, and an unmeasurable host reports nothing. Opening at a hardcoded
    // 24×80 and letting the first fit correct it made bash redraw its prompt at
    // a different width in front of the user (plan/09 LY-04).
    await nextTick();
    const size = shellTerminal.proposeSize() ?? { rows: 24, columns: 80 };
    const created = await api().openShell(props.id, size);
    shellSession.value = created;
    shellState.value = "ready";
    await nextTick();
    void shellTerminal.connect(created.id);
  } catch (caught) {
    shellState.value = "error";
    shellError.value =
      caught instanceof ApiError ? caught.message : "無法開啟系統終端機。";
  }
}

// Closing the tab ends the session on the node. The server-side parent binding
// and idle timeout are the backstop for the cases the browser cannot report
// (a crash, a lost network), not a substitute for asking.
async function closeShell(): Promise<void> {
  const open = shellSession.value;
  shellSession.value = null;
  shellState.value = "idle";
  shellTerminal.disconnect();
  if (activeTab.value === "terminal") activeTab.value = "cli";
  if (!open) return;
  try {
    await api().terminateSession(open.id);
  } catch {
    // Best effort: the parent binding and the idle timeout still collect it.
  }
}

// AC-08 has two halves and only the first was implemented: "closing the terminal
// **or leaving the Session workspace** ends the system terminal". Leaving covers
// three different exits, and each needs its own hook — a shell that survives any of
// them is one nobody is watching, and the next visit could not even see it to close
// it (the tab's close affordance keys off local state, which the exit just threw
// away).
//
// 1. Navigating inside the app (Back, the sidebar): the component unmounts.
onBeforeUnmount(() => {
  void closeShell();
});

// 2. Reload, tab close, or leaving the origin: no unmount runs and an ordinary
//    fetch would be cancelled with the document, so this one is `keepalive` and
//    fire-and-forget. `pagehide` rather than `beforeunload`: it also fires when the
//    page is discarded on mobile, and it does not risk a confirmation prompt.
//    The local state is reset too, not just the request sent: `pagehide` also fires
//    when the page is put in the back/forward cache, and a restored page that still
//    believed it had this terminal would show its dead scrollback.
function terminateShellOnUnload(): void {
  const open = shellSession.value;
  if (!open) return;
  shellSession.value = null;
  shellState.value = "idle";
  shellTerminal.disconnect();
  api().terminateSessionOnUnload(open.id);
}
window.addEventListener("pagehide", terminateShellOnUnload);
onBeforeUnmount(() =>
  window.removeEventListener("pagehide", terminateShellOnUnload),
);

const host = ref<HTMLElement | null>(null);
const terminateOpen = ref(false);
const actionError = ref("");
const busy = ref(false);

const resource = useAsyncResource<SessionDetail>(async () => {
  const detail = await sessions.fetchSession(props.id);
  // Posture is fetched alongside, not awaited into the critical path's failure
  // modes: a node read that fails must not make the workspace unopenable.
  void loadNodePosture(detail.node_id);
  return detail;
});

// The composable owns the xterm + socket; it mints a fresh single-use ws-ticket
// on every (re)connect via the API client.
const terminal = useTerminalSession((sessionId) =>
  api()
    .attachSession(sessionId)
    .then((res) => res.ticket),
);

const session = computed(() => sessions.current);

// 這台 Node 的執行姿態（ADR 0023）。使用者按下 Enter 之前，資訊要在他眼前 —— 不是藏在
// Node 詳情頁裡。額外一次請求、且失敗不影響工作區：拿不到姿態時什麼都不顯示，
// 因為顯示一個猜的姿態比不顯示更糟。Viewer 也持有 node.view，所以每個能開這個工作區的
// 人都拿得到。
const nodePosture = ref<NodeDetail | null>(null);
async function loadNodePosture(nodeId: string): Promise<void> {
  try {
    nodePosture.value = await nodes.fetchNode(nodeId);
  } catch {
    nodePosture.value = null;
  }
}
const sandboxBypassed = computed(() => {
  const runtime = session.value?.runtime;
  if (!runtime || !nodePosture.value) return false;
  return (
    nodePosture.value.runtimes.find((rt) => rt.runtime === runtime)
      ?.sandbox_bypass === true
  );
});
const privilegedNode = computed(
  () => nodePosture.value?.privileged_terminal === true,
);

// Mounting follows the host element, not the lifecycle hook. `onMounted` fires
// once, so any render that replaced the host — a failed load followed by Retry,
// or a tab panel being rebuilt — left xterm attached to a detached node with
// nobody to put it back (WT-02).
watch(
  host,
  (element) => {
    if (element) terminal.mount(element);
  },
  { immediate: true },
);

onMounted(async () => {
  await resource.run();
  if (resource.state.value === "success") {
    void terminal.connect(props.id);
  }
});

// Switching to another session id re-attaches cleanly (dispose is handled by the
// composable's scope teardown on unmount; here we just reconnect).
watch(
  () => props.id,
  async (next, prev) => {
    if (next && next !== prev) {
      // 3. The third way out of a workspace: the route param changes and this
      //    component is *reused*, so neither unmount nor pagehide fires. Without
      //    this the previous session's shell stayed alive, and worse, its id stayed
      //    in `shellSession` — the TERMINAL tab here would then show the terminal
      //    of the session the user just left.
      await closeShell();
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
  <!-- fill: this page is a fixed layout that owns the viewport. The terminal's
       height comes from the shell, so nothing here re-derives it (plan/09 D1). -->
  <AppLayout fill>
    <!-- The workspace container is never unmounted: the terminal host lives
         inside it, and xterm cannot survive its container being replaced.
         Loading / forbidden / error therefore render as an overlay on top
         rather than instead of it (WT-02). -->
    <div class="workspace">
      <header v-if="session" class="head">
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
          <!-- 姿態要在使用者按下 Enter 之前就在眼前（ADR 0023 D10）。只在確實取得
               Node 回報時顯示：猜一個姿態比不顯示更糟。 -->
          <span v-if="sandboxBypassed" class="posture" title="ADR 0023"
            >沙箱：已停用</span
          >
          <span v-if="privilegedNode" class="posture" title="ADR 0023"
            >此 Node 可提權（sudo）</span
          >
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
        <div class="center">
          <WorkspaceTabs
            :tabs="tabs"
            :active="activeTab"
            @select="(id) => (activeTab = id as CentreTab)"
            @close="closeTab"
          />

          <!-- The terminal panel is hidden, never unmounted: unmounting it
               would tear down a live WebSocket and an xterm buffer that the
               user expects to find unchanged when they come back (D4). -->
          <section
            v-show="activeTab === 'cli'"
            id="panel-cli"
            class="pane terminal-pane"
            role="tabpanel"
            aria-labelledby="tab-cli"
          >
            <div
              ref="host"
              class="terminal-host"
              aria-label="Interactive CLI terminal"
            />
          </section>

          <!-- System terminal. Same hide-don't-unmount rule as the CLI panel: it
               holds a live WebSocket to a session on the node. -->
          <section
            v-if="canOpenShell"
            v-show="activeTab === 'terminal'"
            id="panel-terminal"
            class="pane terminal-pane"
            role="tabpanel"
            aria-labelledby="tab-terminal"
          >
            <p class="shell-notice" role="note">
              系統終端機：直接操作此 Node 的 shell，<strong
                >不受 workspace 路徑限制</strong
              >。指令內容不會被記錄。<template v-if="privilegedNode">
                此 Node <strong>可經 sudo 取得 root</strong>（ADR
                0023）。</template
              >
            </p>
            <div
              ref="shellHost"
              class="terminal-host"
              aria-label="System terminal"
            />
            <p class="terminal-hint">
              滾輪可往上檢視先前輸出（按 <kbd>q</kbd> 回到即時輸出）·
              選取文字請按住 <kbd>Shift</kbd> 拖曳
            </p>
            <p
              v-if="shellState === 'starting'"
              class="shell-status"
              role="status"
            >
              正在開啟系統終端機…
            </p>
            <p
              v-else-if="shellState === 'error'"
              class="shell-status bad"
              role="alert"
            >
              {{ shellError }}
              <button class="link" type="button" @click="openShellTab()">
                重試
              </button>
            </p>
          </section>

          <!-- The preview is mounted only while a file is open: closing it must
               dispose Monaco and its models, and unmounting costs nothing here
               because there is no connection behind it. -->
          <section
            v-if="previewPath"
            v-show="activeTab === 'preview'"
            id="panel-preview"
            class="pane"
            role="tabpanel"
            aria-labelledby="tab-preview"
          >
            <PreviewPane :session-id="filesSessionId" :rel-path="previewPath" />
          </section>
        </div>

        <aside v-if="session" class="rail workspace-rail">
          <FileTree
            :session-id="filesSessionId"
            :root-label="workspaceLabel"
            :can-browse="canBrowseFiles"
            :disabled-reason="filesDisabledReason"
            @open="openPreview"
            @clear="closePreview"
          />
        </aside>
      </div>

      <div v-if="!session || resource.state.value !== 'success'" class="veil">
        <AsyncState v-if="resource.state.value === 'loading'" state="loading"
          >Loading session…</AsyncState
        >
        <AsyncState
          v-else-if="resource.state.value === 'forbidden'"
          state="forbidden"
        >
          You do not have permission to view this session.
        </AsyncState>
        <AsyncState v-else state="error">
          Could not load this session.
          <button class="link" @click="resource.run()">Retry</button>
        </AsyncState>
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
/* The height comes from AppLayout's fill mode — deliberately not recomputed
 * here. The previous `calc(100vh - header - 48px)` was 16px taller than the
 * space main actually offered, which is why this page always had a small page
 * scrollbar (plan/09 D1). */
.workspace {
  position: relative;
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
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
  grid-template-columns: 1fr 300px;
  gap: 12px;
  flex: 1;
  min-height: 0;
}
/* Tab bar plus exactly one visible panel. The selected panel gets the whole
   centre column: splitting it left both halves too small to work in (WT-03). */
.center {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  gap: 8px;
  min-height: 0;
  min-width: 0;
}
/* Every panel occupies the same grid cell, so a hidden one costs no space. */
.pane {
  grid-row: 2;
  grid-column: 1;
  min-height: 0;
  min-width: 0;
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
/* A column, not a row template. The template this replaces
 * (`auto minmax(0,1fr) auto`) assumed three children — true for the system
 * terminal, but the CLI panel has one, so auto-placement put the terminal host
 * in the leading `auto` row and its height became "whatever xterm already is".
 * With xterm's default 24 rows that self-stabilised: the host measured exactly
 * the terminal it contained, so FitAddon kept proposing 24 rows at every window
 * size, and the CLI sat at roughly half the pane forever.
 *
 * flex removes the assumption instead of correcting the count: only the host
 * grows, and adding or removing a notice cannot change that (plan/09 D3). */
.terminal-pane {
  display: flex;
  flex-direction: column;
  background: var(--terminal-background);
  border-radius: var(--radius-md);
  overflow: hidden;
}
/* All three are conditional or short: present or not, they must not affect who
   gets the slack. */
.shell-notice,
.shell-status,
.terminal-hint {
  flex: 0 0 auto;
}
/* Scrolling and selecting both changed behaviour with the tmux mouse mode that
   made scrolling work at all (ADR 0023): the wheel now drives tmux copy mode, and
   drag-select belongs to tmux unless Shift is held. Neither is discoverable, so
   the two sentences live under the terminal rather than in a release note nobody
   re-reads. Note it is Shift+*drag*, not Shift+wheel — xterm.js ignores a wheel
   event with Shift held. */
.terminal-hint {
  margin: 0;
  padding: 4px 10px 6px;
  color: #7c8695;
  font-size: 11px;
}
.terminal-hint kbd {
  padding: 0 3px;
  border: 1px solid #333a45;
  border-radius: 3px;
  font-family: inherit;
}
/* 不是裝飾：使用者要能分辨自己在哪一種邊界裡（ADR 0021 §4、ADR 0023 D10）。 */
.posture {
  padding: 1px 6px;
  border-radius: var(--radius-sm);
  background: #3a2f1b;
  color: #f0d9a8;
  font-size: 11px;
}
/* Not decoration: the user has to be able to tell which security boundary they
   are inside (ADR 0021 §4). */
.shell-notice {
  margin: 0;
  padding: 6px 10px;
  background: #3a2f1b;
  color: #f0d9a8;
  font-size: 11px;
}
.shell-status {
  margin: 0;
  padding: 6px 10px;
  color: #9aa4b2;
  font-size: 12px;
}
.shell-status.bad {
  color: var(--status-error);
}
/* Covers the workspace while it cannot be used, without unmounting it. */
.veil {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  background: var(--surface-default);
}
/* No `height: 100%`: inside a flex column it feeds flex-basis, so the host would
 * ask for the whole pane while the notice asks for its own height, and shrinking
 * would decide the outcome. `flex: 1` says the one true thing — take what is
 * left. `min-height: 0` lets it shrink below xterm's rendered height, without
 * which the pane, not the host, would be what overflows. */
.terminal-host {
  flex: 1 1 auto;
  min-height: 0;
  width: 100%;
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
  .workspace-rail {
    display: none;
  }
}
</style>
