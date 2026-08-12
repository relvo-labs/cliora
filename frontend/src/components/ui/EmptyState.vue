<script setup lang="ts">
import { useSlots } from "vue";

if (!useSlots().action) {
  console.warn("EmptyState requires an action slot with a safe next step.");
}
</script>

<template>
  <div class="empty" role="status">
    <div class="message"><slot /></div>
    <div class="action"><slot name="action" /></div>
  </div>
</template>

<style scoped>
.empty {
  display: grid;
  justify-items: start;
  gap: var(--space-3);
  padding: var(--space-5);
  border: 1px dashed var(--border-default);
  border-radius: var(--radius-lg);
  color: var(--text-muted);
  background: var(--surface-default);
}
.message {
  line-height: 1.55;
}
</style>
