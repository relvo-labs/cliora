<script setup lang="ts">
/**
 * One card on the board (PX-18/PX-29, plan/26/06 §3.2).
 *
 * Four zones in a fixed order, because the order is what makes a board scannable:
 * **attention** (why this needs a person), **identity**, **execution** (what the agent is
 * doing), **metadata**. Attention first because it is the only zone that can be urgent.
 *
 * `attention_count > 1` shows "＋N" and the rest lives in the Drawer (D107): a card
 * carrying all eight levels is a card nobody reads.
 */
import { computed } from "vue";

import type { WorkItemCard } from "../../../api/dto";
import AttentionBadge from "./AttentionBadge.vue";
import ExecutionLine from "./ExecutionLine.vue";

const props = withDefaults(
  defineProps<{
    card: WorkItemCard;
    density?: "comfortable" | "compact";
    draggable?: boolean;
    pending?: boolean;
  }>(),
  { density: "comfortable", draggable: false, pending: false },
);
defineEmits<{ (event: "open", taskId: string): void }>();

/** Metadata, capped by density (plan/26/06 §3.3).
 *
 *  Capped rather than wrapped: a card whose metadata line wraps to three rows changes the
 *  column's rhythm, and the rhythm is what lets somebody scan forty cards.
 */
const metadata = computed(() => {
  const parts = [
    props.card.owner_name,
    props.card.risk !== "medium" ? props.card.risk : null,
    props.card.delivery !== "none" ? props.card.delivery : null,
    props.card.blocking_count ? `阻塞 ${props.card.blocking_count}` : null,
    props.card.labels?.length ? props.card.labels[0] : null,
  ].filter((value): value is string => Boolean(value));
  return parts.slice(0, props.density === "compact" ? 2 : 5);
});
</script>

<template>
  <article
    class="work-card"
    :data-card-ref="card.card_ref"
    :data-density="density"
    :data-pending="pending || undefined"
    :data-attention="card.primary_attention ?? undefined"
    :draggable="draggable"
  >
    <AttentionBadge
      v-if="card.primary_attention"
      class="attention-strip"
      :primary="card.primary_attention"
      :count="card.attention_count ?? 1"
      :density="density"
    />
    <button class="open" type="button" @click="$emit('open', card.id)">
      <span class="ref">{{ card.card_ref }}</span>
      <span class="title">{{ card.title }}</span>
    </button>
    <ExecutionLine
      v-if="density === 'comfortable' || card.execution_status !== 'not_queued'"
      :status="card.execution_status ?? 'not_queued'"
      :runner-name="card.active_run_runner_name ?? null"
      :started-at="card.active_run_started_at ?? null"
    />
    <p v-if="metadata.length" class="meta">{{ metadata.join(" · ") }}</p>
  </article>
</template>

<style scoped>
.work-card {
  position: relative;
  overflow: hidden;
  background: var(--surface-elevated);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  padding: var(--space-3);
  box-shadow: 0 1px 2px color-mix(in srgb, var(--text-primary) 5%, transparent);
}
.work-card[data-density="compact"] {
  padding: var(--space-2);
}
.work-card[data-pending="true"] {
  opacity: 0.6;
}
/* The one card treatment that survives from plan/19 D24: a card waiting on a person is
 * outlined, not merely badged. */
.work-card[data-attention="waiting_for_your_input"] {
  border-color: var(--attention-human);
  box-shadow:
    0 0 0 1px var(--attention-human),
    0 2px 10px color-mix(in srgb, var(--attention-human) 18%, transparent);
}
.attention-strip {
  margin: calc(-1 * var(--space-3)) calc(-1 * var(--space-3)) var(--space-3);
  border-radius: var(--radius-sm) var(--radius-sm) 0 0;
  padding-left: var(--space-3);
  padding-right: var(--space-3);
}
.work-card[data-density="compact"] .attention-strip {
  margin: calc(-1 * var(--space-2)) calc(-1 * var(--space-2)) var(--space-2);
  padding-left: var(--space-2);
  padding-right: var(--space-2);
}
.open {
  display: block;
  width: 100%;
  padding: 0;
  border: 0;
  background: none;
  text-align: left;
  cursor: pointer;
}
.ref {
  display: block;
  font-family: var(--font-mono);
  font-size: var(--font-xs);
  color: var(--text-muted);
}
.title {
  display: block;
  margin-top: 2px;
  color: var(--text-primary);
  font-size: var(--font-sm);
  font-weight: 600;
  line-height: 1.4;
  /* Three lines comfortable, two compact (plan/26/06 §3.3). */
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.work-card[data-density="compact"] .title {
  -webkit-line-clamp: 2;
}
.open:hover .title {
  text-decoration: underline;
}
.meta {
  margin: var(--space-2) 0 0;
  color: var(--text-muted);
  font-size: var(--font-xs);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
