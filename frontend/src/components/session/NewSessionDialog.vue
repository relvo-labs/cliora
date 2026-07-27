<script setup lang="ts">
import { computed, ref, watch } from "vue";

import { ApiError } from "../../api/client";
import type {
  FavoriteUsability,
  NodeDetail,
  NodeSummary,
  SessionDetail,
} from "../../api/dto";
import { useFavoritesStore } from "../../stores/favorites";
import { useNodesStore } from "../../stores/nodes";
import { useSessionsStore } from "../../stores/sessions";

const props = defineProps<{ open: boolean }>();
const emit = defineEmits<{
  created: [session: SessionDetail];
  cancel: [];
}>();

const nodes = useNodesStore();
const sessions = useSessionsStore();
const favorites = useFavoritesStore();

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
  node_offline: "Node is offline — a session cannot be started",
  node_disabled: "Node is disabled — unavailable",
  outside_allowed_root: "No longer inside an allowed root",
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
      return "That path is not inside an allowed root, so it cannot be saved.";
    case "WORKSPACE_INVALID":
      return "That path cannot be saved. Use an absolute path with no '..'.";
    case "NODE_DISABLED":
      return "That node is disabled, so it cannot be saved.";
    default:
      return err.message || "Could not save the favourite.";
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
        error.value = "Could not load nodes.";
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
    error.value = "Could not load node details.";
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

async function submit(): Promise<void> {
  if (!canSubmit.value) return;
  busy.value = true;
  error.value = "";
  try {
    const session = await sessions.create({
      node_id: nodeId.value,
      runtime: runtime.value,
      name: name.value.trim(),
      workspace: workspace.value.trim(),
    });
    emit("created", session);
  } catch (caught) {
    error.value =
      caught instanceof ApiError
        ? sessionErrorMessage(caught)
        : "Could not start the session.";
  } finally {
    busy.value = false;
  }
}

function sessionErrorMessage(err: ApiError): string {
  switch (err.code) {
    case "NODE_OFFLINE":
      return "That node is offline; pick an online node.";
    case "SESSION_LIMIT_REACHED":
      return "This node has reached its session limit.";
    case "WORKSPACE_OUTSIDE_ALLOWED_ROOT":
      return "The workspace must be inside an allowed root.";
    case "RUNTIME_NOT_FOUND":
      return "That runtime is not available on this node.";
    case "REQUEST_TIMEOUT":
      return "The node did not respond in time. Try again.";
    default:
      return err.message || "Could not start the session.";
  }
}
</script>

<template>
  <div v-if="open" class="overlay" role="dialog" aria-modal="true">
    <div class="dialog">
      <h2>New session</h2>
      <p v-if="error" class="error" role="alert">{{ error }}</p>

      <label>
        Node
        <select v-model="nodeId">
          <option value="" disabled>Select an online node…</option>
          <option v-for="n in selectableNodes" :key="n.id" :value="n.id">
            {{ n.name }} ({{ n.hostname }})
          </option>
        </select>
      </label>

      <label>
        Runtime
        <select v-model="runtime" :disabled="!nodeDetail">
          <option value="" disabled>Select a runtime…</option>
          <option
            v-for="r in availableRuntimes"
            :key="r.runtime"
            :value="r.runtime"
          >
            {{ r.runtime }}
          </option>
        </select>
      </label>
      <p v-if="nodeDetail && availableRuntimes.length === 0" class="hint">
        No runtimes detected on this node.
      </p>

      <!-- Shortcuts: fill the workspace field, never bypass its authorization. -->
      <section v-if="showShortcuts" class="shortcuts" aria-label="Shortcuts">
        <p v-if="shortcutsLoading" class="hint">Loading shortcuts…</p>
        <p v-else-if="shortcutsFailed" class="hint">
          Could not load shortcuts.
          <button type="button" class="link" @click="favorites.load()">
            Retry
          </button>
        </p>
        <template v-else>
          <div class="group">
            <h3 id="recent-heading">Recently used</h3>
            <p v-if="recentForNode.length === 0" class="hint">
              No recent workspaces on this node yet.
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
                    Node is disabled — unavailable
                  </span>
                  <span v-else-if="!item.node_online" class="why">
                    Node is offline — a session cannot be started
                  </span>
                </button>
              </li>
            </ul>
          </div>

          <div class="group">
            <h3 id="favorites-heading">Favourites</h3>
            <p v-if="favoritesForNode.length === 0" class="hint">
              No favourites yet. Star a workspace below to save it.
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
                  Remove
                </button>
              </li>
            </ul>
          </div>
        </template>
      </section>

      <label>
        Workspace
        <span class="field">
          <input
            v-model="workspace"
            type="text"
            placeholder="/path/inside/an/allowed/root"
            list="roots"
          />
          <button
            type="button"
            class="star"
            :aria-pressed="currentIsFavorite"
            :disabled="!nodeId || workspace.trim() === '' || favoriteToggleBusy"
            :aria-label="
              currentIsFavorite
                ? `Remove ${workspace.trim()} from favourites`
                : `Add ${workspace.trim()} to favourites`
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
        Session name
        <input v-model="name" type="text" placeholder="e.g. refactor-api" />
      </label>

      <div class="buttons">
        <button class="ghost" :disabled="busy" @click="emit('cancel')">
          Cancel
        </button>
        <button class="primary" :disabled="!canSubmit" @click="submit">
          {{ busy ? "Starting…" : "Start" }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.overlay {
  position: fixed;
  inset: 0;
  background: rgba(15, 17, 21, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 50;
}
.dialog {
  width: min(440px, 92vw);
  background: var(--surface-elevated);
  border-radius: var(--radius-lg);
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.dialog h2 {
  margin: 0;
  font-size: 18px;
}
label {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 13px;
  color: var(--text-secondary);
}
select,
input {
  height: 40px;
  padding: 0 12px;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  background: var(--surface-default);
  font-size: 14px;
}
.hint {
  margin: 0;
  font-size: 12px;
  color: var(--text-muted);
}
.shortcuts {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 12px;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
}
.shortcuts h3 {
  margin: 0 0 6px;
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--text-muted);
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
  border-radius: var(--radius-sm);
  background: transparent;
  text-align: left;
  font-size: 13px;
  color: var(--text-primary);
  cursor: pointer;
}
.shortcut:hover:not(:disabled),
.shortcut:focus-visible {
  background: var(--surface-default);
}
.shortcut:disabled {
  cursor: not-allowed;
  color: var(--text-muted);
}
.shortcut .path {
  overflow-wrap: anywhere;
  font-family: var(--font-mono, monospace);
}
.shortcut .why {
  font-size: 11px;
  color: var(--status-warning, var(--text-muted));
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
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  background: var(--surface-default);
  font-size: 16px;
  line-height: 1;
  cursor: pointer;
}
.star[aria-pressed="true"] {
  color: var(--action-primary);
}
.star:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.link {
  border: 0;
  background: none;
  padding: 0;
  font-size: 12px;
  color: var(--action-primary);
  text-decoration: underline;
  cursor: pointer;
}
.error {
  margin: 0;
  padding: 8px 12px;
  border-radius: var(--radius-sm);
  background: #f9eaea;
  color: var(--status-error);
  font-size: 13px;
}
.buttons {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 4px;
}
.ghost,
.primary {
  padding: 8px 16px;
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
.primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
