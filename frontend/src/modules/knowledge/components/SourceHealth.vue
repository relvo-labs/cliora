<script setup lang="ts">
// Whether this project's memory is actually keeping up.
//
// The row that matters most is the one about the repository: content is pushed from
// inside a run (D77), so a project whose agents never ran has none — and **a knowledge
// base that cannot show you it is empty is worse than not having one.** That sentence is
// this component's reason to exist, not a caption.
import { computed } from "vue";

import type { KnowledgeHealth } from "../../../api/dto";
import { sourceLabel } from "../queries";

const props = defineProps<{ health: KnowledgeHealth | null }>();

const deadAgeHours = computed(() =>
  props.health ? props.health.dead_letter_age_seconds / 3600 : 0,
);
// An hour is not a latency budget. It is the point at which "nobody is reading this
// panel" becomes the likelier explanation than "somebody is looking into it".
const deadSevere = computed(() => deadAgeHours.value > 1);
</script>

<template>
  <section v-if="health" class="health">
    <h3>來源健康狀態</h3>

    <table class="health__families">
      <thead>
        <tr>
          <th scope="col">來源</th>
          <th scope="col">筆數</th>
          <th scope="col">片段</th>
          <th scope="col">最後收集</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="family in health.families" :key="family.source_type">
          <td>{{ sourceLabel(family.source_type) }}</td>
          <td>{{ family.sources }}</td>
          <td>{{ family.chunks }}</td>
          <td>{{ family.last_ingested_at ?? "—" }}</td>
        </tr>
      </tbody>
    </table>

    <p
      v-if="health.repo_never_synced"
      class="health__repo"
      data-testid="repo-never-synced"
    >
      <strong>程式庫文件：從未同步。</strong>
      程式庫內容由 Agent 在 run 裡用 <code>cliora knowledge sync</code> 推送。
      這個專案還沒有跑過 run，或 run 裡沒有執行它。
    </p>
    <p v-else class="health__repo">
      程式庫最後同步：<code>{{ health.repo_commit }}</code> （{{
        health.repo_last_synced_at
      }}）
    </p>

    <ul class="health__jobs">
      <li>待處理：{{ health.pending_jobs }}</li>
      <li :class="{ health__warn: health.failed_jobs > 0 }">
        重試中：{{ health.failed_jobs }}
      </li>
      <li :class="{ health__danger: deadSevere }" data-testid="dead-letter">
        已放棄：{{ health.dead_jobs }}
        <template v-if="health.dead_jobs">
          （最舊 {{ deadAgeHours.toFixed(1) }} 小時）
        </template>
      </li>
    </ul>

    <p v-if="health.last_error" class="health__error">
      最近一次失敗：<code>{{ health.last_error }}</code>
    </p>
  </section>
</template>

<style scoped>
.health__families {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--font-sm);
}
.health__families th,
.health__families td {
  text-align: start;
  padding: var(--space-1) var(--space-2);
  border-block-end: 1px solid var(--border-default);
}
.health__repo {
  margin-block: var(--space-3);
  font-size: var(--font-sm);
  color: var(--text-secondary);
}
.health__jobs {
  display: flex;
  gap: var(--space-4);
  list-style: none;
  padding: 0;
  font-size: var(--font-sm);
}
.health__warn {
  color: var(--status-busy);
}
.health__danger {
  color: var(--status-error);
  font-weight: 600;
}
.health__error code {
  font-family: var(--font-mono);
  font-size: var(--font-xs);
  color: var(--text-muted);
}
</style>
