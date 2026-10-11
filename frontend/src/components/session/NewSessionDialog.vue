<script setup lang="ts">
import { computed, ref, watch } from "vue";

import { ApiError } from "../../api/client";
import type {
  FavoriteUsability,
  NodeDetail,
  NodeSummary,
  SessionDetail,
} from "../../api/dto";
import { useBreakpoint } from "../../composables/useBreakpoint";
import { errorGuidance } from "../../utils/errorCatalog";
import { useFavoritesStore } from "../../stores/favorites";
import { useNodesStore } from "../../stores/nodes";
import { usePreferencesStore } from "../../stores/preferences";
import { useSessionsStore } from "../../stores/sessions";
import UiButton from "../ui/UiButton.vue";
import UiDialog from "../ui/UiDialog.vue";
import UiInlineNotice from "../ui/UiInlineNotice.vue";

const props = defineProps<{ open: boolean }>();
const emit = defineEmits<{
  created: [session: SessionDetail];
  cancel: [];
}>();

const nodes = useNodesStore();
const sessions = useSessionsStore();
const favorites = useFavoritesStore();
const preferences = usePreferencesStore();
const { isNarrow } = useBreakpoint();

const nodeList = ref<NodeSummary[]>([]);
const nodeDetail = ref<NodeDetail | null>(null);
const nodeId = ref("");
const runtime = ref("");
const workspace = ref("");
const name = ref("");
const busy = ref(false);
const error = ref("");

// Only Online nodes can host a new session (offline is blocked here and again
// server-side).
const selectableNodes = computed(() =>
  nodeList.value.filter((n) => n.status === "online"),
);
const availableRuntimes = computed(() =>
  (nodeDetail.value?.runtimes ?? []).filter((r) => r.available),
);
const enabledRoots = computed(() =>
  (nodeDetail.value?.workspace_roots ?? []).filter((r) => r.is_enabled),
);

// The node's execution posture (ADR 0023), shown before the session exists
// (#106). Same data and same wording as the work header, which shows it after:
// the node reports it, the console only repeats it, and there is nothing here
// that could set it. Absent or unread means nothing is shown — a guessed
// posture is worse than none.
const privilegedNode = computed(
  () => nodeDetail.value?.privileged_terminal === true,
);
const sandboxBypassed = computed(
  () =>
    runtime.value !== "" &&
    availableRuntimes.value.find((r) => r.runtime === runtime.value)
      ?.sandbox_bypass === true,
);

const canSubmit = computed(
  () =>
    !busy.value &&
    nodeId.value !== "" &&
    runtime.value !== "" &&
    workspace.value.trim() !== "" &&
    name.value.trim() !== "",
);

// --- Shortcuts (P4-13): recents and favourites for the selected node ---
//
// Scoped to the selected node because a path only means anything on one machine.
// These fill the workspace field and nothing else: the path still goes through the
// same server-side prefix authorization and the daemon's `os.Root` resolution, so a
// shortcut can save typing but never grant access.
const recentForNode = computed(() =>
  nodeId.value ? favorites.recentForNode(nodeId.value) : [],
);
const favoritesForNode = computed(() =>
  nodeId.value ? favorites.favoritesForNode(nodeId.value) : [],
);
// `forbidden` hides the whole region: a role without `session.create` cannot reach
// this dialog anyway, and an empty box with a retry button would be noise.
const showShortcuts = computed(
  () => nodeId.value !== "" && favorites.state !== "forbidden",
);
const shortcutsLoading = computed(() => favorites.state === "loading");
const shortcutsFailed = computed(() => favorites.state === "error");
const currentIsFavorite = computed(
  () =>
    nodeId.value !== "" &&
    workspace.value.trim() !== "" &&
    favorites.isFavorite(nodeId.value, workspace.value.trim()),
);
const favoriteToggleBusy = computed(
  () =>
    nodeId.value !== "" &&
    favorites.isPending(nodeId.value, workspace.value.trim()),
);

const UNUSABLE_REASON: Record<Exclude<FavoriteUsability, "usable">, string> = {
  node_offline: "Node 已離線，無法建立 Session",
  node_disabled: "Node 已停用，無法使用",
  outside_allowed_root: "已不在允許的根目錄內",
};

function reasonFor(usability: FavoriteUsability): string | null {
  return usability === "usable" ? null : UNUSABLE_REASON[usability];
}

function pick(path: string): void {
  workspace.value = path;
}

async function toggleFavorite(): Promise<void> {
  const path = workspace.value.trim();
  if (!nodeId.value || !path) return;
  await favorites.toggle(nodeId.value, path);
  // A refused favourite reports why in the same place as every other failure here,
  // rather than failing silently and leaving the star looking broken.
  if (favorites.error instanceof ApiError && !currentIsFavorite.value) {
    error.value = favoriteErrorMessage(favorites.error);
  }
}

function favoriteErrorMessage(err: ApiError): string {
  switch (err.code) {
    case "WORKSPACE_OUTSIDE_ALLOWED_ROOT":
      return "此路徑不在允許的根目錄內，無法儲存。";
    case "WORKSPACE_INVALID":
      return "此路徑無法儲存：請使用不含「..」的絕對路徑。";
    case "NODE_DISABLED":
      return "此 Node 已停用，無法儲存。";
    default:
      return "無法儲存到我的最愛。";
  }
}

watch(
  () => props.open,
  async (open) => {
    if (open) {
      reset();
      // Loaded fresh on every open: usability is recomputed server-side per read,
      // so a favourite whose root was withdrawn since last time says so.
      void favorites.load();
      try {
        nodeList.value = await nodes.fetchList();
      } catch {
        error.value = "無法載入 Node 清單。";
      }
    }
  },
);

watch(nodeId, async (id) => {
  nodeDetail.value = null;
  runtime.value = "";
  workspace.value = "";
  if (!id) return;
  try {
    nodeDetail.value = await nodes.fetchNode(id);
    // Pre-select the first enabled root so the path is a valid default.
    const root = enabledRoots.value[0];
    if (root) workspace.value = root.path;
  } catch {
    error.value = "無法載入 Node 詳細資料。";
  }
});

function reset(): void {
  nodeId.value = "";
  runtime.value = "";
  workspace.value = "";
  name.value = "";
  error.value = "";
  busy.value = false;
  nodeDetail.value = null;
}

// --- The size a CLI starts at on a phone (#115) ---
//
// Without a size the server starts the PTY at 24x80. On a phone the attach then
// narrows it to ~40 columns; tmux reflows what the CLI has already printed and
// pushes the head of its first line into history, where the browser never sees
// it — the first thing the user reads is cut. Only *narrowing* loses output, and
// a desktop panel is wider than 80 columns, so the request is unchanged at 768px
// and up.
//
// The workspace panel does not exist yet, so its box is derived from the shell's
// <main>, which this page and the workspace share. On a phone the workspace is
// one column and its chrome does not depend on the viewport — measured in
// chromium at 360x640, 375x553, 390x664, 412x839 and 430x932, the CLI host was
// always exactly:
//   width  = main - 2x16 (fill padding, AppLayout) - 2x1 (card border)
//   height = main - 252  (work header 48, mode switch 54 + 8, tab strip and
//                         drop bar 89, status bar 28, fill padding 2x12,
//                         card border 1)
// A change to that chrome in SessionWorkspaceView has to change these. Rows that
// drift only add or remove blank lines, and the attach resize corrects them;
// columns that drift wider than the panel bring the cut back.
const PHONE_CLI_INSET_X = 2 * 16 + 2 * 1;
const PHONE_CLI_CHROME_Y = 252;

async function phoneCliSize(): Promise<{
  rows: number;
  columns: number;
} | null> {
  if (!isNarrow.value) return null;
  const main = document.getElementById("main");
  if (!main) return null;
  const rect = main.getBoundingClientRect();
  // Typing the session name raised the keyboard, which shrinks the shell, but
  // the workspace opens with it down. The layout viewport is what the keyboard
  // does not shrink.
  const mainHeight = Math.max(
    rect.height,
    document.documentElement.clientHeight - rect.top,
  );
  try {
    const { measureTerminalSize } = await import(
      "../../composables/useTerminalSession"
    );
    return measureTerminalSize(
      {
        width: rect.width - PHONE_CLI_INSET_X,
        height: mainHeight - PHONE_CLI_CHROME_Y,
      },
      preferences.terminalFontSize,
    );
  } catch {
    // No measurement is not a reason to refuse the session: the server
    // default applies, exactly as before.
    return null;
  }
}

async function submit(): Promise<void> {
  if (!canSubmit.value) return;
  busy.value = true;
  error.value = "";
  try {
    const size = await phoneCliSize();
    const session = await sessions.create({
      node_id: nodeId.value,
      runtime: runtime.value,
      name: name.value.trim(),
      workspace: workspace.value.trim(),
      ...(size ?? {}),
    });
    emit("created", session);
  } catch (caught) {
    error.value =
      caught instanceof ApiError
        ? sessionErrorMessage(caught)
        : "無法建立 Session。";
  } finally {
    busy.value = false;
  }
}

function sessionErrorMessage(err: ApiError): string {
  switch (err.code) {
    case "NODE_OFFLINE":
      return "這台 Node 已離線，請改選在線的 Node。";
    case "SESSION_LIMIT_REACHED":
      return "這台 Node 已達 Session 數量上限。";
    case "WORKSPACE_OUTSIDE_ALLOWED_ROOT":
      return "工作目錄必須位於允許的根目錄內。";
    case "RUNTIME_NOT_FOUND":
      return "這台 Node 上沒有這個 Runtime。";
    case "REQUEST_TIMEOUT":
      return "Node 未在時限內回應，請重試。";
    default:
      // The catalog's wording rather than the server's message, which is
      // English and is not this dialog's to show verbatim.
      return errorGuidance(err.code).cause;
  }
}
</script>

<template>
  <!-- UiDialog owns the name, the focus trap, Escape and focus return (#112).
       `busy` blocks both dismissals while the create request is in flight.
       The title, the submit label and the session-name placeholder stay as
       they were: other full-stack specs select the dialog by them. -->
  <UiDialog
    class="new-session"
    :open="open"
    title="New session"
    :busy="busy"
    @cancel="emit('cancel')"
  >
    <div class="form">
      <p v-if="error" class="error" role="alert">{{ error }}</p>

      <label>
        Node
        <select v-model="nodeId">
          <option value="" disabled>選擇一台在線的 Node…</option>
          <option v-for="n in selectableNodes" :key="n.id" :value="n.id">
            {{ n.name }} ({{ n.hostname }})
          </option>
        </select>
      </label>

      <label>
        Runtime
        <select v-model="runtime" :disabled="!nodeDetail">
          <option value="" disabled>選擇 Runtime…</option>
          <!-- Marked in the option, so the posture is visible while choosing
               and not only after. -->
          <option
            v-for="r in availableRuntimes"
            :key="r.runtime"
            :value="r.runtime"
          >
            {{ r.runtime }}{{ r.sandbox_bypass ? "（沙箱已停用）" : "" }}
          </option>
        </select>
      </label>
      <p v-if="nodeDetail && availableRuntimes.length === 0" class="hint">
        這台 Node 沒有偵測到可用的 Runtime。
      </p>

      <!-- Shortcuts: fill the workspace field, never bypass its authorization. -->
      <section v-if="showShortcuts" class="shortcuts" aria-label="工作目錄捷徑">
        <p v-if="shortcutsLoading" class="hint">正在載入捷徑…</p>
        <p v-else-if="shortcutsFailed" class="hint">
          無法載入捷徑。
          <button type="button" class="link" @click="favorites.load()">
            重試
          </button>
        </p>
        <template v-else>
          <div class="group">
            <h3 id="recent-heading">最近使用</h3>
            <p v-if="recentForNode.length === 0" class="hint">
              這台 Node 還沒有最近使用的工作目錄。
            </p>
            <ul v-else aria-labelledby="recent-heading">
              <li v-for="item in recentForNode" :key="item.path">
                <button
                  type="button"
                  class="shortcut"
                  :disabled="!item.node_online || !item.node_enabled"
                  @click="pick(item.path)"
                >
                  <span class="path">{{ item.path }}</span>
                  <span v-if="!item.node_enabled" class="why">
                    {{ UNUSABLE_REASON.node_disabled }}
                  </span>
                  <span v-else-if="!item.node_online" class="why">
                    {{ UNUSABLE_REASON.node_offline }}
                  </span>
                </button>
              </li>
            </ul>
          </div>

          <div class="group">
            <h3 id="favorites-heading">我的最愛</h3>
            <p v-if="favoritesForNode.length === 0" class="hint">
              還沒有我的最愛。在下方工作目錄欄按星號即可儲存。
            </p>
            <ul v-else aria-labelledby="favorites-heading">
              <li v-for="item in favoritesForNode" :key="item.id">
                <button
                  type="button"
                  class="shortcut"
                  :disabled="item.usability !== 'usable'"
                  @click="pick(item.path)"
                >
                  <span class="path">{{ item.display_name || item.path }}</span>
                  <span v-if="reasonFor(item.usability)" class="why">
                    {{ reasonFor(item.usability) }}
                  </span>
                </button>
                <!-- The next step for a permanently broken favourite: remove it. -->
                <button
                  v-if="item.usability === 'outside_allowed_root'"
                  type="button"
                  class="link"
                  @click="favorites.remove(item.id)"
                >
                  移除
                </button>
              </li>
            </ul>
          </div>
        </template>
      </section>

      <label>
        工作目錄
        <span class="field">
          <input
            v-model="workspace"
            type="text"
            placeholder="允許根目錄內的絕對路徑"
            list="roots"
          />
          <button
            type="button"
            class="star"
            :aria-pressed="currentIsFavorite"
            :disabled="!nodeId || workspace.trim() === '' || favoriteToggleBusy"
            :aria-label="
              currentIsFavorite
                ? `從我的最愛移除 ${workspace.trim()}`
                : `將 ${workspace.trim()} 加入我的最愛`
            "
            @click="toggleFavorite"
          >
            {{ currentIsFavorite ? "★" : "☆" }}
          </button>
        </span>
        <datalist id="roots">
          <option
            v-for="root in enabledRoots"
            :key="root.path"
            :value="root.path"
          />
        </datalist>
      </label>

      <label>
        Session 名稱
        <input v-model="name" type="text" placeholder="e.g. refactor-api" />
      </label>

      <!-- Last in the form, directly above the actions: ADR 0023 D10 wants
           the posture in view before the user commits, and this is the spot
           the eye passes on the way to the submit button. A status region,
           so choosing a node that carries a warning is announced. -->
      <UiInlineNotice
        v-if="privilegedNode || sandboxBypassed"
        class="posture-notice"
        tone="warning"
        title="這台 Node 的執行姿態（ADR 0023）"
      >
        <p v-if="sandboxBypassed" data-posture="sandbox">
          沙箱：已停用 — {{ runtime }} 在這台 Node
          上不經核准流程、不受沙箱限制。
        </p>
        <p v-if="privilegedNode" data-posture="privileged">
          此 Node 可提權（sudo）— 系統終端機可經 sudo 取得 root。
        </p>
      </UiInlineNotice>
    </div>

    <template #actions>
      <UiButton
        variant="secondary"
        :disabled="busy"
        disabled-reason="正在建立 Session"
        @click="emit('cancel')"
      >
        取消
      </UiButton>
      <UiButton
        variant="primary"
        :disabled="!canSubmit"
        :busy="busy"
        disabled-reason="請先選擇 Node 與 Runtime，並填寫工作目錄與 Session 名稱"
        @click="submit"
      >
        {{ busy ? "Starting…" : "Start" }}
      </UiButton>
    </template>
  </UiDialog>
</template>

<style scoped>
.form {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
label {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 13px;
  color: var(--text-primary);
}
select,
input {
  height: 40px;
  padding: 0 12px;
  border: 1px solid var(--border-control);
  border-radius: var(--radius-control);
  background: var(--surface-raised);
  color: var(--text-primary);
  font-size: 14px;
}
.hint {
  margin: 0;
  font-size: 12px;
  color: var(--text-secondary);
}
.shortcuts {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 12px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-panel);
}
.shortcuts h3 {
  margin: 0 0 6px;
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--text-secondary);
}
.shortcuts ul {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.shortcuts li {
  display: flex;
  align-items: baseline;
  gap: 8px;
}
.shortcut {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  padding: 6px 8px;
  border: 0;
  border-radius: var(--radius-panel);
  background: transparent;
  text-align: left;
  font-size: 13px;
  color: var(--text-primary);
  cursor: pointer;
}
.shortcut:hover:not(:disabled),
.shortcut:focus-visible {
  background: var(--surface-raised);
}
.shortcut:disabled {
  cursor: not-allowed;
  color: var(--text-secondary);
}
.shortcut .path {
  overflow-wrap: anywhere;
  font-family: var(--font-mono);
}
.shortcut .why {
  font-size: 11px;
  color: var(--status-warning-fg);
}
.field {
  display: flex;
  gap: 6px;
  align-items: stretch;
}
.field input {
  flex: 1;
  min-width: 0;
}
.star {
  width: 40px;
  border: 1px solid var(--border-control);
  border-radius: var(--radius-control);
  background: var(--surface-raised);
  font-size: 16px;
  line-height: 1;
  cursor: pointer;
}
.star[aria-pressed="true"] {
  color: var(--accent-strong);
}
.star:disabled {
  color: var(--text-disabled);
  cursor: not-allowed;
}
.link {
  border: 0;
  background: none;
  padding: 0;
  font-size: 12px;
  color: var(--accent-strong);
  text-decoration: underline;
  cursor: pointer;
}
.error {
  margin: 0;
  padding: 8px 12px;
  border-radius: var(--radius-panel);
  background: var(--status-error-bg);
  color: var(--status-error-fg);
  font-size: 13px;
}
.posture-notice p {
  margin: 0;
}
/* Phone (#106): the backdrop follows the height the software keyboard leaves,
   the same `--viewport-usable-height` the shell sizes itself by (plan/29
   MS-02), so the panel — which scrolls inside itself at `max-height: 100%` —
   ends above the keyboard rather than under it. The actions stay pinned to
   the bottom of that scrolling panel, so the submit button is reachable while
   the session name is being typed. Without the property (no visualViewport)
   this is the backdrop's own full height, exactly as before. */
@media (max-width: 767px) {
  /* Two classes: UiDialog's own `.backdrop { inset: 0 }` has the same
     specificity as one and would win on source order. */
  .backdrop.new-session {
    bottom: auto;
    height: var(--viewport-usable-height, 100%);
  }
  /* Focus scrolling (the browser bringing the typed-into field into view as
     the keyboard opens) stops short of the pinned actions. */
  .backdrop.new-session :deep(.panel) {
    scroll-padding-bottom: 88px;
  }
  /* -24px: a sticky box stops at the scrollport's content edge, which is the
     panel's 24px padding short of its visible edge. */
  .backdrop.new-session :deep(.actions) {
    position: sticky;
    bottom: -24px;
    margin: 22px -24px -24px;
    padding: 12px 24px calc(12px + env(safe-area-inset-bottom, 0px));
    background: var(--surface-raised);
    border-top: 1px solid var(--border-subtle);
  }
}
</style>
