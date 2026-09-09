<script setup lang="ts">
// A toolbar: actions on the left, search on the right, one row, fixed height.
//
// Fixed height matters more than it looks. A toolbar whose height comes from
// its contents changes the height of the panel below it whenever a button
// appears or a label wraps — and on the workspace that panel is the terminal,
// so a wrapping toolbar label silently costs terminal rows. plan/09 spent a
// whole phase on the class of bug this belongs to.
//
// Every icon button inside is a UiIconButton, which makes an accessible name
// mandatory rather than optional.

withDefaults(
  defineProps<{
    /** Announced name, e.g. "工作區檔案工具列". */
    label: string;
    /** Sitting on the terminal rather than on a panel. */
    onTerminal?: boolean;
  }>(),
  {},
);
</script>

<template>
  <div
    class="toolbar"
    :class="{ 'on-terminal': onTerminal }"
    role="toolbar"
    :aria-label="label"
  >
    <div class="start"><slot /></div>
    <div v-if="$slots.end" class="end"><slot name="end" /></div>
  </div>
</template>

<style scoped>
.toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  /* Fixed, and `flex-shrink: 0` so a flex parent cannot squeeze it either. */
  height: var(--density-control);
  flex-shrink: 0;
  padding: 0 8px;
  border-bottom: 1px solid var(--border-subtle);
  background: var(--surface-default);
}
.start,
.end {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}
.start {
  flex: 1;
}
.on-terminal {
  background: var(--terminal-background);
  border-color: var(--border-on-terminal);
  color: var(--text-on-terminal);
}
</style>
