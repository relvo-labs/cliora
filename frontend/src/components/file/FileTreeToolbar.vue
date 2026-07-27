<script setup lang="ts">
// Tree toolbar: manual refresh of the current directory level (FR-FILE-006).
// MVP has no filesystem watching, so refresh is the only invalidation path and
// it must be discoverable.

import { RefreshCw } from "lucide-vue-next";

defineProps<{ dirLabel: string; busy?: boolean }>();
const emit = defineEmits<{ refresh: [] }>();
</script>

<template>
  <div class="toolbar">
    <span class="scope" :title="dirLabel">{{ dirLabel }}</span>
    <button
      type="button"
      class="action"
      :disabled="busy"
      :aria-busy="busy || undefined"
      @click="emit('refresh')"
    >
      <RefreshCw :size="12" aria-hidden="true" />
      重新整理
    </button>
  </div>
</template>

<style scoped>
.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
}
.scope {
  font-size: 11px;
  color: var(--text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.action {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  flex: none;
  padding: 3px 8px;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  background: var(--surface-default);
  color: var(--text-secondary);
  font-size: 11px;
  font-weight: 600;
}
.action:disabled {
  color: var(--action-disabled);
}
</style>
