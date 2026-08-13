<script setup lang="ts">
withDefaults(defineProps<{ flush?: boolean }>(), { flush: false });
</script>

<template>
  <section class="ui-card">
    <header v-if="$slots.header"><slot name="header" /></header>
    <div class="body" :class="{ flush }"><slot /></div>
  </section>
</template>

<style scoped>
.ui-card {
  overflow: hidden;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  background: var(--surface-elevated);
  box-shadow: 0 1px 2px color-mix(in srgb, var(--text-primary) 4%, transparent);
}
header {
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--border-default);
  font-weight: 600;
}
.body {
  padding: var(--space-4);
}
.body.flush {
  padding: 0;
}
</style>
