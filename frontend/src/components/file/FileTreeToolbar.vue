<script setup lang="ts">
// Tree toolbar: manual refresh of the current directory level, plus the opt-in
// auto-refresh for a running session (FR-FILE-006). MVP has no filesystem
// watching, so these are the only invalidation paths and both must be
// discoverable.

import { RefreshCw, Upload } from "lucide-vue-next";
import { ref } from "vue";

defineProps<{
  dirLabel: string;
  busy?: boolean;
  autoRefresh?: boolean;
  // Mirrors the tree's own gate: server-computed permission AND the node's own
  // report (ADR 0026 §9). Hidden rather than disabled when false.
  canUpload?: boolean;
}>();
const emit = defineEmits<{
  refresh: [];
  "update:autoRefresh": [boolean];
  pick: [files: File[]];
}>();

// The picker is not a nicety alongside drag and drop — it is the only entry point
// that exists for keyboard and touch users, so it ships in the same change.
const fileInput = ref<HTMLInputElement | null>(null);

function onPicked(event: Event): void {
  const input = event.target as HTMLInputElement;
  const files = Array.from(input.files ?? []);
  // Reset so picking the same file twice in a row still fires a change event.
  input.value = "";
  if (files.length > 0) emit("pick", files);
}
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
      v-if="canUpload"
      type="button"
      class="action"
      :title="`上傳檔案到 ${dirLabel}`"
      @click="fileInput?.click()"
    >
      <Upload :size="12" aria-hidden="true" />
      上傳檔案
    </button>
    <input
      v-if="canUpload"
      ref="fileInput"
      type="file"
      multiple
      class="hidden-input"
      @change="onPicked"
    />
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
/* Visually hidden but still reachable by the button's click(). Not display:none —
 * some browsers refuse to open a picker for a fully hidden input. */
.hidden-input {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}
</style>
