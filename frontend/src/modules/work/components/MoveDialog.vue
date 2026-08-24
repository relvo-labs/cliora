<script setup lang="ts">
/**
 * Moving a card with the keyboard (PX-34, merged from upstream PX-35).
 *
 * **Not a fallback for the drag — the same mutation, through the same call.** They were
 * two tickets upstream, and that is precisely how a codebase ends up with two rollback
 * implementations, one of which is subtly wrong. HTML5 drag-and-drop is also unusable with
 * a keyboard and unreliable under Playwright, so this is the path the e2e suite drives.
 *
 * The announcement is made **before and after**, because a screen-reader user needs to
 * know both what is about to happen and whether it did (plan/26/06 §3.4).
 */
import { computed, ref, watch } from "vue";

import type { WorkItemCard } from "../../../api/dto";
import UiButton from "../../../components/ui/UiButton.vue";

const props = defineProps<{
  card: WorkItemCard | null;
  /** `[{ key, label }]` — the groups this board is showing. */
  groups: { key: string; label: string }[];
  /** Cards already in each group, in order, so a position can be named. */
  itemsByGroup: Record<string, WorkItemCard[]>;
}>();
const emit = defineEmits<{
  (event: "close"): void;
  (
    event: "confirm",
    payload: {
      card: WorkItemCard;
      previous: WorkItemCard | null;
      next: WorkItemCard | null;
      groupKey: string;
    },
  ): void;
}>();

const targetGroup = ref("");
const position = ref(0);

watch(
  () => props.card,
  (card) => {
    if (!card) return;
    // The card's own group, not the first one: a move usually reorders within a column,
    // and defaulting to somebody else's column makes the common case two changes.
    targetGroup.value =
      props.groups.find((group) => group.key === card.lifecycle)?.key ??
      props.groups[0]?.key ??
      "";
    position.value = 0;
  },
  // `immediate`, because the dialog is mounted with a card already set — the parent
  // renders it from `moving`, which is non-null exactly when it should be open.
  { immediate: true },
);

/** The cards in the target group, with the moving card removed.
 *
 *  Removed because "position 3" has to mean the same thing before and after: leaving the
 *  card in its own list makes the index shift by one when it moves down. */
const siblings = computed(() =>
  (props.itemsByGroup[targetGroup.value] ?? []).filter(
    (item) => item.id !== props.card?.id,
  ),
);

const options = computed(() => [
  { value: 0, label: "最前面" },
  ...siblings.value.map((item, index) => ({
    value: index + 1,
    label: `在 ${item.card_ref} 之後`,
  })),
]);

function confirm(): void {
  if (!props.card) return;
  // **Neighbours, not the index.** The index is how a person names a position; the
  // request names the two cards it lands between, because on a filtered board position 3
  // of the list is not position 3 of the lane.
  const previous =
    position.value > 0 ? siblings.value[position.value - 1] : null;
  const next = siblings.value[position.value] ?? null;
  emit("confirm", {
    card: props.card,
    previous: previous ?? null,
    next,
    groupKey: targetGroup.value,
  });
}
</script>

<template>
  <div v-if="card" class="backdrop" @click.self="emit('close')">
    <div class="dialog" role="dialog" aria-label="移動卡片" data-move-dialog>
      <h2>移動 {{ card.card_ref }}</h2>
      <label>
        欄位
        <select v-model="targetGroup" data-move-group>
          <option v-for="group in groups" :key="group.key" :value="group.key">
            {{ group.label }}
          </option>
        </select>
      </label>
      <label>
        位置
        <select v-model.number="position" data-move-position>
          <option
            v-for="option in options"
            :key="option.value"
            :value="option.value"
          >
            {{ option.label }}
          </option>
        </select>
      </label>
      <div class="actions">
        <UiButton variant="ghost" @click="emit('close')">取消</UiButton>
        <UiButton variant="primary" data-move-confirm @click="confirm"
          >移動</UiButton
        >
      </div>
    </div>
  </div>
</template>

<style scoped>
.backdrop {
  position: fixed;
  inset: 0;
  z-index: 50;
  display: grid;
  place-items: center;
  background: color-mix(in srgb, var(--text-primary) 24%, transparent);
}
.dialog {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  width: min(420px, 92vw);
  padding: var(--space-4);
  border-radius: var(--radius-md);
  background: var(--surface-elevated);
  box-shadow: 0 12px 32px
    color-mix(in srgb, var(--text-primary) 18%, transparent);
}
.dialog h2 {
  margin: 0;
  font-size: var(--font-md);
}
.dialog label {
  display: grid;
  gap: var(--space-1);
  font-size: var(--font-sm);
  color: var(--text-secondary);
}
.dialog select {
  padding: 6px 8px;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  background: var(--surface-elevated);
  color: var(--text-primary);
  font-size: var(--font-sm);
}
.actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
}
</style>
