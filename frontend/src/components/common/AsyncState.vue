<script setup lang="ts">
defineProps<{
  state:
    | "idle"
    | "loading"
    | "success"
    | "empty"
    | "stale"
    | "offline"
    | "forbidden"
    | "partial"
    | "error";
}>();
</script>
<template>
  <div class="async" role="status" aria-live="polite">
    <strong>{{ state }}</strong
    ><span
      ><slot>Cliora is {{ state }}.</slot></span
    >
  </div>
</template>
<style scoped>
.async {
  display: grid;
  gap: 4px;
  padding: 12px;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  background: var(--surface-elevated);
  font-size: 12px;
}
.async strong {
  text-transform: capitalize;
}
.async span {
  color: var(--text-muted);
}
</style>
