<script setup lang="ts">
/**
 * What to do with a selection (PX-30, plan/26/05 §5).
 *
 * **It says out loud that bulk has no optimistic lock.** Bulk means "make these cards say
 * this", so carrying a version per card would require reading a hundred current versions
 * first — and the honest consequence is that a concurrent edit is overwritten. Saying so
 * is the mitigation; silently letting the last writer win is not.
 *
 * All-or-nothing, and that is also stated: a partial success needs an interface that says
 * which cards succeeded, and that is a different feature rather than a relaxation.
 */
import UiButton from "../../../components/ui/UiButton.vue";

const props = defineProps<{ count: number; busy: boolean }>();
defineEmits<{
  (event: "set-stage", stage: string): void;
  (event: "set-risk", risk: string): void;
  (event: "clear"): void;
}>();
</script>

<template>
  <div v-if="props.count > 0" class="bulk" role="region" aria-label="批次動作">
    <strong data-bulk-count>已選取 {{ props.count }} 張</strong>
    <UiButton
      size="sm"
      variant="secondary"
      :disabled="busy"
      data-bulk-ready
      @click="$emit('set-stage', 'ready')"
    >
      送到就緒
    </UiButton>
    <UiButton
      size="sm"
      variant="ghost"
      :disabled="busy"
      data-bulk-high-risk
      @click="$emit('set-risk', 'high')"
    >
      標為高風險
    </UiButton>
    <UiButton
      size="sm"
      variant="ghost"
      :disabled="busy"
      @click="$emit('clear')"
    >
      取消選取
    </UiButton>
    <p class="caveat">
      批次修改是全部或全不，而且<strong>不帶樂觀鎖</strong>——
      期間別人的修改會被覆蓋。
    </p>
  </div>
</template>

<style scoped>
.bulk {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3);
  border: 1px solid var(--action-primary);
  border-radius: var(--radius-md);
  background: color-mix(
    in srgb,
    var(--action-primary) 8%,
    var(--surface-elevated)
  );
  margin-bottom: var(--space-3);
}
.bulk strong {
  font-size: var(--font-sm);
}
.caveat {
  flex-basis: 100%;
  margin: 0;
  color: var(--text-secondary);
  font-size: var(--font-xs);
}
</style>
