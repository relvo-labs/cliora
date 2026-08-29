<script setup lang="ts">
/**
 * One project's chrome, and a `<RouterView>` where the page used to be (PX-64, D117).
 *
 * This replaces `views/ProjectDetailView.vue` — 1,515 lines coordinating six tabs, four
 * independently fetched DTOs, two dialogs and its own query-string state machine. The
 * split is not tidiness: the tab bar's `v-if` chain meant every tab's markup and styles
 * were part of every visit, and `beta.1` was about to add a board, a backlog, a drawer
 * and an overview to it.
 *
 * **Replacement, not coexistence** (D117). The old file is deleted in the same change,
 * and `?tab=` keeps working through a redirect in the router rather than a compatibility
 * branch here — a redirect is visibly temporary and a branch is not.
 *
 * What lives here is what is true of the *project* rather than of a page: the load and
 * permission states, the header, the sub-navigation, the archive banner, one shared error
 * strip, and the two dialogs that edit the project itself. Everything else moved into
 * `views/`.
 */
import { computed, onMounted, ref, watch } from "vue";
import { RouterLink, RouterView, useRouter } from "vue-router";

import { ApiError } from "../../api/client";
import type { NodeDetail, NodeSummary, ProjectStatus } from "../../api/dto";
import AsyncState from "../../components/common/AsyncState.vue";
import AppLayout from "../../components/layout/AppLayout.vue";
import BaseBadge from "../../components/ui/BaseBadge.vue";
import PageHead from "../../components/ui/PageHead.vue";
import UiButton from "../../components/ui/UiButton.vue";
import { useNodesStore } from "../../stores/nodes";
import { useProjectsStore } from "../../stores/projects";
import { formatInstant } from "../../utils/time";
import { createProjectContext } from "./useProjectContext";

const props = defineProps<{ id: string }>();

const nodes = useNodesStore();
const projects = useProjectsStore();
const router = useRouter();

const binding = ref(false);
const context = createProjectContext(props.id, {
  openBindDialog: () => void beginBind(),
});
const {
  project,
  resource,
  isArchived,
  can,
  actionError,
  actionRequestId,
  actionBusy,
} = context;

/** The sub-routes, in the order a person meets them.
 *
 *  Overview first because it answers "what is this"; Work second because it is where
 *  people live. Knowledge is a sibling route that predates this shell (`alpha.3`) and is
 *  listed here so the navigation is complete rather than nearly so.
 */
const SECTIONS = [
  { name: "project-overview", label: "Overview" },
  { name: "project-work", label: "Work" },
  { name: "project-roadmap", label: "Roadmap" },
  { name: "project-requirements", label: "Requirements" },
  { name: "project-knowledge", label: "Knowledge" },
  { name: "project-activity", label: "Activity" },
  { name: "project-settings", label: "Settings" },
] as const;

const requestId = computed(() => {
  const error = resource.error.value;
  return error instanceof ApiError ? error.requestId : undefined;
});
const projectStatusTone = computed(() => {
  if (project.value?.status === "active") return "status-online";
  if (project.value?.status === "paused") return "status-busy";
  return "status-offline";
});
const activeSection = computed(() =>
  String(router.currentRoute.value.name ?? ""),
);

onMounted(() => resource.run());

// --- editing the project itself -------------------------------------------------

const editing = ref(false);
const editName = ref("");
const editDescription = ref("");
const editStatus = ref<ProjectStatus>("active");

function beginEdit(): void {
  if (!project.value) return;
  editName.value = project.value.name;
  editDescription.value = project.value.description ?? "";
  editStatus.value = project.value.status;
  actionError.value = "";
  editing.value = true;
}

async function saveEdit(): Promise<void> {
  if (!editName.value.trim()) return;
  await context.perform(async () => {
    await projects.update(props.id, {
      name: editName.value.trim(),
      description: editDescription.value.trim(),
      status: editStatus.value,
    });
    editing.value = false;
    await resource.run();
  });
}

async function setStatus(status: "active" | "archived"): Promise<void> {
  await context.perform(async () => {
    await projects.update(props.id, { status });
    await resource.run();
  });
}

// --- binding a workspace --------------------------------------------------------

const nodeOptions = ref<NodeSummary[]>([]);
const bindNodeId = ref("");
const bindNode = ref<NodeDetail | null>(null);
const bindPath = ref("");
const bindLabel = ref("");
const bindPrimary = ref(false);

const enabledRoots = computed(() =>
  (bindNode.value?.workspace_roots ?? []).filter((root) => root.is_enabled),
);

async function beginBind(): Promise<void> {
  actionError.value = "";
  bindNodeId.value = "";
  bindNode.value = null;
  bindPath.value = "";
  bindLabel.value = "";
  bindPrimary.value = (project.value?.workspaces.length ?? 0) === 0;
  binding.value = true;
  try {
    nodeOptions.value = await nodes.fetchList();
  } catch (error) {
    context.recordActionError(error, "Could not load nodes.");
  }
}

watch(bindNodeId, async (id) => {
  bindNode.value = null;
  bindPath.value = "";
  if (!id) return;
  try {
    bindNode.value = await nodes.fetchNode(id);
    bindPath.value = enabledRoots.value[0]?.path ?? "";
  } catch (error) {
    context.recordActionError(
      error,
      "Could not load that node's workspace roots.",
    );
  }
});

async function saveBinding(): Promise<void> {
  if (!bindNodeId.value || !bindPath.value.trim()) return;
  await context.perform(async () => {
    await projects.bindWorkspace(props.id, {
      node_id: bindNodeId.value,
      path: bindPath.value.trim(),
      label: bindLabel.value.trim() || undefined,
      is_primary: bindPrimary.value,
    });
    binding.value = false;
    await resource.run();
  });
}
</script>

<template>
  <AppLayout>
    <div
      v-if="resource.state.value === 'loading'"
      class="skeleton"
      role="status"
      aria-label="Loading project"
    >
      <span /><span /><span />
    </div>
    <AsyncState
      v-else-if="resource.state.value === 'forbidden'"
      state="forbidden"
    >
      You do not have permission to view this project.
    </AsyncState>
    <AsyncState v-else-if="resource.state.value === 'error'" state="error">
      Could not load this project. It may have been removed, or the project
      layer may not be enabled in this deployment.
      <small v-if="requestId">Request ID: {{ requestId }}</small>
      <button class="link" @click="resource.run()">Retry</button>
    </AsyncState>

    <template v-else-if="project">
      <PageHead>
        <template #title>{{ project.name }}</template>
        <template #subtitle>
          <span class="slug">{{ project.slug }}</span>
          · owned by {{ project.owner_name }} · created
          <span data-visual-mask>{{ formatInstant(project.created_at) }}</span>
        </template>
        <template #actions>
          <BaseBadge variant="outline" :tone="projectStatusTone">
            {{ project.status }}
          </BaseBadge>
          <UiButton
            v-if="can.manage.value"
            variant="secondary"
            @click="beginEdit"
          >
            Edit
          </UiButton>
          <UiButton
            v-if="can.manage.value && !isArchived"
            variant="ghost"
            @click="setStatus('archived')"
          >
            Archive
          </UiButton>
          <UiButton
            v-if="can.manage.value && isArchived"
            variant="ghost"
            @click="setStatus('active')"
          >
            Un-archive
          </UiButton>
        </template>
      </PageHead>

      <p v-if="isArchived" class="notice">
        This project is archived. Existing sessions and bindings are untouched,
        but it accepts no new ones until it is un-archived.
      </p>
      <!-- One strip for the page. Two error banners stacked above a board is how a
           reader stops reading either. -->
      <p v-if="actionError" class="notice error" role="alert">
        {{ actionError }}
        <small v-if="actionRequestId">Request ID: {{ actionRequestId }}</small>
      </p>

      <!-- Links, not buttons. Each section is a URL now, so middle-click and "copy link
           address" work on the navigation the way they already did on the breadcrumb. -->
      <nav class="tabs" aria-label="Project sections">
        <RouterLink
          v-for="section in SECTIONS"
          :key="section.name"
          :to="{ name: section.name, params: { id } }"
          :data-active="activeSection === section.name"
          :data-tab="section.label.toLowerCase()"
        >
          {{ section.label }}
        </RouterLink>
      </nav>

      <RouterView />
    </template>

    <div v-if="editing" class="dialog-backdrop" @click.self="editing = false">
      <div class="dialog" role="dialog" aria-label="Edit project">
        <h2>Edit project</h2>
        <label>Name <input v-model="editName" maxlength="128" /></label>
        <label>
          Description
          <textarea v-model="editDescription" rows="4" />
        </label>
        <label>
          Status
          <select v-model="editStatus">
            <option value="active">Active</option>
            <option value="paused">Paused</option>
            <option value="archived">Archived</option>
          </select>
        </label>
        <div class="dialog-actions">
          <UiButton variant="ghost" @click="editing = false">Cancel</UiButton>
          <UiButton
            variant="primary"
            :disabled="actionBusy || !editName.trim()"
            @click="saveEdit"
          >
            Save
          </UiButton>
        </div>
      </div>
    </div>

    <div v-if="binding" class="dialog-backdrop" @click.self="binding = false">
      <div class="dialog" role="dialog" aria-label="Bind workspace">
        <h2>Bind workspace</h2>
        <label>
          Node
          <select v-model="bindNodeId">
            <option value="" disabled>Select a node…</option>
            <option v-for="node in nodeOptions" :key="node.id" :value="node.id">
              {{ node.name }} · {{ node.status }}
            </option>
          </select>
        </label>
        <label>
          Path
          <input
            v-model="bindPath"
            list="project-bind-roots"
            placeholder="/path/inside/an/allowed/root"
          />
          <datalist id="project-bind-roots">
            <option
              v-for="root in enabledRoots"
              :key="root.path"
              :value="root.path"
            />
          </datalist>
        </label>
        <p v-if="bindNode && enabledRoots.length === 0" class="hint">
          This node has no enabled workspace root.
        </p>
        <label>Label <input v-model="bindLabel" maxlength="128" /></label>
        <label class="check"
          ><input v-model="bindPrimary" type="checkbox" /> Primary
          binding</label
        >
        <div class="dialog-actions">
          <UiButton variant="ghost" @click="binding = false">Cancel</UiButton>
          <UiButton
            variant="primary"
            :disabled="actionBusy || !bindNodeId || !bindPath.trim()"
            @click="saveBinding"
          >
            Bind
          </UiButton>
        </div>
      </div>
    </div>
  </AppLayout>
</template>

<style scoped>
.head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  margin-bottom: 16px;
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
.head-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 20px;
}
.section-head h2 {
  margin-top: 0;
}
.slug {
  font-family: var(--font-mono);
}
.pill {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 11px;
  background: var(--surface-canvas);
  color: var(--text-secondary);
}
.pill[data-status="paused"] {
  border: 1px solid var(--status-busy);
  background: transparent;
}
.pill[data-status="archived"] {
  color: var(--text-muted);
}
.notice {
  margin: 0 0 16px;
  padding: 10px 12px;
  border-radius: var(--radius-sm);
  background: var(--surface-canvas);
  color: var(--text-secondary);
  font-size: 13px;
}
.tabs {
  display: flex;
  gap: 4px;
  margin-bottom: 16px;
  border-bottom: 1px solid var(--border-default);
}
.tabs a {
  padding: 8px 14px;
  border: none;
  background: none;
  color: var(--text-secondary);
  font-size: 13px;
  cursor: pointer;
}
.tabs a[data-active="true"] {
  color: var(--action-primary);
  font-weight: 600;
  box-shadow: inset 0 -2px 0 var(--action-primary);
}
h2 {
  margin: 20px 0 8px;
  font-size: 14px;
  color: var(--text-secondary);
}
.muted {
  color: var(--text-muted);
  font-size: 13px;
}
.notice.error {
  color: var(--status-error);
}
.notice small,
.async small {
  display: block;
  margin-top: 4px;
}
.skeleton {
  display: grid;
  gap: 12px;
}
.skeleton span {
  height: 18px;
  border-radius: var(--radius-sm);
  background: var(--surface-elevated);
}
.skeleton span:nth-child(1) {
  width: 36%;
  height: 30px;
}
.skeleton span:nth-child(2) {
  width: 68%;
}
.dialog-backdrop {
  position: fixed;
  inset: 0;
  z-index: 20;
  display: grid;
  place-items: center;
  background: rgb(0 0 0 / 40%);
}
.dialog {
  width: min(480px, 92vw);
  padding: 20px;
  border-radius: var(--radius-md);
  background: var(--surface-elevated);
  display: grid;
  gap: 12px;
}
.dialog h2 {
  margin: 0;
}
.dialog label {
  display: grid;
  gap: 6px;
  font-size: 13px;
}
.dialog input,
.dialog textarea,
.dialog select {
  padding: 8px 10px;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  background: var(--surface-default);
  color: var(--text-primary);
}
.dialog .check {
  display: flex;
  align-items: center;
}
.dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
.hint {
  margin: 0;
  color: var(--text-muted);
  font-size: 12px;
}

/* Project workbench — mirrors the reviewed prototype's calm, dense hierarchy. */
.tabs {
  gap: 0;
  margin-bottom: var(--space-4);
  overflow-x: auto;
  scrollbar-width: thin;
}
.tabs a {
  min-height: 40px;
  padding: 0 var(--space-4);
  white-space: nowrap;
}
.tabs a:hover {
  color: var(--text-primary);
  background: var(--surface-default);
}
.tab-panel {
  display: grid;
  gap: var(--space-4);
}
.dialog {
  padding: var(--space-5);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  box-shadow: 0 18px 48px
    color-mix(in srgb, var(--text-primary) 18%, transparent);
}
.dialog input,
.dialog textarea,
.dialog select {
  min-height: 38px;
}
@media (max-width: 980px) {
  .workbar,
  .roadmap-bar,
  .requirement-bar {
    align-items: stretch;
    flex-direction: column;
  }
  .workbar-copy {
    margin-right: 0;
  }
  .quick-create {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    width: 100%;
  }
  .quick-create input,
  .requirement-bar .quick-create input {
    width: 100%;
    min-width: 0;
  }
}
@media (max-width: 700px) {
  .overview-grid {
    grid-template-columns: 1fr;
  }
  .bindings li,
  .timeline li {
    align-items: flex-start;
    flex-wrap: wrap;
  }
  .path,
  .detail {
    max-width: 100%;
  }
  .who {
    margin-left: 0;
  }
}
</style>
