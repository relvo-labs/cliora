<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { RouterLink, useRouter } from "vue-router";

import { ApiError } from "../api/client";
import {
  ACTION_PROJECT_MANAGE,
  ACTION_TASK_CREATE,
  ACTION_TASK_UPDATE,
} from "../api/dto";
import type {
  Board,
  ProcessDefinition,
  Requirement,
  Roadmap,
  BindingUsability,
  NodeDetail,
  NodeSummary,
  ProjectStatus,
  ProjectWorkspace,
} from "../api/dto";
import AppLayout from "../components/layout/AppLayout.vue";
import ProjectRepositories from "../components/project/ProjectRepositories.vue";
import TaskBoard from "../components/project/TaskBoard.vue";
import TaskRoadmap from "../components/project/TaskRoadmap.vue";
import AsyncState from "../components/common/AsyncState.vue";
import { useAsyncResource } from "../composables/useAsyncResource";
import { api, useAuthStore } from "../stores/auth";
import { useNodesStore } from "../stores/nodes";
import { useProjectsStore } from "../stores/projects";
import { kindLabel } from "../utils/activityKinds";
import { formatInstant } from "../utils/time";

const props = defineProps<{ id: string }>();

const auth = useAuthStore();
const nodes = useNodesStore();
const projects = useProjectsStore();
const router = useRouter();

const canManage = computed(() => auth.hasPermission(ACTION_PROJECT_MANAGE));
const canWriteTasks = computed(() => auth.hasPermission(ACTION_TASK_UPDATE));
const canCreateTasks = computed(() => auth.hasPermission(ACTION_TASK_CREATE));
// In the query string, so a reload lands where the user was rather than back on
// Overview — a board is a place people leave open.
const tab = ref<
  "overview" | "board" | "roadmap" | "requirements" | "activity" | "settings"
>(
  (router.currentRoute.value.query.tab as
    | "overview"
    | "board"
    | "roadmap"
    | "requirements"
    | "activity"
    | "settings") ?? "overview",
);
watch(tab, (value) => {
  void router.replace({
    query: { ...router.currentRoute.value.query, tab: value },
  });
});

const board = ref<Board | null>(null);
const roadmap = ref<Roadmap | null>(null);
const processDefinition = ref<ProcessDefinition | null>(null);
const requirements = ref<Requirement[]>([]);
const intakeText = ref("");
const taskTitle = ref("");
const epicTitle = ref("");
const storyTitle = ref("");
const taskError = ref("");

/** One reload for the whole task layer.
 *
 * Board *and* roadmap, because a card that moved changed both, and leaving one stale
 * is how a user ends up trusting neither. Three requests on a tab switch is cheaper
 * than a wrong number on a screen. */
async function reloadTasks(): Promise<void> {
  const [nextBoard, nextRoadmap, nextProcess] = await Promise.all([
    api().getBoard(props.id),
    api().getRoadmap(props.id),
    api().getProcess(props.id),
  ]);
  board.value = nextBoard;
  roadmap.value = nextRoadmap;
  processDefinition.value = nextProcess;
}

async function createEpic(): Promise<void> {
  await api().createEpic(props.id, { title: epicTitle.value });
  epicTitle.value = "";
  await reloadTasks();
}

async function createStory(): Promise<void> {
  await api().createUserStory(props.id, { title: storyTitle.value });
  storyTitle.value = "";
  await reloadTasks();
}

async function openCard(taskId: string): Promise<void> {
  await router.push({ name: "task-detail", params: { id: props.id, taskId } });
}

async function createTask(): Promise<void> {
  taskError.value = "";
  try {
    await api().createTask(props.id, { title: taskTitle.value });
    taskTitle.value = "";
    await reloadTasks();
  } catch (error) {
    taskError.value = error instanceof ApiError ? error.message : "建立失敗。";
  }
}

async function submitIntake(): Promise<void> {
  taskError.value = "";
  try {
    await api().createRequirement(props.id, { raw_text: intakeText.value });
    intakeText.value = "";
    requirements.value = await api().listRequirements(props.id);
  } catch (error) {
    taskError.value = error instanceof ApiError ? error.message : "建立失敗。";
  }
}

watch(
  tab,
  async (value) => {
    if (value === "board" || value === "roadmap" || value === "settings") {
      if (!board.value) await reloadTasks();
    }
    if (value === "requirements" && requirements.value.length === 0) {
      requirements.value = await api().listRequirements(props.id);
    }
  },
  { immediate: true },
);

const resource = useAsyncResource(async () => {
  await projects.fetchProject(props.id);
  await projects.fetchActivity(props.id);
});

onMounted(() => resource.run());

const project = computed(() => projects.current);
const isArchived = computed(() => project.value?.status === "archived");
const requestId = computed(() => {
  const error = resource.error.value;
  return error instanceof ApiError ? error.requestId : undefined;
});

const editing = ref(false);
const editName = ref("");
const editDescription = ref("");
const editStatus = ref<ProjectStatus>("active");
const actionBusy = ref(false);
const actionError = ref("");
const actionRequestId = ref<string>();

const binding = ref(false);
const nodeOptions = ref<NodeSummary[]>([]);
const bindNodeId = ref("");
const bindNode = ref<NodeDetail | null>(null);
const bindPath = ref("");
const bindLabel = ref("");
const bindPrimary = ref(false);

const enabledRoots = computed(() =>
  (bindNode.value?.workspace_roots ?? []).filter((root) => root.is_enabled),
);

// Indicator plus words, never colour alone. The four values are the same
// vocabulary as workspace favourites, because the question is the same one.
const USABILITY: Record<BindingUsability, { mark: string; text: string }> = {
  usable: { mark: "●", text: "" },
  node_offline: { mark: "○", text: "Machine offline" },
  node_disabled: { mark: "○", text: "Machine removed or disabled" },
  outside_allowed_root: {
    mark: "○",
    text: "This machine no longer allows this directory",
  },
};

function usable(binding: ProjectWorkspace): boolean {
  return binding.usability === "usable";
}

// The event's own words, assembled from the payload. Kept here rather than sent by
// the server so the wording can change without a migration.
function describe(kind: string, payload: Record<string, unknown>): string {
  const path = typeof payload.path === "string" ? payload.path : "";
  const node = typeof payload.node_name === "string" ? payload.node_name : "";
  switch (kind) {
    case "project.created":
      return String(payload.name ?? "");
    case "project.updated":
      return payload.from && payload.to
        ? `${payload.from} → ${payload.to}`
        : ((payload.changed as string[] | undefined)?.join(", ") ?? "");
    case "workspace.bound":
    case "workspace.unbound":
      return node ? `${node}:${path}` : path;
    case "session.started":
      return String(payload.name ?? payload.runtime ?? "");
    case "session.ended":
      return String(payload.status ?? "");
    default:
      return "";
  }
}

async function openSession(binding: ProjectWorkspace): Promise<void> {
  // Not a new flow: the existing New Session dialog, prefilled. V2.0 deliberately
  // stops short of a one-click start, which needs a task to start *on* (V2.1).
  await router.push({
    name: "sessions",
    query: {
      node_id: binding.node_id,
      workspace: binding.path,
      project_id: props.id,
    },
  });
}

async function setStatus(status: "active" | "archived"): Promise<void> {
  await perform(async () => {
    await projects.update(props.id, { status });
    await resource.run();
  });
}

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
  await perform(async () => {
    await projects.update(props.id, {
      name: editName.value.trim(),
      description: editDescription.value.trim(),
      status: editStatus.value,
    });
    editing.value = false;
    await resource.run();
  });
}

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
    recordActionError(error, "Could not load nodes.");
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
    recordActionError(error, "Could not load that node's workspace roots.");
  }
});

async function saveBinding(): Promise<void> {
  if (!bindNodeId.value || !bindPath.value.trim()) return;
  await perform(async () => {
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

async function unbind(bindingId: string): Promise<void> {
  await perform(async () => {
    await projects.unbindWorkspace(props.id, bindingId);
    await resource.run();
  });
}

async function perform(operation: () => Promise<void>): Promise<void> {
  actionBusy.value = true;
  actionError.value = "";
  actionRequestId.value = undefined;
  try {
    await operation();
  } catch (error) {
    recordActionError(error, "The project could not be updated.");
  } finally {
    actionBusy.value = false;
  }
}

function recordActionError(error: unknown, fallback: string): void {
  actionError.value = error instanceof ApiError ? error.message : fallback;
  actionRequestId.value =
    error instanceof ApiError ? error.requestId : undefined;
}
</script>

<template>
  <AppLayout>
    <div
      v-if="resource.state.value === 'loading'"
      class="skeleton"
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
      <header class="head">
        <div>
          <h1>{{ project.name }}</h1>
          <p>
            <span class="slug">{{ project.slug }}</span>
            · owned by {{ project.owner_name }} · created
            {{ formatInstant(project.created_at) }}
          </p>
        </div>
        <div class="head-actions">
          <span class="pill" :data-status="project.status">{{
            project.status
          }}</span>
          <button v-if="canManage" class="ghost" @click="beginEdit">
            Edit
          </button>
          <button
            v-if="canManage && !isArchived"
            class="ghost"
            @click="setStatus('archived')"
          >
            Archive
          </button>
          <button
            v-if="canManage && isArchived"
            class="ghost"
            @click="setStatus('active')"
          >
            Un-archive
          </button>
        </div>
      </header>

      <p v-if="isArchived" class="notice">
        This project is archived. Existing sessions and bindings are untouched,
        but it accepts no new ones until it is un-archived.
      </p>
      <p v-if="actionError" class="notice error" role="alert">
        {{ actionError }}
        <small v-if="actionRequestId">Request ID: {{ actionRequestId }}</small>
      </p>

      <nav class="tabs">
        <button :data-active="tab === 'overview'" @click="tab = 'overview'">
          Overview
        </button>
        <button
          :data-active="tab === 'board'"
          data-tab="board"
          @click="tab = 'board'"
        >
          Board
        </button>
        <button
          :data-active="tab === 'roadmap'"
          data-tab="roadmap"
          @click="tab = 'roadmap'"
        >
          Roadmap
        </button>
        <button
          :data-active="tab === 'requirements'"
          data-tab="requirements"
          @click="tab = 'requirements'"
        >
          Requirements
        </button>
        <button :data-active="tab === 'activity'" @click="tab = 'activity'">
          Activity
        </button>
        <button
          :data-active="tab === 'settings'"
          data-tab="settings"
          @click="tab = 'settings'"
        >
          Settings
        </button>
      </nav>

      <section v-if="tab === 'board'">
        <div v-if="canCreateTasks && !isArchived" class="quick-create">
          <input v-model="taskTitle" placeholder="新卡片的標題" data-new-task />
          <button class="ghost" :disabled="!taskTitle" @click="createTask">
            建立
          </button>
        </div>
        <p v-if="taskError" class="notice error" role="alert">
          {{ taskError }}
        </p>
        <TaskBoard
          v-if="board"
          :board="board"
          :client="api()"
          :can-write="canWriteTasks && !isArchived"
          @changed="reloadTasks"
          @open="openCard"
        />
      </section>

      <section v-else-if="tab === 'roadmap'">
        <div v-if="canCreateTasks && !isArchived" class="quick-create">
          <input v-model="epicTitle" placeholder="新 Epic" data-new-epic />
          <button class="ghost" :disabled="!epicTitle" @click="createEpic">
            建立 Epic
          </button>
          <input
            v-model="storyTitle"
            placeholder="新 User Story"
            data-new-story
          />
          <button class="ghost" :disabled="!storyTitle" @click="createStory">
            建立 User Story
          </button>
        </div>
        <TaskRoadmap v-if="roadmap" :roadmap="roadmap" />
      </section>

      <section v-else-if="tab === 'requirements'">
        <!-- Intake is one field on purpose: it accepts a vague sentence, which is the
             premise of the whole flow (D28). A form with ten required fields at this
             moment is how the flow stops being used. -->
        <div v-if="canCreateTasks && !isArchived" class="quick-create">
          <input
            v-model="intakeText"
            placeholder="用一句話說你想要什麼"
            data-new-requirement
          />
          <button class="ghost" :disabled="!intakeText" @click="submitIntake">
            提出
          </button>
        </div>
        <ul class="requirements">
          <li
            v-for="item in requirements"
            :key="item.id"
            :data-status="item.status"
          >
            <RouterLink
              :to="{
                name: 'requirement-detail',
                params: { id: props.id, requirementId: item.id },
              }"
            >
              <span class="ref">{{ item.card_ref }}</span>
              {{ item.raw_text }}
            </RouterLink>
            <span class="status">{{ item.status }}</span>
          </li>
          <li v-if="requirements.length === 0" class="empty">
            還沒有需求。丟一句模糊的話進來就可以開始。
          </li>
        </ul>
      </section>

      <section v-else-if="tab === 'settings'">
        <h2>生效中的流程定義</h2>
        <p class="muted">唯讀；流程由平台種子管理，專案不能在這裡改寫。</p>
        <dl v-if="processDefinition" class="process-settings">
          <dt>版本</dt>
          <dd>{{ processDefinition.version }}</dd>
          <dt>來源</dt>
          <dd>{{ processDefinition.source }}</dd>
          <template v-for="gate in processDefinition.gates" :key="gate.key">
            <dt>{{ gate.label }}</dt>
            <dd>
              {{ gate.enabled ? "啟用" : `停用：${gate.disabled_reason}` }}
              <RouterLink
                v-if="gate.key === 'ui' && !gate.enabled"
                to="/settings/integrations"
              >
                前往整合設定
              </RouterLink>
            </dd>
          </template>
        </dl>
      </section>

      <section v-if="tab === 'overview'">
        <p v-if="project.description" class="description">
          {{ project.description }}
        </p>

        <!-- Above Workspaces on purpose: after the 2026-08-10 ruling a run does not
             use a workspace binding at all, so "where does this project's code live"
             is now the question a person answers first. -->
        <ProjectRepositories :project-id="id" :can-manage="canManage" />

        <div class="section-head">
          <h2>Workspaces</h2>
          <button
            v-if="canManage && !isArchived"
            class="ghost"
            :disabled="actionBusy"
            @click="beginBind"
          >
            Bind workspace
          </button>
        </div>
        <p v-if="project.workspaces.length === 0" class="muted">
          No workspaces bound yet.
        </p>
        <ul v-else class="bindings">
          <li v-for="w in project.workspaces" :key="w.id">
            <span class="mark" :data-usability="w.usability" aria-hidden="true">
              {{ USABILITY[w.usability].mark }}
            </span>
            <span class="node">{{ w.node_name }}</span>
            <span class="path" :title="w.path">{{ w.path }}</span>
            <span v-if="w.is_primary" class="tag">primary</span>
            <span v-if="!usable(w)" class="reason">
              {{ USABILITY[w.usability].text }}
            </span>
            <span class="spacer" />
            <button
              class="link"
              :disabled="!usable(w) || isArchived"
              :title="usable(w) ? '' : USABILITY[w.usability].text"
              @click="openSession(w)"
            >
              Open session
            </button>
            <button
              v-if="canManage"
              class="link danger"
              :disabled="actionBusy"
              @click="unbind(w.id)"
            >
              Unbind
            </button>
          </li>
        </ul>

        <h2>Recent activity</h2>
        <p v-if="projects.activity.length === 0" class="muted">
          Nothing has happened yet. Bind a workspace, or start a session from
          one.
        </p>
        <ul v-else class="timeline">
          <li v-for="event in projects.activity.slice(0, 10)" :key="event.id">
            <span class="when" :title="event.occurred_at">{{
              formatInstant(event.occurred_at)
            }}</span>
            <span class="what">{{ kindLabel(event.kind) }}</span>
            <span class="detail">{{
              describe(event.kind, event.payload)
            }}</span>
            <span class="who">{{ event.actor_name ?? "—" }}</span>
          </li>
        </ul>
      </section>

      <section v-else>
        <!--
          Stated, never left blank. A missing actor means one of two different
          things — a system-originated event, or a reader without `audit.view` —
          and silence would let the second read as the first.
        -->
        <p v-if="projects.actorsHidden" class="notice muted">
          Some information is hidden: showing who performed an action requires
          audit permission.
        </p>
        <ul class="timeline">
          <li v-for="event in projects.activity" :key="event.id">
            <span class="when" :title="event.occurred_at">{{
              formatInstant(event.occurred_at)
            }}</span>
            <span class="what">{{ kindLabel(event.kind) }}</span>
            <span class="detail">{{
              describe(event.kind, event.payload)
            }}</span>
            <span class="who">{{ event.actor_name ?? "—" }}</span>
          </li>
        </ul>
        <button
          v-if="projects.activityCursor"
          class="ghost"
          @click="projects.fetchActivity(props.id, { append: true })"
        >
          Load more
        </button>
      </section>
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
          <button class="ghost" @click="editing = false">Cancel</button>
          <button
            class="primary"
            :disabled="actionBusy || !editName.trim()"
            @click="saveEdit"
          >
            Save
          </button>
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
          <button class="ghost" @click="binding = false">Cancel</button>
          <button
            class="primary"
            :disabled="actionBusy || !bindNodeId || !bindPath.trim()"
            @click="saveBinding"
          >
            Bind
          </button>
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
  font-family: var(--font-mono, monospace);
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
  border: 1px solid var(--status-warning, var(--border-focus));
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
.tabs button {
  padding: 8px 14px;
  border: none;
  background: none;
  color: var(--text-secondary);
  font-size: 13px;
  cursor: pointer;
}
.tabs button[data-active="true"] {
  color: var(--action-primary);
  font-weight: 600;
  box-shadow: inset 0 -2px 0 var(--action-primary);
}
h2 {
  margin: 20px 0 8px;
  font-size: 14px;
  color: var(--text-secondary);
}
.description {
  margin: 0;
  white-space: pre-wrap;
  font-size: 13px;
}
.muted {
  color: var(--text-muted);
  font-size: 13px;
}
.bindings,
.timeline {
  list-style: none;
  margin: 0;
  padding: 0;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  background: var(--surface-default);
}
.bindings li,
.timeline li {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  border-bottom: 1px solid var(--border-subtle, var(--border-default));
  font-size: 13px;
}
.bindings li:last-child,
.timeline li:last-child {
  border-bottom: none;
}
.spacer {
  flex: 1;
}
.mark[data-usability="usable"] {
  color: var(--status-success, seagreen);
}
.mark[data-usability="outside_allowed_root"] {
  color: var(--status-warning, darkorange);
}
.node {
  font-weight: 600;
}
.path {
  color: var(--text-secondary);
  font-family: var(--font-mono, monospace);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 40ch;
}
.tag {
  padding: 1px 6px;
  border-radius: 999px;
  background: var(--surface-canvas);
  color: var(--text-muted);
  font-size: 11px;
}
.reason {
  color: var(--text-muted);
  font-size: 12px;
}
.when {
  color: var(--text-muted);
  min-width: 13ch;
}
.what {
  font-weight: 600;
}
.detail {
  color: var(--text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.who {
  margin-left: auto;
  color: var(--text-muted);
}
.link.danger {
  color: var(--status-danger, crimson);
}
.notice.error {
  color: var(--status-danger, crimson);
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
</style>
