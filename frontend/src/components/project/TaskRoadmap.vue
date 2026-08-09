<script setup lang="ts">
/**
 * Epic → User Story → Task, with **two** unclassified buckets (TK-09, D4).
 *
 * Two, not one, and that is the whole reason this component is not a plain tree: a
 * card filed under an epic but under no story belongs to *that epic's* bucket, and a
 * card with neither belongs to the top level. Monstrare defines both, and the rule
 * behind them is that a card must never disappear because of how it was filed.
 */
import type { Roadmap } from "../../api/dto";

defineProps<{ roadmap: Roadmap }>();

function percent(done: number, total: number): string {
  if (total === 0) return "—";
  return `${Math.round((done / total) * 100)}%`;
}
</script>

<template>
  <div class="roadmap">
    <p class="summary" data-roadmap-summary>
      完成度 {{ percent(roadmap.done_count, roadmap.total_count) }} （{{
        roadmap.done_count
      }}
      / {{ roadmap.total_count }}）
    </p>

    <details v-for="epic in roadmap.epics" :key="epic.id" open>
      <summary>
        <span class="ref">{{ epic.card_ref }}</span> {{ epic.title }}
        <span class="progress"
          >{{ epic.done_count }} / {{ epic.total_count }}</span
        >
      </summary>

      <details v-for="story in epic.stories" :key="story.id" open>
        <summary>
          <span class="ref">{{ story.card_ref }}</span> {{ story.title }}
          <span class="progress"
            >{{ story.done_count }} / {{ story.total_count }}</span
          >
        </summary>
        <ul>
          <li
            v-for="task in story.tasks"
            :key="task.id"
            :data-stage="task.stage"
          >
            <span class="ref">{{ task.card_ref }}</span> {{ task.title }}
          </li>
        </ul>
      </details>

      <!-- Bucket one: filed under this epic, under no story. -->
      <section v-if="epic.unclassified.length" data-bucket="epic">
        <h4>（未分類任務）</h4>
        <ul>
          <li
            v-for="task in epic.unclassified"
            :key="task.id"
            :data-stage="task.stage"
          >
            <span class="ref">{{ task.card_ref }}</span> {{ task.title }}
          </li>
        </ul>
      </section>
    </details>

    <details v-if="roadmap.orphan_stories.length" open>
      <summary>（未歸類的 User Story）</summary>
      <details v-for="story in roadmap.orphan_stories" :key="story.id" open>
        <summary>
          <span class="ref">{{ story.card_ref }}</span> {{ story.title }}
        </summary>
        <ul>
          <li v-for="task in story.tasks" :key="task.id">
            <span class="ref">{{ task.card_ref }}</span> {{ task.title }}
          </li>
        </ul>
      </details>
    </details>

    <!-- Bucket two: neither an epic nor a story. -->
    <section v-if="roadmap.unclassified.length" data-bucket="top">
      <h4>（未歸類）</h4>
      <ul>
        <li
          v-for="task in roadmap.unclassified"
          :key="task.id"
          :data-stage="task.stage"
        >
          <span class="ref">{{ task.card_ref }}</span> {{ task.title }}
        </li>
      </ul>
    </section>

    <p v-if="roadmap.total_count === 0" class="empty">
      還沒有任務。先建一個 Epic，或直接建一張卡。
    </p>
  </div>
</template>

<style scoped>
.summary {
  color: var(--color-text-muted);
  font-size: var(--font-size-sm);
}
details {
  margin-left: var(--space-3);
}
summary {
  cursor: pointer;
  padding: 2px 0;
}
.ref {
  font-family: var(--font-mono);
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
  margin-right: var(--space-1);
}
.progress {
  color: var(--color-text-muted);
  font-size: var(--font-size-xs);
  margin-left: var(--space-2);
}
ul {
  list-style: none;
  margin: 0 0 var(--space-2);
  padding-left: var(--space-4);
}
li[data-stage="done"] .ref {
  text-decoration: line-through;
}
h4 {
  font-size: var(--font-size-sm);
  margin: var(--space-2) 0 var(--space-1) var(--space-3);
}
.empty {
  color: var(--color-text-muted);
}
</style>
