<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";

import { ApiError } from "../api/client";
import { ACTION_PROJECT_MANAGE } from "../api/dto";
import type { ProjectStatus } from "../api/dto";
import AppLayout from "../components/layout/AppLayout.vue";
import AsyncState from "../components/common/AsyncState.vue";
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
    <header class="head">
      <div>
        <h1>Projects</h1>
        <p>Work that spans workspaces on more than one node.</p>
      </div>
      <div class="head-actions">
        <button
          class="ghost"
          :disabled="resource.state.value === 'loading'"
          @click="resource.run()"
        >
          Refresh
        </button>
        <button v-if="canManage" class="primary" @click="creating = true">
          New project
        </button>
      </div>
    </header>

    <div class="filters">
      <select v-model="statusFilter" @change="resource.run()">
        <option value="">All statuses</option>
        <option value="active">Active</option>
        <option value="paused">Paused</option>
        <option value="archived">Archived</option>
      </select>
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
      <button class="link" @click="resource.run()">Retry</button>
    </AsyncState>
    <!--
      Two wordings, because the useful next step differs by role. Both end with the
      same sentence: a project is optional, and ad-hoc sessions were not replaced.
    -->
    <AsyncState v-else-if="displayState === 'empty'" state="empty">
      <template v-if="featureUnavailable">
        Projects are not enabled in this deployment.
      </template>
      <template v-else-if="canManage">
        No projects yet. Create one with “New project”. You can still start an
        ad-hoc session directly from Sessions.
      </template>
      <template v-else>
        No projects yet. Ask an Admin to create one, or start an ad-hoc session
        directly from Sessions.
      </template>
    </AsyncState>

    <div v-if="displayState === 'success'" class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Name</th>
            <th>Status</th>
            <th>Workspaces</th>
            <th>Sessions</th>
            <th>Last activity</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="p in projects.list" :key="p.id">
            <td>
              <button class="name" @click="open(p.id)">{{ p.name }}</button>
              <!-- The slug is what a URL and, from V2.1, a card reference are
                   built from, so it is shown rather than hidden behind the name. -->
              <span class="slug">{{ p.slug }}</span>
            </td>
            <td>
              <span class="pill" :data-status="p.status">{{ p.status }}</span>
            </td>
            <td>
              {{ p.workspace_count }} directories · {{ p.node_count }} nodes
            </td>
            <!-- An em dash rather than a 0: "nothing running" is easier to scan
                 as an absence than as a number to be read and compared. -->
            <td>{{ p.active_session_count || "—" }}</td>
            <td :title="p.last_activity_at ?? ''">
              {{ formatInstant(p.last_activity_at) }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>

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
          <button class="ghost" @click="creating = false">Cancel</button>
          <button class="primary" :disabled="!newName.trim()" @click="create">
            Create
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
  margin-bottom: 20px;
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
  gap: 8px;
}
.filters {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}
.check {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--text-secondary);
  font-size: 13px;
}
.table-wrap {
  overflow-x: auto;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  background: var(--surface-default);
}
table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
th,
td {
  padding: 10px 14px;
  text-align: left;
  border-bottom: 1px solid var(--border-subtle, var(--border-default));
}
th {
  color: var(--text-muted);
  font-weight: 600;
  font-size: 12px;
}
tbody tr:last-child td {
  border-bottom: none;
}
.name {
  background: none;
  border: none;
  padding: 0;
  color: var(--action-primary);
  font-weight: 600;
  font-size: 13px;
  cursor: pointer;
}
.slug {
  display: block;
  color: var(--text-muted);
  font-size: 11px;
}
/* Three states, and deliberately no green: the same screen later carries "session
 * running" and, from V2.2, "run executing". Spending green here would make three
 * different kinds of "in progress" indistinguishable (plan/16 §8). */
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
  color: var(--status-warning, var(--text-secondary));
  background: transparent;
}
.pill[data-status="archived"] {
  color: var(--text-muted);
}
.dialog-backdrop {
  position: fixed;
  inset: 0;
  display: grid;
  place-items: center;
  background: rgb(0 0 0 / 40%);
}
.dialog {
  width: min(420px, 92vw);
  padding: 20px;
  border-radius: var(--radius-md);
  background: var(--surface-elevated);
  display: grid;
  gap: 12px;
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
  color: var(--status-danger, crimson);
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
</style>
