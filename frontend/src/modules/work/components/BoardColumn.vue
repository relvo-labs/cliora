<script setup lang="ts">
/**
 * One column (PX-29/PX-36, plan/26/06 §3.1).
 *
 * **The header count is the server's.** Not `items.length` — the column loads fifty and
 * the header says 348. The upstream plan calls the alternative "the commonest lie on a
 * board like this", and there is a pinned test on the server as well as this component's.
 *
 * Drop targets refuse visibly where the move is not allowed, **and the server is still the
 * decision**: a client-side rule that got out of step would refuse a legal move with no
 * way for the person to find out why.
 */
import { computed } from "vue";

import type { WorkItemCard as Card } from "../../../api/dto";
import UiButton from "../../../components/ui/UiButton.vue";
import WorkItemCard from "./WorkItemCard.vue";

const props = withDefaults(
  defineProps<{
    label: string;
    groupKey: string;
    count: number;
    items: Card[];
    hasMore: boolean;
    density?: "comfortable" | "compact";
    canWrite?: boolean;
    /** The advisory WIP limit for this lane, if the process declares one. */
    wipSuggested?: number | null;
    /** Set on the Done column: "近 7 天 / 共 348" rather than a bare number. */
    windowNote?: string | null;
    pending?: Record<string, string>;
    dropAllowed?: boolean;
  }>(),
  {
    density: "comfortable",
    canWrite: false,
    wipSuggested: null,
    windowNote: null,
    pending: () => ({}),
    dropAllowed: true,
  },
);
const emit = defineEmits<{
  (event: "open", taskId: string): void;
  (event: "load-more", groupKey: string): void;
  (event: "drag-start", card: Card): void;
  (event: "drop", groupKey: string): void;
  (event: "move", card: Card): void;
}>();

/** Over the advisory limit the count changes and **nothing is refused** — Monstrare's
 *  semantics, kept from V1 (ADR 0028: WIP reports, it does not enforce). */
const overWip = computed(
  () => props.wipSuggested !== null && props.count > props.wipSuggested,
);
</script>

<template>
  <section
    class="column"
    :data-group="groupKey"
    :data-drop-allowed="dropAllowed"
    @dragover.prevent
    @drop.prevent="dropAllowed && emit('drop', groupKey)"
  >
    <header>
      <h3>{{ label }}</h3>
      <span class="count" :data-over-wip="overWip" data-server-count>
        {{ count
        }}<template v-if="wipSuggested"> / {{ wipSuggested }}</template>
      </span>
      <p v-if="windowNote" class="window-note">{{ windowNote }}</p>
    </header>
    <ul>
      <li v-for="card in items" :key="card.id">
        <WorkItemCard
          :card="card"
          :density="density"
          :draggable="canWrite"
          :pending="Boolean(pending[card.id])"
          @open="emit('open', $event)"
          @dragstart="emit('drag-start', card)"
        />
        <button
          v-if="canWrite"
          class="move"
          type="button"
          :data-move-for="card.card_ref"
          @click="emit('move', card)"
        >
          移動…
        </button>
      </li>
    </ul>
    <p v-if="items.length === 0" class="empty">—</p>
    <!-- Per column, not per page: "Load more" belongs to the column somebody clicked. -->
    <UiButton
      v-if="hasMore"
      size="sm"
      variant="ghost"
      :data-load-more="groupKey"
      @click="emit('load-more', groupKey)"
    >
      載入更多
    </UiButton>
  </section>
</template>

<style scoped>
.column {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  background: var(--surface-default);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  padding: var(--space-3);
  min-width: 260px;
  min-height: 320px;
}
.column[data-drop-allowed="false"] {
  /* A visible refusal at the target, before the drop. The server is still the decision. */
  border-style: dashed;
  border-color: var(--attention-blocked);
}
.column header {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 0 var(--space-2);
  align-items: baseline;
}
.column h3 {
  margin: 0;
  font-size: var(--font-sm);
  font-weight: 700;
  letter-spacing: 0.01em;
}
.count {
  min-width: 24px;
  padding: 2px 6px;
  border-radius: 999px;
  text-align: center;
  font-size: var(--font-xs);
  color: var(--text-muted);
  background: var(--surface-canvas);
  font-variant-numeric: tabular-nums;
}
/* Colour and weight, and the words are in the WIP number itself. */
.count[data-over-wip="true"] {
  color: var(--status-busy);
  font-weight: 600;
}
.window-note {
  grid-column: 1 / -1;
  margin: 2px 0 0;
  color: var(--text-muted);
  font-size: var(--font-xs);
}
.column ul {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}
.column li {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}
.move {
  align-self: flex-start;
  padding: 2px 6px;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  background: none;
  color: var(--text-muted);
  font-size: var(--font-xs);
  cursor: pointer;
}
.move:hover,
.move:focus-visible {
  border-color: var(--border-default);
  color: var(--text-primary);
}
.empty {
  margin: 0;
  color: var(--text-muted);
  text-align: center;
}
</style>
