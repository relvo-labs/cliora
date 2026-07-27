<script setup lang="ts">
defineProps<{ status: string }>();
</script>
<template>
  <span class="badge" :data-status="status" role="status"
    ><i aria-hidden="true" />{{ status }}</span
  >
</template>
<style scoped>
.badge {
  display: inline-flex;
  height: 24px;
  align-items: center;
  gap: 7px;
  padding: 0 10px;
  border-radius: 999px;
  background: #e9edf2;
  color: var(--text-secondary);
  font-size: 12px;
  text-transform: capitalize;
}
.badge i {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: currentColor;
}
.badge[data-status="connected"] {
  background: #e8f5ee;
  color: #2f815b;
}
.badge[data-status="reconnecting"] {
  background: #fbf2e4;
  color: #a56f28;
}
.badge[data-status="gap"],
.badge[data-status="exited"] {
  background: #f9eaea;
  color: #b34242;
}
/* Node statuses (style.md). The status word is always shown alongside the dot,
   so meaning never depends on colour alone (WCAG 1.4.1). */
.badge[data-status="online"] {
  background: #e8f5ee;
  color: var(--status-online);
}
.badge[data-status="degraded"] {
  background: #fbf2e4;
  color: var(--status-busy);
}
.badge[data-status="offline"] {
  background: #eef0f2;
  color: var(--status-offline);
}
.badge[data-status="disabled"] {
  background: #eef0f2;
  color: var(--status-offline);
  border: 1px dashed var(--status-offline);
}
.badge[data-status="error"] {
  background: #f9eaea;
  color: var(--status-error);
}
</style>
