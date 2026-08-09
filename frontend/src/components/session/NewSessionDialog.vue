<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";

import { ApiError } from "../../api/client";
import {
  ACTION_PROJECT_VIEW,
  FEATURE_PROJECTS,
  type FavoriteUsability,
  type NodeDetail,
  type NodeSummary,
  type ProjectDetail,
  type ProjectSummary,
  type SessionDetail,
} from "../../api/dto";
import { useAuthStore } from "../../stores/auth";
import { useFavoritesStore } from "../../stores/favorites";
import { useNodesStore } from "../../stores/nodes";
import { useProjectsStore } from "../../stores/projects";
import { useSessionsStore } from "../../stores/sessions";

const props = defineProps<{
  open: boolean;
  // Prefill, supplied when the dialog is opened from a project's binding list.
  // Optional in every combination: the ad-hoc path passes none of them and is
  // byte-for-byte the dialog that existed before the project layer.
  prefill?: {
    projectId?: string;
    // Carried from a card's "開始工作" button. A **prefill**, not a second creation
    // flow: node, runtime and workspace are still chosen and still validated, because
    // the one thing a card cannot know is which machine the work happens on
    // (`plan/17/07-…md` §5.1).
    taskId?: string;
    nodeId?: string;
    workspace?: string;
  };
}>();
const emit = defineEmits<{
  created: [session: SessionDetail];
  cancel: [];
}>();

const auth = useAuthStore();
const nodes = useNodesStore();
const sessions = useSessionsStore();
const favorites = useFavoritesStore();
const projects = useProjectsStore();

const nodeList = ref<NodeSummary[]>([]);
const nodeDetail = ref<NodeDetail | null>(null);
const nodeId = ref("");
const runtime = ref("");
const workspace = ref("");
const name = ref("");
const busy = ref(false);
const error = ref("");

// --- The optional project (ADR 0027) ---
//
// Two conditions, ANDed, exactly as the navigation rail does it: `features` says
// whether this deployment has projects at all, `permissions` whether this person
// may see them. With either false the field is **absent**, not disabled — and the
// dialog is then indistinguishable from the pre-V2 one, which is what the
// flag-off promise means here.
const showProjectField = computed(
  () =>
    auth.hasFeature(FEATURE_PROJECTS) &&
    auth.hasPermission(ACTION_PROJECT_VIEW),
);
const projectId = ref("");
const taskId = ref("");
const prefillLocked = ref(false);
const projectList = ref<ProjectSummary[]>([]);
const projectDetail = ref<ProjectDetail | null>(null);

// Archived projects accept no new sessions, so offering one would be offering a
// choice the server refuses. Paused ones are fine — pausing is a label for people,
// not a platform constraint.
const selectableProjects = computed(() =>
  projectList.value.filter((p) => p.status !== "archived"),
);

// With a project chosen, the node and workspace lists narrow to its bindings —
// and only to the usable ones, because a binding whose root was withdrawn cannot
// start a session. Without one, both lists are exactly what they were before.
const projectBindings = computed(() =>
  (projectDetail.value?.workspaces ?? []).filter(
    (w) => w.usability === "usable",
  ),
);
const projectNodeIds = computed(
  () => new Set(projectBindings.value.map((w) => w.node_id)),
);

// Only Online nodes can host a new session (offline is blocked here and again
// server-side).
const selectableNodes = computed(() => {
  const online = nodeList.value.filter((n) => n.status === "online");
  return projectId.value
    ? online.filter((n) => projectNodeIds.value.has(n.id))
    : online;
});
const availableRuntimes = computed(() =>
  (nodeDetail.value?.runtimes ?? []).filter((r) => r.available),
);
const enabledRoots = computed(() =>
  (nodeDetail.value?.workspace_roots ?? []).filter((r) => r.is_enabled),
);
// The bound paths for the chosen node. Offered as buttons rather than typed,
// because a project session's workspace must match a binding **exactly** — a
// subdirectory of a bound path is not itself bound, and typing one is the easiest
// way to meet that refusal.
const boundPathsForNode = computed(() =>
  projectBindings.value.filter((w) => w.node_id === nodeId.value),
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
  () =>
    projectId.value === "" &&
    nodeId.value !== "" &&
    favorites.state !== "forbidden",
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
      if (showProjectField.value) {
        try {
          projectList.value = await projects.fetchList();
        } catch {
          // Not fatal, and deliberately not an error banner: the ad-hoc path still
          // works, so a failed project list should cost the user the *narrowing*,
          // not the dialog.
          projectList.value = [];
        }
      }
      // Applied after the lists load so the watchers below see real options.
      if (props.prefill?.projectId && showProjectField.value) {
        projectId.value = props.prefill.projectId;
        prefillLocked.value = true;
        await nextTick();
      }
      // After the project, because a task without its project is refused server-side
      // and there is no reason to let the dialog send that request at all.
      if (props.prefill?.taskId && projectId.value) {
        taskId.value = props.prefill.taskId;
      }
      if (props.prefill?.nodeId) {
        nodeId.value = props.prefill.nodeId;
        await nextTick();
      }
      if (props.prefill?.workspace) workspace.value = props.prefill.workspace;
    }
  },
);

watch(projectId, async (id) => {
  projectDetail.value = null;
  if (!id) return;
  try {
    projectDetail.value = await projects.fetchProject(id);
  } catch {
    error.value = "Could not load that project's workspaces.";
    return;
  }
  // Choosing a project narrows the node list, so a node picked before it may no
  // longer be offered. Clearing is the honest response — leaving a stale selection
  // would submit a pair the server refuses with SESSION_PROJECT_MISMATCH.
  if (nodeId.value && !projectNodeIds.value.has(nodeId.value)) {
    nodeId.value = "";
  } else if (nodeId.value) {
    const bound = boundPathsForNode.value[0];
    if (bound) workspace.value = bound.path;
  }
});

watch(nodeId, async (id) => {
  nodeDetail.value = null;
  runtime.value = "";
  workspace.value = "";
  if (!id) return;
  try {
    nodeDetail.value = await nodes.fetchNode(id);
    // Inside a project, default to a *bound* path: the allowed root is rarely one
    // of the bindings, and the match is exact, so defaulting to the root would
    // prefill a value the server then refuses.
    const bound = boundPathsForNode.value[0];
    if (bound) {
      workspace.value = bound.path;
      return;
    }
    // Pre-select the first enabled root so the path is a valid default.
    const root = enabledRoots.value[0];
    if (root) workspace.value = root.path;
  } catch {
    error.value = "Could not load node details.";
  }
});

function reset(): void {
  projectId.value = "";
  taskId.value = "";
  prefillLocked.value = false;
  projectList.value = [];
  projectDetail.value = null;
  nodeId.value = "";
  runtime.value = "";
  workspace.value = "";
  name.value = "";
  error.value = "";
  busy.value = false;
  nodeDetail.value = null;
}

function changeToAdHoc(): void {
  prefillLocked.value = false;
  projectId.value = "";
  // The card goes with the project: a session attached to a card but to no project is
  // a state the server refuses, and offering it here would be offering a dead end.
  taskId.value = "";
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
      // Omitted entirely when empty, so the request body of an ad-hoc session is
      // identical to the one this dialog sent before the project layer existed.
      ...(projectId.value ? { project_id: projectId.value } : {}),
      ...(projectId.value && taskId.value ? { task_id: taskId.value } : {}),
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
    case "SESSION_PROJECT_MISMATCH":
      return "That workspace is not one of the project's bound directories. Pick one from the list, or clear the project.";
    case "PROJECT_ARCHIVED":
      return "That project is archived and accepts no new sessions.";
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

      <!--
        Kept after Node and Runtime so those remain the first two selects used by
        the pre-V2 keyboard and E2E flow. It is absent, not disabled, when this
        deployment or person lacks projects, preserving the flag-off dialog.
      -->
      <label v-if="showProjectField" data-testid="project-field">
        Project <span class="optional">optional</span>
        <select
          v-model="projectId"
          :disabled="prefillLocked || projectList.length === 0"
        >
          <option value="">No project (ad-hoc session)</option>
          <option v-for="p in selectableProjects" :key="p.id" :value="p.id">
            {{ p.name }}
          </option>
        </select>
      </label>
      <p v-if="showProjectField && projectList.length === 0" class="hint">
        No projects exist yet. This session will be ad-hoc.
      </p>
      <button
        v-if="showProjectField && prefillLocked"
        type="button"
        class="link change-project"
        @click="changeToAdHoc"
      >
        Change to an ad-hoc session
      </button>
      <p v-if="showProjectField && projectId" class="hint">
        Only this project's bound directories can be used, and the match is
        exact — a subdirectory of a bound path is not itself bound.
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
            :readonly="projectId !== ''"
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
        <div v-if="projectId" class="bound-paths">
          <p v-if="boundPathsForNode.length === 0" class="hint">
            This project has no usable bound directory on that node. Bind one
            first, or clear the project to start an ad-hoc session.
          </p>
          <template v-else>
            <span class="hint">Bound directories:</span>
            <button
              v-for="w in boundPathsForNode"
              :key="w.id"
              type="button"
              class="bound"
              :data-selected="workspace === w.path"
              @click="workspace = w.path"
            >
              {{ w.path }}
            </button>
          </template>
        </div>
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
.optional {
  margin-left: 6px;
  color: var(--text-muted);
  font-size: 11px;
  font-weight: 400;
}
.hint {
  margin: 0;
  color: var(--text-muted);
  font-size: 12px;
}
.bound-paths {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}
.bound {
  padding: 3px 8px;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  background: var(--surface-default);
  color: var(--text-secondary);
  font-family: var(--font-mono, monospace);
  font-size: 12px;
  cursor: pointer;
}
.bound[data-selected="true"] {
  border-color: var(--action-primary);
  color: var(--action-primary);
}
</style>
