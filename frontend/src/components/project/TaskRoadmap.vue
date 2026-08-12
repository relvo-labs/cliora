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
import StageBadge from "../ui/StageBadge.vue";

defineProps<{ roadmap: Roadmap }>();

function percent(done: number, total: number): string {
  if (total === 0) return "—";
  return `${Math.round((done / total) * 100)}%`;
}
</script>

<template>
  <div class="roadmap">
    <div class="overall">
      <div>
        <span class="overall-label">Overall completion</span>
        <p class="summary" data-roadmap-summary>
          {{ percent(roadmap.done_count, roadmap.total_count) }}
          <span
            >{{ roadmap.done_count }} / {{ roadmap.total_count }} tasks</span
          >
        </p>
      </div>
      <progress
        :value="roadmap.done_count"
        :max="Math.max(roadmap.total_count, 1)"
        aria-label="整體完成度"
      ></progress>
    </div>

    <details v-for="epic in roadmap.epics" :key="epic.id" open>
      <summary>
        <span class="ref">{{ epic.card_ref }}</span> {{ epic.title }}
        <span class="progress"
          >{{ epic.done_count }} / {{ epic.total_count }}</span
        >
        <progress
          :value="epic.done_count"
          :max="Math.max(epic.total_count, 1)"
          :aria-label="`${epic.title} 完成度`"
        ></progress>
      </summary>

      <details v-for="story in epic.stories" :key="story.id" open>
        <summary>
          <span class="ref">{{ story.card_ref }}</span> {{ story.title }}
          <span class="progress"
            >{{ story.done_count }} / {{ story.total_count }}</span
          >
          <progress
            :value="story.done_count"
            :max="Math.max(story.total_count, 1)"
            :aria-label="`${story.title} 完成度`"
          ></progress>
        </summary>
        <ul>
          <li
            v-for="task in story.tasks"
            :key="task.id"
            :data-stage="task.stage"
          >
            <span class="ref">{{ task.card_ref }}</span> {{ task.title }}
            <StageBadge :stage="task.stage" />
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
            <StageBadge :stage="task.stage" />
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
            <StageBadge :stage="task.stage" />
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
          <StageBadge :stage="task.stage" />
        </li>
      </ul>
    </section>

    <p v-if="roadmap.total_count === 0" class="empty">
      還沒有任務。先建一個 Epic，或直接建一張卡。
    </p>
  </div>
</template>

<style scoped>
.roadmap {
  display: grid;
  gap: var(--space-3);
}
.overall {
  display: grid;
  grid-template-columns: minmax(180px, 0.34fr) minmax(240px, 1fr);
  align-items: center;
  gap: var(--space-5);
  padding: var(--space-4);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  background: var(--surface-elevated);
}
.overall-label {
  color: var(--text-muted);
  font-size: var(--font-xs);
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}
.summary {
  display: flex;
  align-items: baseline;
  gap: var(--space-2);
  margin: var(--space-1) 0 0;
  color: var(--text-primary);
  font-size: var(--font-lg);
  font-weight: 600;
}
.summary span {
  color: var(--text-muted);
  font-size: var(--font-xs);
  font-weight: 400;
}
progress {
  width: 100%;
  height: 5px;
  overflow: hidden;
  border: 0;
  border-radius: 999px;
  color: var(--stage-done);
  background: var(--surface-canvas);
}
progress::-webkit-progress-bar {
  background: var(--surface-canvas);
}
progress::-webkit-progress-value {
  background: var(--stage-done);
}
progress::-moz-progress-bar {
  background: var(--stage-done);
}
details {
  overflow: hidden;
  margin: 0;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  background: var(--surface-elevated);
}
[data-bucket="top"] {
  overflow: hidden;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  background: var(--surface-elevated);
}
[data-bucket="top"] h4 {
  border-top: 0;
}
details details {
  margin: 0 var(--space-3) var(--space-3);
  border-radius: var(--radius-sm);
  background: var(--surface-default);
}
summary {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  cursor: pointer;
  min-height: 50px;
  padding: var(--space-3) var(--space-4);
  color: var(--text-primary);
  font-weight: 600;
}
details > summary:hover {
  background: var(--surface-default);
}
details details > summary {
  min-height: 42px;
  padding: var(--space-2) var(--space-3);
  font-size: var(--font-sm);
  font-weight: 600;
}
summary progress {
  width: 96px;
  margin-left: auto;
}
li {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-height: 40px;
  padding: var(--space-2) var(--space-3);
  border-top: 1px solid var(--border-default);
  color: var(--text-secondary);
  background: var(--surface-elevated);
  font-size: var(--font-sm);
}
li :deep(.badge) {
  margin-left: auto;
}
.ref {
  font-family: var(--font-mono);
  font-size: var(--font-xs);
  color: var(--text-muted);
  margin-right: var(--space-1);
}
.progress {
  color: var(--text-muted);
  font-size: var(--font-xs);
  margin-left: var(--space-2);
}
ul {
  list-style: none;
  margin: 0;
  padding: 0;
}
li[data-stage="done"] .ref {
  text-decoration: line-through;
}
h4 {
  margin: 0;
  padding: var(--space-2) var(--space-4);
  border-top: 1px solid var(--border-default);
  color: var(--text-muted);
  background: var(--surface-default);
  font-size: var(--font-xs);
  text-transform: uppercase;
}
.empty {
  margin: 0;
  padding: var(--space-5);
  border: 1px dashed var(--border-default);
  border-radius: var(--radius-lg);
  color: var(--text-muted);
  background: var(--surface-default);
}
@media (max-width: 700px) {
  .overall {
    grid-template-columns: 1fr;
    gap: var(--space-3);
  }
  summary progress {
    display: none;
  }
}
</style>
