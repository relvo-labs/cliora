<script setup lang="ts">
// What this card's agent will actually read, and why.
//
// **Its host is `TaskDetailView`, not a Drawer.** The upstream plan says "the Task
// Drawer gains a Related knowledge section"; the Drawer is `beta.1`'s work and does not
// exist yet, and this section is too important to wait for it — it is the only answer to
// "why did the agent do that?". `PX-62` re-hosts it, and because the only prop is
// `taskId` that move is one line.
//
// The list comes from the **same** search the Context Builder runs, with the same task
// id, so the two cannot drift. A second ranking computed here would disagree one day and
// nobody would be able to tell which was right.
import { computed, onMounted, ref } from "vue";

import type { KnowledgeHit } from "../../../api/dto";
import { api } from "../../../stores/auth";
import { useAsyncResource } from "../../../composables/useAsyncResource";
import AuthorityBadge from "./AuthorityBadge.vue";
import { explainWhy, sourceLabel } from "../queries";

const props = defineProps<{
  projectId: string;
  taskId: string;
  taskTitle: string;
  canManage: boolean;
}>();

const client = api();
const pinned = ref<Set<string>>(new Set());
const busy = ref<string | null>(null);

const related = useAsyncResource(
  () =>
    client.searchKnowledge(props.projectId, {
      q: props.taskTitle,
      taskId: props.taskId,
      limit: 8,
    }),
  { isEmpty: (page) => page.items.length === 0 },
);

const items = computed<KnowledgeHit[]>(() => related.data.value?.items ?? []);

function isPinned(hit: KnowledgeHit): boolean {
  return pinned.value.has(hit.source_id) || hit.why.includes("pinned");
}

async function setPin(
  hit: KnowledgeHit,
  mode: "pin" | "exclude",
): Promise<void> {
  busy.value = hit.source_id;
  const snapshot = new Set(pinned.value);
  // Optimistic, and it **rolls back on failure**. A pin that silently did not take is
  // worse than one that visibly failed: the next turn would read something else and the
  // person would have no reason to look.
  if (mode === "pin") pinned.value = new Set(pinned.value).add(hit.source_id);
  try {
    await client.setKnowledgePin(
      props.projectId,
      props.taskId,
      hit.source_id,
      mode,
    );
    await related.run();
  } catch (error) {
    pinned.value = snapshot;
    throw error;
  } finally {
    busy.value = null;
  }
}

async function clearPin(hit: KnowledgeHit): Promise<void> {
  busy.value = hit.source_id;
  const snapshot = new Set(pinned.value);
  const next = new Set(pinned.value);
  next.delete(hit.source_id);
  pinned.value = next;
  try {
    await client.clearKnowledgePin(
      props.projectId,
      props.taskId,
      hit.source_id,
    );
    await related.run();
  } catch (error) {
    pinned.value = snapshot;
    throw error;
  } finally {
    busy.value = null;
  }
}

onMounted(() => void related.run());
</script>

<template>
  <section class="related">
    <h3 class="related__title">
      這張卡的專案記憶
      <span class="related__count"
        >（Agent 目前會讀到的 {{ items.length }} 個來源）</span
      >
    </h3>

    <p v-if="related.state.value === 'empty'" class="related__empty">
      這個專案還沒有任何與這張卡相關的來源。
    </p>

    <ul v-else class="related__list">
      <li v-for="hit in items" :key="hit.source_id" class="related__item">
        <div class="related__head">
          <span v-if="isPinned(hit)" aria-label="已釘選" title="已釘選"
            >📌</span
          >
          <AuthorityBadge :authority="hit.authority" :version="hit.version" />
          <span class="related__type">{{ sourceLabel(hit.source_type) }}</span>
          <span class="related__source-title">{{ hit.title }}</span>
        </div>
        <p class="related__why">為什麼：{{ explainWhy(hit.why) }}</p>
        <div v-if="canManage" class="related__actions">
          <button
            v-if="!isPinned(hit)"
            type="button"
            :disabled="busy === hit.source_id"
            @click="setPin(hit, 'pin')"
          >
            釘選
          </button>
          <button
            v-else
            type="button"
            :disabled="busy === hit.source_id"
            @click="clearPin(hit)"
          >
            移除釘選
          </button>
          <button
            type="button"
            :disabled="busy === hit.source_id"
            @click="setPin(hit, 'exclude')"
          >
            從這張卡排除
          </button>
        </div>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.related__title {
  font-size: var(--font-md);
}
.related__count {
  color: var(--text-muted);
  font-size: var(--font-xs);
  font-weight: 400;
}
.related__list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}
.related__head {
  display: flex;
  align-items: baseline;
  gap: var(--space-2);
  flex-wrap: wrap;
}
.related__type {
  color: var(--text-muted);
  font-size: var(--font-xs);
}
.related__why {
  color: var(--text-muted);
  font-size: var(--font-xs);
  margin-block: var(--space-1);
}
.related__actions {
  display: flex;
  gap: var(--space-2);
}
</style>
