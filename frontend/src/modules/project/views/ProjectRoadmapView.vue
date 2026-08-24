<script setup lang="ts">
/** Epic → User Story → Task, on a URL of its own (PX-64). Formerly `?tab=roadmap`. */
import { onMounted, ref } from "vue";

import type { Roadmap } from "../../../api/dto";
import TaskRoadmap from "../../../components/project/TaskRoadmap.vue";
import UiButton from "../../../components/ui/UiButton.vue";
import { api } from "../../../stores/auth";
import { useProjectContext } from "../useProjectContext";

const context = useProjectContext();
const { projectId, isArchived, can } = context;

const roadmap = ref<Roadmap | null>(null);
const epicTitle = ref("");
const storyTitle = ref("");

async function reload(): Promise<void> {
  roadmap.value = await api().getRoadmap(projectId);
}

async function createEpic(): Promise<void> {
  await api().createEpic(projectId, { title: epicTitle.value });
  epicTitle.value = "";
  await reload();
}

async function createStory(): Promise<void> {
  await api().createUserStory(projectId, { title: storyTitle.value });
  storyTitle.value = "";
  await reload();
}

onMounted(reload);
</script>

<template>
  <section class="tab-panel">
    <div class="workbar roadmap-bar">
      <div class="workbar-copy">
        <strong>Delivery roadmap</strong>
        <span>Epic → User Story → Task, with completion rolled upward.</span>
      </div>
      <div v-if="can.createTasks.value && !isArchived" class="quick-create">
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
</template>

<style scoped>
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
.notice {
  margin: 0 0 16px;
  padding: 10px 12px;
  border-radius: var(--radius-sm);
  background: var(--surface-canvas);
  color: var(--text-secondary);
  font-size: 13px;
}
</style>
