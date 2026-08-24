<script setup lang="ts">
/**
 * "What is this project" (PX-64). Formerly `?tab=overview`, and the default landing page.
 *
 * The ordering is a decision rather than an accident. Repositories sit **above**
 * workspaces because after the 2026-08-10 ruling a run does not use a workspace binding
 * at all, so "where does this project's code live" is the question a person answers first.
 * Secrets sit beside repositories because from V2.3 a repository row means "which
 * credential fetches this", and the two are edited together.
 *
 * `PX-50` replaces this page with the attention strip, work distribution and the rest.
 * This ticket only moved it.
 */
import { computed, onMounted, ref } from "vue";
import { RouterLink, useRouter } from "vue-router";

import type {
  BindingUsability,
  ProjectWorkspace,
  WorkCounts,
} from "../../../api/dto";
import ProjectRepositories from "../../../components/project/ProjectRepositories.vue";
import ProjectSecrets from "../../../components/project/ProjectSecrets.vue";
import UiButton from "../../../components/ui/UiButton.vue";
import UiCard from "../../../components/ui/UiCard.vue";
import { api } from "../../../stores/auth";
import { useProjectsStore } from "../../../stores/projects";
import { ATTENTION, ATTENTION_LEVELS } from "../../work/attention";
import { encodeFilter } from "../../work/viewState";
import { kindLabel } from "../../../utils/activityKinds";
import { formatInstant } from "../../../utils/time";
import { describeActivity } from "../describeActivity";
import { useProjectContext } from "../useProjectContext";

const context = useProjectContext();
const { projectId, project, isArchived, can, actionBusy } = context;
const projects = useProjectsStore();
const router = useRouter();

// Indicator plus words, never colour alone. The four values are the same vocabulary as
// workspace favourites, because the question is the same one.
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

async function openSession(binding: ProjectWorkspace): Promise<void> {
  // Not a new flow: the existing New Session dialog, prefilled. V2.0 deliberately stops
  // short of a one-click start, which needs a task to start *on* (V2.1).
  await router.push({
    name: "sessions",
    query: {
      node_id: binding.node_id,
      workspace: binding.path,
      project_id: projectId,
    },
  });
}

// --- the read model's two strips (PX-50, plan/26/08 §5) --------------------------
//
// **Two requests, and both are the single `GROUP BY`** (D110). Overview answers five
// questions and these two answer the first two of them: what needs a person, and where the
// work sits. Everything else on this page is project metadata, which is why the attention
// strip is at the top and the workspace list is not.
//
// Secrets, workspace binding forms and process settings are **not** here — they moved to
// Settings (§5). Functions with different risk levels sharing one screen is precisely how
// `ProjectDetailView.vue` reached 1,515 lines.

const counts = ref<WorkCounts | null>(null);

onMounted(async () => {
  // `try`, not `.catch`: the strips are an annotation on a page whose primary content is
  // the project itself, and a throw here — including a synchronous one — must not take the
  // page down with it.
  try {
    counts.value = await api().getWorkCounts(projectId);
  } catch {
    counts.value = null;
  }
});

/** The eight levels with a count, in the server's order, zeroes dropped.
 *
 *  Dropped rather than shown as 0: a strip of eight cells that are mostly zero is a strip
 *  nobody reads, and the ones that matter are the ones with a number. */
const attentionStrip = computed(() =>
  ATTENTION_LEVELS.filter(
    (level) => (counts.value?.by_attention[level] ?? 0) > 0,
  ).map((level) => ({
    level,
    label: ATTENTION[level].label,
    tone: ATTENTION[level].tone,
    count: counts.value!.by_attention[level],
    // Clicking a cell lands on the board **already filtered**, which is the whole
    // reason the strip is worth having.
    filter: encodeFilter({ field: "attention", op: "eq", value: level }),
  })),
);

const LIFECYCLE_LABELS: Record<string, string> = {
  backlog: "待辦",
  ready: "就緒",
  in_progress: "進行中",
  review: "審查",
  done: "完成",
};

const distribution = computed(() =>
  ["backlog", "ready", "in_progress", "review", "done"].map((key) => ({
    key,
    label: LIFECYCLE_LABELS[key],
    count: counts.value?.by_lifecycle[key] ?? 0,
  })),
);

const distributionTotal = computed(() =>
  distribution.value.reduce((sum, entry) => sum + entry.count, 0),
);

async function unbind(bindingId: string): Promise<void> {
  await context.perform(async () => {
    await projects.unbindWorkspace(projectId, bindingId);
    await context.reload();
  });
}
</script>

<template>
  <section v-if="project" class="tab-panel overview-panel">
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
        <strong class="metric-number">{{ projects.activity.length }}</strong>
        <span class="metric-caption">latest project events</span>
      </UiCard>
    </div>

    <!-- 2. What needs a person. First, because it is the only thing on this page that
         can be urgent, and every cell is a link into the board already filtered. -->
    <UiCard v-if="attentionStrip.length" flush class="overview-card">
      <template #header>
        <div class="card-heading">
          <div>
            <span>需要有人處理</span>
            <small>點一格會帶著篩選進入工作板。</small>
          </div>
        </div>
      </template>
      <ul class="attention-strip" data-attention-strip>
        <li v-for="cell in attentionStrip" :key="cell.level">
          <RouterLink
            :to="{
              name: 'project-work',
              params: { id: projectId },
              query: { f: cell.filter },
            }"
            :data-attention-cell="cell.level"
            :class="`t-${cell.tone}`"
          >
            <strong>{{ cell.count }}</strong>
            <span>{{ cell.label }}</span>
          </RouterLink>
        </li>
      </ul>
    </UiCard>

    <!-- 3. Where the work sits. Counts, not a chart: five numbers read faster than five
         bars, and a bar chart of five categories is decoration. -->
    <UiCard v-if="counts" flush class="overview-card">
      <template #header>
        <div class="card-heading">
          <div>
            <span>工作分佈</span>
            <small>共 {{ distributionTotal }} 張卡片。</small>
          </div>
        </div>
      </template>
      <ul class="distribution" data-distribution>
        <li
          v-for="entry in distribution"
          :key="entry.key"
          :data-lifecycle="entry.key"
        >
          <strong>{{ entry.count }}</strong>
          <span>{{ entry.label }}</span>
        </li>
      </ul>
    </UiCard>

    <UiCard v-if="project.description" class="description-card">
      <span class="eyebrow">Project brief</span>
      <p class="description">{{ project.description }}</p>
    </UiCard>

    <UiCard class="overview-card">
      <ProjectRepositories
        :project-id="projectId"
        :can-manage="can.manage.value"
      />
    </UiCard>

    <UiCard v-if="can.manageSecrets.value" class="overview-card">
      <ProjectSecrets :project-id="projectId" />
    </UiCard>

    <UiCard flush class="overview-card">
      <template #header>
        <div class="card-heading">
          <div>
            <span>Workspace bindings</span>
            <small>Session launch points registered to this project.</small>
          </div>
          <UiButton
            v-if="can.manage.value && !isArchived"
            size="sm"
            :disabled="actionBusy"
            @click="context.openBindDialog()"
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
            v-if="can.manage.value"
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
          <UiButton
            size="sm"
            variant="ghost"
            @click="
              router.push({
                name: 'project-activity',
                params: { id: projectId },
              })
            "
          >
            View all
          </UiButton>
        </div>
      </template>
      <p v-if="projects.activity.length === 0" class="card-empty">
        Nothing has happened yet. Bind a workspace, or start a session from one.
      </p>
      <ul v-else class="timeline">
        <li v-for="event in projects.activity.slice(0, 10)" :key="event.id">
          <span class="when" :title="event.occurred_at">
            {{ formatInstant(event.occurred_at) }}
          </span>
          <span class="what">{{ kindLabel(event.kind) }}</span>
          <span class="detail">{{
            describeActivity(event.kind, event.payload)
          }}</span>
          <span class="who">{{ event.actor_name ?? "—" }}</span>
        </li>
      </ul>
    </UiCard>
  </section>
</template>

<style scoped>
.attention-strip,
.distribution {
  list-style: none;
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3);
  margin: 0;
  padding: var(--space-3);
}
.attention-strip a,
.distribution li {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 96px;
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-sm);
  border: 1px solid var(--border-default);
  background: var(--surface-elevated);
  color: var(--text-primary);
  text-decoration: none;
}
/* Colour is the fourth cue, after the number, the words and the border.
 *
 * A class per tone rather than an inline custom property: `var(--cell-tone)` would be a
 * reference the token checker cannot resolve, and its allowlist is for runtime variables
 * somebody else owns — not for one this file invented. Same shape as `AttentionBadge`. */
.attention-strip a {
  border-left: 3px solid currentColor;
}
.attention-strip a > * {
  color: var(--text-primary);
}
.t-attention-human {
  color: var(--attention-human);
}
.t-attention-approval {
  color: var(--attention-approval);
}
.t-attention-blocked {
  color: var(--attention-blocked);
}
.t-attention-failed {
  color: var(--attention-failed);
}
.t-attention-warning {
  color: var(--attention-warning);
}
.attention-strip a:hover {
  border-color: var(--action-primary);
}
.attention-strip strong,
.distribution strong {
  font-size: var(--font-lg);
  font-variant-numeric: tabular-nums;
}
.attention-strip span,
.distribution span {
  color: var(--text-muted);
  font-size: var(--font-xs);
}

.description {
  margin: 0;
  white-space: pre-wrap;
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
.notice {
  margin: 0 0 16px;
  padding: 10px 12px;
  border-radius: var(--radius-sm);
  background: var(--surface-canvas);
  color: var(--text-secondary);
  font-size: 13px;
}
.muted {
  color: var(--text-muted);
  font-size: 13px;
}
</style>
