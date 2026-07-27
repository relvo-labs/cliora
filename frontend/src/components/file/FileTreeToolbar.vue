<script setup lang="ts">
// Tree toolbar: manual refresh of the current directory level, plus the opt-in
// auto-refresh for a running session (FR-FILE-006). MVP has no filesystem
// watching, so these are the only invalidation paths and both must be
// discoverable.

import { RefreshCw } from "lucide-vue-next";

defineProps<{ dirLabel: string; busy?: boolean; autoRefresh?: boolean }>();
const emit = defineEmits<{ refresh: []; "update:autoRefresh": [boolean] }>();
</script>

<template>
  <div class="toolbar">
    <span class="scope" :title="dirLabel">{{ dirLabel }}</span>
    <label class="auto">
      <input
        type="checkbox"
        :checked="autoRefresh"
        @change="
          emit(
            'update:autoRefresh',
            ($event.target as HTMLInputElement).checked,
          )
        "
      />
      自動重新整理
    </label>
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
.auto {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  flex: none;
  font-size: 11px;
  color: var(--text-secondary);
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
