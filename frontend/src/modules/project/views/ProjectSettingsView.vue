<script setup lang="ts">
/** The effective process, read-only (PX-64). Formerly `?tab=settings`.
 *
 * Read-only and it says so on the page: a project inherits the platform's seeded process
 * and may only *disable* items in it, never add one or rename a lane (ADR 0033 §5). A
 * form here would imply otherwise.
 */
import { onMounted, ref } from "vue";
import { RouterLink } from "vue-router";

import type { ProcessDefinition } from "../../../api/dto";
import UiCard from "../../../components/ui/UiCard.vue";
import { api } from "../../../stores/auth";
import { useProjectContext } from "../useProjectContext";

const { projectId } = useProjectContext();
const processDefinition = ref<ProcessDefinition | null>(null);

onMounted(async () => {
  processDefinition.value = await api().getProcess(projectId);
});
</script>

<template>
  <section class="tab-panel">
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
</template>

<style scoped>
.tab-panel {
  display: grid;
  gap: var(--space-4);
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
.muted {
  color: var(--text-muted);
  font-size: 13px;
}
</style>
