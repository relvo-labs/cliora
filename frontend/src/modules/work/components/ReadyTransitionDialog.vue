<script setup lang="ts">
/**
 * "Send to Ready" when the Definition of Ready is not met (PX-30, D97, plan/26/06 §5).
 *
 * **A warning that can be pressed through, not a gate.** The server does not refuse the
 * move — `_readiness_warnings` returns warnings and `update_task` writes anyway (ADR 0028
 * §1, because a board that refuses is a board that stops being written to). So this dialog
 * must not look like a gate, and the one sentence that does the work is *「Definition of
 * Ready 不會阻擋這次移動」*: a person shown a list of missing items assumes it is a
 * barrier, and the first one to press **仍要送到 Ready** would otherwise believe they had
 * bypassed something.
 *
 * **Each missing item is a link into the field that fills it.** A list somebody has to
 * translate into "so where do I type that" is a list that gets pressed past. Clicking a row
 * closes this and opens the Drawer with that field focused — which is why the emit carries
 * the readiness *key*, not a label: the Drawer maps keys to its own fields, and a label is
 * for reading.
 *
 * **Nothing is fetched here.** The caller has already loaded the card, because it had to
 * know there was something missing to show this at all. `readiness_missing` is deliberately
 * *not* on the board's card DTO — it measured +20 % of the whole payload for something one
 * dialog needs about one card (`test_work_items_size`), so the caller reads
 * `/api/tasks/{id}` when it opens this.
 */
import { computed } from "vue";

import UiButton from "../../../components/ui/UiButton.vue";

const props = defineProps<{
  /** The card being moved, or null when the dialog is closed. */
  cardRef: string | null;
  /** Readiness keys still unticked, in the process's own order. */
  missing: string[];
  /** `key → label` from the project's effective process. A key with no label is shown
   *  as the key: a project may have items this console's build does not know about, and
   *  hiding one would under-report what is missing. */
  labels: Record<string, string>;
  busy?: boolean;
}>();

const emit = defineEmits<{
  (event: "close"): void;
  (event: "proceed"): void;
  (event: "fill", readinessKey: string): void;
}>();

const rows = computed(() =>
  props.missing.map((key) => ({ key, label: props.labels[key] ?? key })),
);
</script>

<template>
  <div v-if="cardRef" class="backdrop" @click.self="emit('close')">
    <div
      class="dialog"
      role="dialog"
      :aria-label="`${cardRef} 送到就緒`"
      data-ready-dialog
    >
      <h2>這張卡還缺 {{ missing.length }} 項</h2>

      <ul class="missing">
        <li v-for="row in rows" :key="row.key">
          <button
            type="button"
            class="fill"
            :data-fill="row.key"
            @click="emit('fill', row.key)"
          >
            <span class="box" aria-hidden="true">☐</span>
            <span class="label">{{ row.label }}</span>
            <span class="arrow">開啟並聚焦 →</span>
          </button>
        </li>
      </ul>

      <!-- **The sentence that stops this reading as a gate.** Not a footnote: it is why
           the second button exists and why pressing it is not a bypass. -->
      <p class="not-a-gate" data-not-a-gate>
        Definition of Ready 不會阻擋這次移動，但缺項會出現在這張卡的就緒徽章上。
      </p>

      <div class="actions">
        <UiButton variant="ghost" data-ready-cancel @click="emit('close')">
          取消
        </UiButton>
        <UiButton
          v-if="rows.length"
          variant="secondary"
          data-fill-first
          @click="emit('fill', rows[0].key)"
        >
          補齊缺失項
        </UiButton>
        <UiButton
          variant="primary"
          :disabled="busy"
          data-proceed-anyway
          @click="emit('proceed')"
        >
          仍要送到 Ready
        </UiButton>
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
  width: min(480px, 92vw);
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
.actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
}
.missing {
  margin: 0 0 var(--space-3);
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}
.fill {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  width: 100%;
  padding: var(--space-2);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  background: var(--surface-elevated);
  color: var(--text-primary);
  font-size: var(--font-sm);
  text-align: left;
  cursor: pointer;
}
.fill:hover,
.fill:focus-visible {
  border-color: var(--border-focus);
}
.label {
  flex: 1;
}
.arrow {
  color: var(--text-muted);
  font-size: var(--font-xs);
}
.not-a-gate {
  margin: 0;
  color: var(--text-muted);
  font-size: var(--font-xs);
  line-height: 1.6;
}
</style>
