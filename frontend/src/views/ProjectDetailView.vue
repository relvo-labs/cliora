<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { RouterLink, useRouter } from "vue-router";

import { ApiError } from "../api/client";
import {
  ACTION_PROJECT_MANAGE,
  ACTION_SECRET_MANAGE,
  ACTION_RUN_DISPATCH,
  ACTION_TASK_APPROVE,
  ACTION_TASK_CREATE,
  ACTION_TASK_UPDATE,
  FEATURE_AGENT_RUNS,
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
import PatchProposals from "../components/project/PatchProposals.vue";
import ProjectSecrets from "../components/project/ProjectSecrets.vue";
import TaskBoard from "../components/project/TaskBoard.vue";
import TaskRoadmap from "../components/project/TaskRoadmap.vue";
import AsyncState from "../components/common/AsyncState.vue";
import BaseBadge from "../components/ui/BaseBadge.vue";
import EmptyState from "../components/ui/EmptyState.vue";
import PageHead from "../components/ui/PageHead.vue";
import UiButton from "../components/ui/UiButton.vue";
import UiCard from "../components/ui/UiCard.vue";
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
// **The feature flag and the permission, both** — a flag says what the deployment has,
// a permission says what this person may do, and neither alone is authorization
// (ADR 0027). The server checks both regardless; this only decides what is rendered.
const canManageSecrets = computed(
  () =>
    auth.hasFeature(FEATURE_AGENT_RUNS) &&
    auth.hasPermission(ACTION_SECRET_MANAGE),
);
const canWriteTasks = computed(() => auth.hasPermission(ACTION_TASK_UPDATE));
const canCreateTasks = computed(() => auth.hasPermission(ACTION_TASK_CREATE));
// Both, because sending a requirement to an agent is two acts: creating a card and
// spending compute. `run.dispatch` is deliberately not covered by `task.update` for
// exactly that reason (ADR 0029).
// Deciding a patch proposal is the same authority as approving a specification: both
// are a person saying "this is now the platform's position" (ADR 0034 §6).
const canApprove = computed(() => auth.hasPermission(ACTION_TASK_APPROVE));
const canDispatch = computed(
  () =>
    auth.hasPermission(ACTION_TASK_CREATE) &&
    auth.hasPermission(ACTION_RUN_DISPATCH),
);
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

/**
 * Send a requirement to an agent (RQ-10 §1.2, FR-SPEC-002).
 *
 * **Two requests, and the second one fails often** — every dispatch refusal in this
 * phase lands there (no repository registered, no eligible runner, the four card-kind
 * rules). So the failure path matters more than the success one:
 *
 * * the card **stays**. Deleting it on failure would delete a perfectly good card when
 *   the reason was "no runner is online yet", which is a wait rather than a mistake;
 * * the message names the card and links to it, because by then the card exists and the
 *   person needs to be able to find it;
 * * the requirement row remembers it, so a second click does not make a second card.
 */
const dispatchingId = ref<string | null>(null);
const dispatchedCards = ref<Record<string, { ref: string; id: string }>>({});

async function sendToAgent(
  requirementId: string,
  kind: "clarification" | "decomposition",
  cardRef: string,
): Promise<void> {
  taskError.value = "";
  dispatchingId.value = requirementId;
  let created: { id: string; card_ref: string } | null = null;
  try {
    const result = await api().createTask(props.id, {
      title: kind === "clarification" ? `釐清 ${cardRef}` : `拆解 ${cardRef}`,
      card_kind: kind,
      requirement_id: requirementId,
      // A run that reads code asks better questions; delivery is inert either way, and
      // the server refuses anything else for these kinds.
      source: "repo",
      delivery: "artifact",
      stage: "ready",
    });
    created = { id: result.task.id, card_ref: result.task.card_ref };
    dispatchedCards.value = {
      ...dispatchedCards.value,
      [requirementId]: { ref: result.task.card_ref, id: result.task.id },
    };
    await api().dispatchTask(result.task.id);
    requirements.value = await api().listRequirements(props.id);
  } catch (error) {
    const detail = error instanceof ApiError ? error.message : "派工失敗。";
    taskError.value = created
      ? `卡片 ${created.card_ref} 已建立，但派工被拒：${detail}`
      : detail;
  } finally {
    dispatchingId.value = null;
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
const projectStatusTone = computed(() => {
  if (project.value?.status === "active") return "status-online";
  if (project.value?.status === "paused") return "status-busy";
  return "status-offline";
});
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
      <PageHead>
        <template #title>{{ project.name }}</template>
        <template #subtitle>
          <span class="slug">{{ project.slug }}</span>
          · owned by {{ project.owner_name }} · created
          {{ formatInstant(project.created_at) }}
        </template>
        <template #actions>
          <BaseBadge variant="outline" :tone="projectStatusTone">
            {{ project.status }}
          </BaseBadge>
          <UiButton v-if="canManage" variant="secondary" @click="beginEdit">
            Edit
          </UiButton>
          <UiButton
            v-if="canManage && !isArchived"
            variant="ghost"
            @click="setStatus('archived')"
          >
            Archive
          </UiButton>
          <UiButton
            v-if="canManage && isArchived"
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

      <section v-if="tab === 'board'" class="tab-panel board-panel">
        <div class="workbar">
          <div class="workbar-copy">
            <strong>Delivery board</strong>
            <span
              >WIP limits are advisory. Move cards without losing context.</span
            >
          </div>
          <div v-if="canCreateTasks && !isArchived" class="quick-create">
            <input
              v-model="taskTitle"
              placeholder="新卡片的標題"
              data-new-task
            />
            <UiButton
              variant="primary"
              size="sm"
              :disabled="!taskTitle"
              @click="createTask"
            >
              建立卡片
            </UiButton>
          </div>
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

      <section v-else-if="tab === 'roadmap'" class="tab-panel">
        <div class="workbar roadmap-bar">
          <div class="workbar-copy">
            <strong>Delivery roadmap</strong>
            <span
              >Epic → User Story → Task, with completion rolled upward.</span
            >
          </div>
          <div v-if="canCreateTasks && !isArchived" class="quick-create">
            <input v-model="epicTitle" placeholder="新 Epic" data-new-epic />
            <UiButton size="sm" :disabled="!epicTitle" @click="createEpic">
              建立 Epic
            </UiButton>
            <input
              v-model="storyTitle"
              placeholder="新 User Story"
              data-new-story
            />
            <UiButton size="sm" :disabled="!storyTitle" @click="createStory">
              建立 User Story
            </UiButton>
          </div>
        </div>
        <TaskRoadmap v-if="roadmap" :roadmap="roadmap" />
      </section>

      <section v-else-if="tab === 'requirements'" class="tab-panel">
        <!-- Intake is one field on purpose: it accepts a vague sentence, which is the
             premise of the whole flow (D28). A form with ten required fields at this
             moment is how the flow stops being used. -->
        <div class="workbar requirement-bar">
          <div class="workbar-copy">
            <strong>Requirement intake</strong>
            <span
              >Start with one imperfect sentence; clarification happens
              next.</span
            >
          </div>
          <div v-if="canCreateTasks && !isArchived" class="quick-create">
            <input
              v-model="intakeText"
              placeholder="用一句話說你想要什麼"
              data-new-requirement
            />
            <UiButton
              variant="primary"
              size="sm"
              :disabled="!intakeText"
              @click="submitIntake"
            >
              提出需求
            </UiButton>
          </div>
        </div>
        <!-- Every dispatch refusal this phase added lands here, and until V2.5 this
             panel had nowhere to show one. A refusal a person cannot see is the same as
             a button that silently does nothing. -->
        <p
          v-if="taskError"
          class="notice error"
          role="alert"
          data-requirement-error
        >
          {{ taskError }}
        </p>
        <UiCard v-if="requirements.length" flush>
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
              <!-- Disabled is not enough: a rule people cannot see the reason for is a
                   rule they look for a way round. The API refuses the same thing. -->
              <span
                v-if="canDispatch && !isArchived"
                class="requirement-actions"
              >
                <UiButton
                  size="sm"
                  variant="ghost"
                  :disabled="
                    dispatchingId === item.id ||
                    !['intake', 'clarifying'].includes(item.status)
                  "
                  :title="
                    ['intake', 'clarifying'].includes(item.status)
                      ? '建立一張釐清卡並派給 Agent'
                      : '這個需求已經有規格了'
                  "
                  :data-clarify="item.card_ref"
                  @click="sendToAgent(item.id, 'clarification', item.card_ref)"
                >
                  派給 Agent 釐清
                </UiButton>
                <UiButton
                  size="sm"
                  variant="ghost"
                  :disabled="
                    dispatchingId === item.id || item.status !== 'approved'
                  "
                  :title="
                    item.status === 'approved'
                      ? '建立一張拆解卡並派給 Agent'
                      : '先核准規格。未核准的規格不能被拆解——這是 API 層的規則，不是介面的限制。'
                  "
                  :data-decompose="item.card_ref"
                  @click="sendToAgent(item.id, 'decomposition', item.card_ref)"
                >
                  派給 Agent 拆解
                </UiButton>
              </span>
              <RouterLink
                v-if="dispatchedCards[item.id]"
                class="dispatched-card"
                :data-dispatched="item.card_ref"
                :to="{
                  name: 'task-detail',
                  params: { id: props.id, taskId: dispatchedCards[item.id].id },
                }"
              >
                已建立 {{ dispatchedCards[item.id].ref }}
              </RouterLink>
            </li>
          </ul>
        </UiCard>
        <EmptyState v-else>
          還沒有需求。丟一句模糊的話進來就可以開始。
          <template #action>
            <span class="empty-guidance"
              >需求會先進入收件，再由 Agent 協助釐清。</span
            >
          </template>
        </EmptyState>
      </section>

      <section v-else-if="tab === 'settings'" class="tab-panel">
        <UiCard>
          <template #header>
            <div class="card-heading">
              <span>生效中的流程定義</span>
              <span class="heading-note">唯讀 · 平台管理</span>
            </div>
          </template>
          <p class="muted settings-copy">
            專案沿用平台種子的流程，不能在這裡改寫。
          </p>
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
        </UiCard>
      </section>

      <section v-if="tab === 'overview'" class="tab-panel overview-panel">
        <div class="overview-grid" aria-label="Project summary">
          <UiCard>
            <span class="metric-label">Workspace footprint</span>
            <strong class="metric-number">{{ project.workspace_count }}</strong>
            <span class="metric-caption">
              directories across {{ project.node_count }} nodes
            </span>
          </UiCard>
          <UiCard>
            <span class="metric-label">Active sessions</span>
            <strong class="metric-number">{{
              project.active_session_count
            }}</strong>
            <span class="metric-caption">
              {{
                project.active_session_count
                  ? "work in progress"
                  : "nothing running"
              }}
            </span>
          </UiCard>
          <UiCard>
            <span class="metric-label">Recent changes</span>
            <strong class="metric-number">{{
              projects.activity.length
            }}</strong>
            <span class="metric-caption">latest project events</span>
          </UiCard>
        </div>

        <UiCard v-if="project.description" class="description-card">
          <span class="eyebrow">Project brief</span>
          <p class="description">{{ project.description }}</p>
        </UiCard>

        <!-- Above Workspaces on purpose: after the 2026-08-10 ruling a run does not
             use a workspace binding at all, so "where does this project's code live"
             is now the question a person answers first. -->
        <UiCard class="overview-card">
          <ProjectRepositories :project-id="id" :can-manage="canManage" />
        </UiCard>

        <!-- Secrets sit beside repositories because from V2.3 a repository row means
             "which credential fetches this", and the two are edited together. Gated on
             the runner feature rather than on a permission: a deployment without it has
             no secrets endpoints at all, and they answer 404. -->
        <UiCard v-if="canManageSecrets" class="overview-card">
          <ProjectSecrets :project-id="id" />
        </UiCard>

        <!-- Here rather than in a tab of its own: a project may see zero of these in a
             month, and a sixth tab that is usually empty costs every visit. -->
        <PatchProposals
          :client="api()"
          :project-id="id"
          :can-decide="canApprove"
        />

        <UiCard flush class="overview-card">
          <template #header>
            <div class="card-heading">
              <div>
                <span>Workspace bindings</span>
                <small>Session launch points registered to this project.</small>
              </div>
              <UiButton
                v-if="canManage && !isArchived"
                size="sm"
                :disabled="actionBusy"
                @click="beginBind"
              >
                Bind workspace
              </UiButton>
            </div>
          </template>
          <p v-if="project.workspaces.length === 0" class="card-empty">
            No workspaces bound yet.
          </p>
          <ul v-else class="bindings">
            <li v-for="w in project.workspaces" :key="w.id">
              <span
                class="mark"
                :data-usability="w.usability"
                aria-hidden="true"
              >
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
        </UiCard>

        <UiCard flush class="overview-card">
          <template #header>
            <div class="card-heading">
              <div>
                <span>Recent activity</span>
                <small>The latest changes across this project.</small>
              </div>
              <UiButton size="sm" variant="ghost" @click="tab = 'activity'">
                View all
              </UiButton>
            </div>
          </template>
          <p v-if="projects.activity.length === 0" class="card-empty">
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
        </UiCard>
      </section>

      <section v-else-if="tab === 'activity'" class="tab-panel activity-panel">
        <!--
          Stated, never left blank. A missing actor means one of two different
          things — a system-originated event, or a reader without `audit.view` —
          and silence would let the second read as the first.
        -->
        <p v-if="projects.actorsHidden" class="notice muted">
          Some information is hidden: showing who performed an action requires
          audit permission.
        </p>
        <UiCard flush>
          <template #header>
            <div class="card-heading">
              <div>
                <span>Activity log</span>
                <small
                  >Project, workspace and session events in time order.</small
                >
              </div>
            </div>
          </template>
          <ul class="timeline activity-log">
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
        </UiCard>
        <UiButton
          v-if="projects.activityCursor"
          variant="secondary"
          @click="projects.fetchActivity(props.id, { append: true })"
        >
          Load more
        </UiButton>
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
  border-bottom: 1px solid var(--border-default);
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
  color: var(--status-online);
}
.mark[data-usability="outside_allowed_root"] {
  color: var(--status-busy);
}
.node {
  font-weight: 600;
}
.path {
  color: var(--text-secondary);
  font-family: var(--font-mono);
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
  color: var(--status-error);
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
.tabs button {
  min-height: 40px;
  padding: 0 var(--space-4);
  white-space: nowrap;
}
.tabs button:hover {
  color: var(--text-primary);
  background: var(--surface-default);
}
.tab-panel {
  display: grid;
  gap: var(--space-4);
}
.workbar {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  min-height: 58px;
  padding: var(--space-2) var(--space-3) var(--space-2) var(--space-4);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  background: var(--surface-default);
}
.workbar-copy {
  display: grid;
  gap: 2px;
  min-width: 0;
  margin-right: auto;
}
.workbar-copy strong {
  font-size: var(--font-sm);
}
.workbar-copy span {
  color: var(--text-muted);
  font-size: var(--font-xs);
}
.quick-create {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
.quick-create input {
  width: 220px;
  min-height: 32px;
  padding: 0 var(--space-3);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  color: var(--text-primary);
  background: var(--surface-elevated);
  font-size: var(--font-sm);
}
.requirement-bar .quick-create input {
  width: min(380px, 34vw);
}
.overview-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--space-3);
}
.overview-grid :deep(.body) {
  display: grid;
  gap: var(--space-1);
  min-height: 120px;
  align-content: center;
}
.metric-label,
.eyebrow {
  color: var(--text-muted);
  font-size: var(--font-xs);
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}
.metric-number {
  margin-top: var(--space-1);
  font-size: 28px;
  font-weight: 600;
  line-height: 1;
  letter-spacing: -0.03em;
}
.metric-caption {
  color: var(--text-muted);
  font-size: var(--font-xs);
}
.description-card :deep(.body) {
  display: grid;
  gap: var(--space-2);
}
.description {
  max-width: 76ch;
  color: var(--text-secondary);
  line-height: 1.65;
}
.overview-card {
  margin: 0;
}
.card-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  width: 100%;
  font-size: var(--font-sm);
}
.card-heading > div {
  display: grid;
  gap: 2px;
}
.card-heading small,
.heading-note {
  color: var(--text-muted);
  font-size: var(--font-xs);
  font-weight: 400;
}
.card-empty {
  margin: 0;
  padding: var(--space-5) var(--space-4);
  color: var(--text-muted);
  font-size: var(--font-sm);
}
.bindings,
.timeline {
  border: 0;
  border-radius: 0;
  background: transparent;
}
.bindings li,
.timeline li {
  min-height: 46px;
  padding: var(--space-3) var(--space-4);
}
.timeline li {
  position: relative;
  padding-left: var(--space-5);
}
.timeline li::before {
  position: absolute;
  left: var(--space-3);
  width: 6px;
  height: 6px;
  border-radius: 50%;
  content: "";
  background: var(--action-primary);
}
.activity-log:empty::after {
  display: block;
  padding: var(--space-5);
  color: var(--text-muted);
  content: "No activity yet.";
}
.requirements {
  list-style: none;
  margin: 0;
  padding: 0;
}
.requirements li {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: var(--space-4);
  min-height: 58px;
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--border-default);
}
.requirements li:last-child {
  border-bottom: 0;
}
.requirements a {
  display: flex;
  align-items: baseline;
  gap: var(--space-3);
  min-width: 0;
  color: var(--text-primary);
  font-weight: 600;
  text-decoration: none;
}
.requirements a:hover {
  color: var(--action-primary);
}
.requirements .ref {
  flex: none;
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: var(--font-xs);
  font-weight: 400;
}
.requirement-actions {
  display: inline-flex;
  gap: var(--space-2);
}
.dispatched-card {
  font-size: var(--font-xs);
  color: var(--text-muted);
}
.requirements .status {
  padding: 2px 8px;
  border: 1px solid var(--border-default);
  border-radius: 999px;
  color: var(--text-muted);
  font-size: var(--font-xs);
  font-weight: 600;
}
.empty-guidance {
  color: var(--text-muted);
  font-size: var(--font-xs);
}
.settings-copy {
  margin-top: 0;
}
.process-settings {
  display: grid;
  grid-template-columns: minmax(120px, 0.35fr) minmax(0, 1fr);
  margin: var(--space-4) 0 0;
  border-top: 1px solid var(--border-default);
}
.process-settings dt,
.process-settings dd {
  margin: 0;
  padding: var(--space-3) 0;
  border-bottom: 1px solid var(--border-default);
}
.process-settings dt {
  color: var(--text-muted);
  font-size: var(--font-xs);
  font-weight: 600;
}
.process-settings dd {
  color: var(--text-secondary);
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
