<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { RouterLink, useRouter } from "vue-router";

import { ApiError } from "../api/client";
import {
  ACTION_SESSION_CREATE,
  ACTION_TASK_APPROVE,
  type ActivityEvent,
  type ProcessDefinition,
  type SessionSummary,
  type Task,
} from "../api/dto";
import AsyncState from "../components/common/AsyncState.vue";
import AppLayout from "../components/layout/AppLayout.vue";
import TaskAgentPanel from "../components/project/TaskAgentPanel.vue";
import TaskDetail from "../components/project/TaskDetail.vue";
import { useAsyncResource } from "../composables/useAsyncResource";
import { api, useAuthStore } from "../stores/auth";

const props = defineProps<{ id: string; taskId: string }>();
const router = useRouter();
const auth = useAuthStore();
const task = ref<Task | null>(null);
const process = ref<ProcessDefinition | null>(null);
const sessions = ref<SessionSummary[]>([]);
const activity = ref<ActivityEvent[]>([]);

const resource = useAsyncResource(async () => {
  const [nextTask, nextProcess, nextSessions, nextActivity] = await Promise.all(
    [
      api().getTask(props.taskId),
      api().getProcess(props.id),
      api().listSessions({ project_id: props.id, task_id: props.taskId }),
      api().listProjectActivity(props.id, {
        limit: 100,
        task_id: props.taskId,
      }),
    ],
  );
  task.value = nextTask;
  process.value = nextProcess;
  sessions.value = nextSessions;
  activity.value = nextActivity.items;
});

const actorNames = computed(() =>
  Object.fromEntries(
    activity.value
      .filter((item) => item.actor_id && item.actor_name)
      .map((item) => [item.actor_id as string, item.actor_name as string]),
  ),
);
const requestId = computed(() =>
  resource.error.value instanceof ApiError
    ? resource.error.value.requestId
    : undefined,
);

function startSession(current: Task): void {
  void router.push({
    name: "sessions",
    query: { project_id: props.id, task_id: current.id },
  });
}

onMounted(() => resource.run());
</script>

<template>
  <AppLayout>
    <main class="task-page">
      <nav class="breadcrumbs" aria-label="Breadcrumb">
        <RouterLink
          :to="{
            name: 'project-detail',
            params: { id },
            query: { tab: 'board' },
          }"
        >
          Project
        </RouterLink>
        <span aria-hidden="true">/</span>
        <span>{{ task?.card_ref ?? "Task" }}</span>
      </nav>

      <AsyncState v-if="resource.state.value === 'loading'" state="loading">
        載入任務…
      </AsyncState>
      <AsyncState v-else-if="resource.state.value === 'error'" state="error">
        無法載入任務。<span v-if="requestId">Request ID: {{ requestId }}</span>
        <button class="ghost" @click="resource.run">重試</button>
      </AsyncState>
      <TaskDetail
        v-else-if="task && process"
        :task="task"
        :process="process"
        :client="api()"
        :can-approve="auth.hasPermission(ACTION_TASK_APPROVE)"
        :can-start-session="auth.hasPermission(ACTION_SESSION_CREATE)"
        :sessions="sessions"
        :activity="activity"
        :actor-names="actorNames"
        @changed="resource.run"
        @start-session="startSession"
      />
      <!-- Its own panel rather than a section inside TaskDetail: it is the only part
           of this page that talks to a different half of the system, and it disappears
           entirely when the deployment has agent runs switched off. -->
      <TaskAgentPanel
        v-if="task"
        :project-id="id"
        :task-id="task.id"
        :stage="task.stage"
      />
    </main>
  </AppLayout>
</template>

<style scoped>
.task-page {
  display: grid;
  gap: var(--space-4);
}
.breadcrumbs {
  display: flex;
  gap: var(--space-2);
  color: var(--text-muted);
  font-size: var(--font-sm);
}
</style>
