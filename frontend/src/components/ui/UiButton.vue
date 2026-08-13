<script setup lang="ts">
withDefaults(
  defineProps<{
    variant?: "primary" | "secondary" | "ghost" | "danger";
    size?: "sm" | "md";
    type?: "button" | "submit" | "reset";
  }>(),
  { variant: "secondary", size: "md", type: "button" },
);
</script>

<template>
  <button :type="type" :class="[variant, `size-${size}`]">
    <slot />
  </button>
</template>

<style scoped>
button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  min-height: 34px;
  padding: 0 var(--space-3);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  color: var(--text-secondary);
  background: var(--surface-elevated);
  font-size: var(--font-sm);
  font-weight: 600;
  line-height: 1;
  white-space: nowrap;
}
button:hover:not(:disabled) {
  border-color: var(--text-muted);
  background: var(--surface-default);
}
button:disabled {
  cursor: not-allowed;
  color: var(--action-disabled);
  border-color: var(--border-default);
  background: var(--surface-canvas);
}
.primary {
  color: var(--text-inverse);
  border-color: var(--action-primary);
  background: var(--action-primary);
}
.primary:hover:not(:disabled) {
  border-color: var(--action-primary-hover);
  background: var(--action-primary-hover);
}
.ghost {
  border-color: transparent;
  background: transparent;
}
.ghost:hover:not(:disabled) {
  border-color: var(--border-default);
  background: var(--surface-default);
}
.danger {
  color: var(--status-error);
  border-color: var(--border-danger);
  background: var(--surface-elevated);
}
.size-sm {
  min-height: 28px;
  padding-inline: var(--space-2);
  font-size: var(--font-xs);
}
</style>
