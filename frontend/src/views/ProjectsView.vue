<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";

import { ApiError } from "../api/client";
import { ACTION_PROJECT_MANAGE } from "../api/dto";
import type { ProjectStatus } from "../api/dto";
import AppLayout from "../components/layout/AppLayout.vue";
import AsyncState from "../components/common/AsyncState.vue";
import BaseBadge from "../components/ui/BaseBadge.vue";
import DataTable from "../components/ui/DataTable.vue";
import EmptyState from "../components/ui/EmptyState.vue";
import PageHead from "../components/ui/PageHead.vue";
import UiButton from "../components/ui/UiButton.vue";
import UiCard from "../components/ui/UiCard.vue";
import { useAsyncResource } from "../composables/useAsyncResource";
import { useAuthStore } from "../stores/auth";
import { useProjectsStore } from "../stores/projects";
import { formatInstant } from "../utils/time";

const auth = useAuthStore();
const projects = useProjectsStore();
const router = useRouter();

// Admin-only (ADR 0027 sec 4), so most people land on a page they cannot add to.
// That makes the empty state's wording load-bearing rather than decorative.
const canManage = computed(() => auth.hasPermission(ACTION_PROJECT_MANAGE));

const statusFilter = ref<ProjectStatus | "">("");
const ownedByMe = ref(false);
const creating = ref(false);
const newName = ref("");
const newSlug = ref("");
const newDescription = ref("");
const createError = ref<string | null>(null);
const createRequestId = ref<string>();

const resource = useAsyncResource(
  () =>
    projects.fetchList({
      status: statusFilter.value || undefined,
      owned_by_me: ownedByMe.value || undefined,
    }),
  { isEmpty: (list) => list.length === 0 },
);

const displayState = computed(() =>
  resource.state.value === "success" && projects.list.length === 0
    ? "empty"
    : resource.state.value === "error" &&
        resource.error.value instanceof ApiError &&
        resource.error.value.status === 404
      ? "empty"
      : resource.state.value,
);
const featureUnavailable = computed(
  () =>
    resource.error.value instanceof ApiError &&
    resource.error.value.status === 404,
);
const requestId = computed(() =>
  resource.error.value instanceof ApiError
    ? resource.error.value.requestId
    : undefined,
);

const totals = computed(() =>
  projects.list.reduce(
    (result, project) => ({
      workspaces: result.workspaces + project.workspace_count,
      nodes: result.nodes + project.node_count,
      sessions: result.sessions + project.active_session_count,
    }),
    { workspaces: 0, nodes: 0, sessions: 0 },
  ),
);

function statusTone(status: ProjectStatus): string {
  if (status === "active") return "status-online";
  if (status === "paused") return "status-busy";
  return "status-offline";
}

onMounted(() => resource.run());

function open(id: string): void {
  void router.push({ name: "project-detail", params: { id } });
}

async function create(): Promise<void> {
  createError.value = null;
  createRequestId.value = undefined;
  try {
    const project = await projects.create({
      name: newName.value.trim(),
      ...(newSlug.value.trim() ? { slug: newSlug.value.trim() } : {}),
      ...(newDescription.value.trim()
        ? { description: newDescription.value.trim() }
        : {}),
    });
    creating.value = false;
    newName.value = "";
    newSlug.value = "";
    newDescription.value = "";
    open(project.id);
  } catch (error) {
    createError.value =
      error instanceof Error ? error.message : "Could not create the project.";
    createRequestId.value =
      error instanceof ApiError ? error.requestId : undefined;
  }
}
</script>

<template>
  <AppLayout>
    <PageHead>
      <template #title>Projects</template>
      <template #subtitle>
        {{ projects.list.length }} projects · {{ totals.workspaces }} workspace
        bindings across {{ totals.nodes }} nodes
      </template>
      <template #actions>
        <UiButton
          variant="ghost"
          :disabled="resource.state.value === 'loading'"
          @click="resource.run()"
        >
          Refresh
        </UiButton>
        <UiButton v-if="canManage" variant="primary" @click="creating = true">
          New project
        </UiButton>
      </template>
    </PageHead>

    <div class="project-toolbar" aria-label="Project filters">
      <div class="toolbar-copy">
        <strong>Project directory</strong>
        <span>Cross-node work, ownership and execution at a glance.</span>
      </div>
      <label class="field-label">
        <span>Status</span>
        <select v-model="statusFilter" @change="resource.run()">
          <option value="">All statuses</option>
          <option value="active">Active</option>
          <option value="paused">Paused</option>
          <option value="archived">Archived</option>
        </select>
      </label>
      <label class="check">
        <input v-model="ownedByMe" type="checkbox" @change="resource.run()" />
        Only mine
      </label>
    </div>

    <div
      v-if="displayState === 'loading'"
      class="skeleton"
      aria-label="Loading projects"
    >
      <span /><span /><span /><span />
    </div>
    <AsyncState v-else-if="displayState === 'forbidden'" state="forbidden">
      You do not have permission to view projects.
    </AsyncState>
    <AsyncState v-else-if="displayState === 'error'" state="error">
      Could not load projects.
      <small v-if="requestId">Request ID: {{ requestId }}</small>
      <UiButton variant="ghost" size="sm" @click="resource.run()">
        Retry
      </UiButton>
    </AsyncState>
    <!--
      Two wordings, because the useful next step differs by role. Both end with the
      same sentence: a project is optional, and ad-hoc sessions were not replaced.
    -->
    <AsyncState
      v-else-if="displayState === 'empty' && featureUnavailable"
      state="empty"
    >
      Projects are not enabled in this deployment.
    </AsyncState>
    <EmptyState v-else-if="displayState === 'empty'">
      還沒有專案。你仍然可以直接從 Sessions 建立 Ad-hoc Session。
      <template #action>
        <UiButton v-if="canManage" variant="primary" @click="creating = true">
          建立專案
        </UiButton>
        <UiButton @click="router.push({ name: 'sessions' })">
          前往 Sessions
        </UiButton>
      </template>
    </EmptyState>

    <UiCard v-if="displayState === 'success'" flush class="project-table-card">
      <DataTable>
        <thead>
          <tr>
            <th>Project</th>
            <th>Status</th>
            <th>Workspace footprint</th>
            <th>Active sessions</th>
            <th>Last activity</th>
            <th aria-label="Open project"></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="p in projects.list" :key="p.id" class="project-row">
            <td>
              <button class="name" @click="open(p.id)">{{ p.name }}</button>
              <span class="slug">{{ p.slug }}</span>
            </td>
            <td>
              <BaseBadge variant="outline" :tone="statusTone(p.status)">
                {{ p.status }}
              </BaseBadge>
            </td>
            <td>
              <strong class="metric-value">{{ p.workspace_count }}</strong>
              directories
              <span class="metric-separator">·</span>
              {{ p.node_count }} nodes
            </td>
            <td>
              <span :class="{ quiet: !p.active_session_count }">
                {{ p.active_session_count || "—" }}
              </span>
            </td>
            <td class="activity" :title="p.last_activity_at ?? ''">
              {{ formatInstant(p.last_activity_at) }}
            </td>
            <td class="open-cell">
              <button
                class="open-project"
                :aria-label="`Open ${p.name}`"
                @click="open(p.id)"
              >
                →
              </button>
            </td>
          </tr>
        </tbody>
      </DataTable>
    </UiCard>

    <div v-if="creating" class="dialog-backdrop" @click.self="creating = false">
      <div class="dialog" role="dialog" aria-label="New project">
        <h2>New project</h2>
        <label>
          Name
          <input v-model="newName" type="text" maxlength="128" />
        </label>
        <label>
          Identifier <span class="optional">optional</span>
          <input
            v-model="newSlug"
            type="text"
            maxlength="64"
            placeholder="derived-from-name"
          />
        </label>
        <label>
          Description <span class="optional">optional</span>
          <textarea v-model="newDescription" rows="4" />
        </label>
        <p class="hint">
          The identifier is derived from the name and cannot be changed
          afterwards.
        </p>
        <p v-if="createError" class="error">{{ createError }}</p>
        <p v-if="createRequestId" class="hint">
          Request ID: {{ createRequestId }}
        </p>
        <div class="dialog-actions">
          <UiButton variant="ghost" @click="creating = false">Cancel</UiButton>
          <UiButton
            variant="primary"
            :disabled="!newName.trim()"
            @click="create"
          >
            Create
          </UiButton>
        </div>
      </div>
    </div>
  </AppLayout>
</template>

<style scoped>
.project-toolbar {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  min-height: 58px;
  margin-bottom: var(--space-3);
  padding: var(--space-2) var(--space-3) var(--space-2) var(--space-4);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  background: var(--surface-default);
}
.toolbar-copy {
  display: grid;
  gap: 2px;
  min-width: 0;
  margin-right: auto;
}
.toolbar-copy strong {
  font-size: var(--font-sm);
}
.toolbar-copy span {
  color: var(--text-muted);
  font-size: var(--font-xs);
}
.field-label {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--text-muted);
  font-size: var(--font-xs);
  font-weight: 600;
}
.field-label select {
  min-height: 34px;
  padding: 0 30px 0 var(--space-3);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  color: var(--text-secondary);
  background: var(--surface-elevated);
}
.check {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--text-secondary);
  font-size: var(--font-sm);
}
.project-table-card {
  min-height: 190px;
}
.name {
  background: none;
  border: none;
  padding: 0;
  color: var(--text-primary);
  font-weight: 600;
  font-size: var(--font-md);
  cursor: pointer;
}
.name:hover {
  color: var(--action-primary);
}
.slug {
  display: block;
  margin-top: 2px;
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: var(--font-xs);
}
.metric-value {
  color: var(--text-primary);
}
.metric-separator {
  margin-inline: var(--space-1);
  color: var(--text-muted);
}
.quiet,
.activity {
  color: var(--text-muted);
}
.open-cell {
  width: 44px;
  text-align: right;
}
.open-project {
  width: 28px;
  height: 28px;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  color: var(--text-muted);
  background: transparent;
}
.open-project:hover {
  border-color: var(--border-default);
  color: var(--action-primary);
  background: var(--surface-elevated);
}
.dialog-backdrop {
  position: fixed;
  inset: 0;
  display: grid;
  place-items: center;
  background: rgb(0 0 0 / 40%);
  z-index: 20;
}
.dialog {
  width: min(420px, 92vw);
  padding: var(--space-5);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  background: var(--surface-elevated);
  display: grid;
  gap: var(--space-3);
  box-shadow: 0 18px 48px
    color-mix(in srgb, var(--text-primary) 18%, transparent);
}
.dialog h2 {
  margin: 0;
  font-size: 17px;
}
.dialog label {
  display: grid;
  gap: 6px;
  font-size: 13px;
}
.dialog input {
  min-height: 38px;
  padding: 8px 10px;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  background: var(--surface-default);
  color: var(--text-primary);
}
.dialog textarea {
  padding: 8px 10px;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  resize: vertical;
  background: var(--surface-default);
  color: var(--text-primary);
}
.optional {
  color: var(--text-muted);
  font-weight: 400;
}
.hint {
  margin: 0;
  color: var(--text-muted);
  font-size: 12px;
}
.error {
  margin: 0;
  color: var(--status-error);
  font-size: 12px;
}
.dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
.skeleton {
  display: grid;
  gap: 10px;
}
.skeleton span {
  height: 38px;
  border-radius: var(--radius-sm);
  background: var(--surface-elevated);
}
.skeleton span:first-child {
  width: 72%;
}
@media (max-width: 760px) {
  .project-toolbar {
    align-items: stretch;
    flex-direction: column;
  }
  .toolbar-copy {
    margin-right: 0;
  }
  .field-label {
    justify-content: space-between;
  }
}
</style>
