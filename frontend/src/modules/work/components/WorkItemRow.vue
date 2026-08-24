<script setup lang="ts">
/**
 * One row in the Backlog / List layout (PX-30, plan/26/06 §4).
 *
 * A row rather than a card because the Backlog's job is different: a board is for
 * *scanning* state and a backlog is for *ordering* work, so the row leads with the rank
 * handle and the selection checkbox and puts attention beside the title rather than above
 * it.
 *
 * **Inline rename is on the title, in place, and it does not open the card.** Renaming is
 * the most common edit a backlog gets — a card filed in thirty seconds gets a better name
 * a minute later — and routing it through the Drawer costs an open, a scroll and a close
 * for one field. Escape abandons and Enter saves, so a mistaken double-click has an exit
 * that is not "save whatever is in the box".
 */
import { nextTick, ref } from "vue";

import type { WorkItemCard } from "../../../api/dto";
import UiButton from "../../../components/ui/UiButton.vue";
import AttentionBadge from "./AttentionBadge.vue";

const props = withDefaults(
  defineProps<{
    card: WorkItemCard;
    selected?: boolean;
    canWrite?: boolean;
  }>(),
  { selected: false, canWrite: false },
);
const emit = defineEmits<{
  (event: "open", taskId: string): void;
  (event: "toggle", taskId: string): void;
  (event: "move", card: WorkItemCard): void;
  (event: "rename", payload: { card: WorkItemCard; title: string }): void;
  (event: "ready", card: WorkItemCard): void;
}>();

const editing = ref(false);
const draft = ref("");
const input = ref<HTMLInputElement | null>(null);

async function startRename(): Promise<void> {
  // **Not renameable when the title is hidden.** `title` is optional on the card because
  // a view's `visible_fields` may drop it, and a rename box pre-filled with "" would
  // silently replace a title nobody could see.
  if (!props.canWrite || props.card.title === undefined) return;
  draft.value = props.card.title;
  editing.value = true;
  await nextTick();
  input.value?.select();
}

function commit(): void {
  const title = draft.value.trim();
  editing.value = false;
  // An unchanged title is not a write. Without this, a stray double-click on every row of
  // a backlog would be a PATCH per row and an activity entry per row.
  if (!title || title === props.card.title) return;
  emit("rename", { card: props.card, title });
}

function abandon(): void {
  editing.value = false;
}
</script>

<template>
  <li class="row" :data-card-ref="card.card_ref" :data-selected="selected">
    <input
      v-if="canWrite"
      type="checkbox"
      :checked="selected"
      :aria-label="`選取 ${card.card_ref}`"
      :data-select="card.card_ref"
      @change="$emit('toggle', card.id)"
    />
    <button
      v-if="canWrite"
      class="handle"
      type="button"
      :aria-label="`移動 ${card.card_ref}`"
      :data-move-for="card.card_ref"
      @click="$emit('move', card)"
    >
      ⋮⋮
    </button>
    <span v-if="editing" class="renaming">
      <span class="ref">{{ card.card_ref }}</span>
      <input
        ref="input"
        v-model="draft"
        class="rename-input"
        :aria-label="`重新命名 ${card.card_ref}`"
        :data-rename-input="card.card_ref"
        @keydown.enter.prevent="commit"
        @keydown.esc.prevent="abandon"
        @blur="commit"
      />
    </span>
    <button
      v-else
      class="open"
      type="button"
      @click="emit('open', card.id)"
      @dblclick.stop.prevent="startRename"
    >
      <span class="ref">{{ card.card_ref }}</span>
      <span class="title">{{ card.title }}</span>
    </button>
    <!-- A visible affordance as well as the double-click: a gesture with no control is a
         feature only the person who built it knows about, and it is unreachable by
         keyboard. -->
    <button
      v-if="canWrite && !editing && card.title !== undefined"
      class="handle"
      type="button"
      :aria-label="`重新命名 ${card.card_ref}`"
      :data-rename-for="card.card_ref"
      @click="startRename"
    >
      ✎
    </button>
    <AttentionBadge
      v-if="card.primary_attention"
      density="compact"
      :primary="card.primary_attention"
      :count="card.attention_count ?? 1"
    />
    <span class="readiness" :data-readiness="card.readiness">
      {{
        card.readiness === "ready"
          ? "已就緒"
          : card.readiness === "needs_clarification"
            ? "待釐清"
            : "草稿"
      }}
    </span>
    <span class="owner">{{ card.owner_name ?? "—" }}</span>
    <!-- Only on a backlog card: the Backlog's whole job is deciding what moves next, and
         a "send to Ready" on a card that is already in Ready is a control with nothing to
         do. `lifecycle` may be hidden by a view's `visible_fields`, in which case the
         button is not offered rather than offered wrongly. -->
    <UiButton
      v-if="canWrite && card.lifecycle === 'backlog'"
      size="sm"
      variant="secondary"
      :data-send-ready="card.card_ref"
      @click="emit('ready', card)"
    >
      送到就緒
    </UiButton>
  </li>
</template>

<style scoped>
.row {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-3);
  border-bottom: 1px solid var(--border-default);
}
.row:last-child {
  border-bottom: 0;
}
.row[data-selected="true"] {
  background: color-mix(
    in srgb,
    var(--action-primary) 8%,
    var(--surface-elevated)
  );
}
.renaming {
  display: flex;
  flex: 1;
  align-items: center;
  gap: var(--space-2);
  min-width: 0;
}
.rename-input {
  flex: 1;
  min-width: 0;
  padding: 4px 6px;
  border: 1px solid var(--border-focus);
  border-radius: var(--radius-sm);
  background: var(--surface-elevated);
  color: var(--text-primary);
  font-size: var(--font-sm);
}
.handle {
  flex: none;
  padding: 0 2px;
  border: 0;
  background: none;
  color: var(--text-muted);
  cursor: grab;
  font-size: var(--font-sm);
  letter-spacing: -2px;
}
.open {
  display: flex;
  align-items: baseline;
  gap: var(--space-2);
  flex: 1;
  min-width: 0;
  padding: 0;
  border: 0;
  background: none;
  text-align: left;
  cursor: pointer;
}
.ref {
  flex: none;
  font-family: var(--font-mono);
  font-size: var(--font-xs);
  color: var(--text-muted);
}
.title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-primary);
  font-size: var(--font-sm);
}
.open:hover .title {
  text-decoration: underline;
}
.readiness,
.owner {
  flex: none;
  color: var(--text-muted);
  font-size: var(--font-xs);
}
.readiness[data-readiness="draft"] {
  color: var(--attention-warning);
}
</style>
