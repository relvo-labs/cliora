<script setup lang="ts">
// The one table. Four views had written their own (NodesView, AuditView,
// SessionsView, NodeTunnelsView), so a row height, a header treatment and an
// overflow rule existed four times and agreed by luck.
//
// The rules it carries, each from somewhere specific:
//
//   * Row height is `--density-row` (48px), header on `--surface-raised`, and
//     **no zebra striping** (Porcelain §5). Stripes make a scanning eye track
//     the stripe rather than the row, and they fight a selected-row tint.
//   * The primary name is openable and the path is a **second line, not a
//     second column** (all five style documents). A path in its own column sets
//     the column width by its longest value, which is what pushes a table wide
//     enough to need a page-level scrollbar.
//   * Overflow scrolls **inside this component's own container**, never the
//     page (plan/08, plan/09).
//   * Empty and no-results are different states with different words, and this
//     component will not let a caller conflate them: it takes both slots.
//
// Not here on purpose: virtual scrolling, column resizing, column visibility
// toggles. Those solve a data-volume problem, and there is no evidence of one —
// AuditView, the largest list, already paginates.

withDefaults(
  defineProps<{
    /** Announced name. A table with no caption is a grid of unlabelled cells. */
    label: string;
    /** Column headers, in order. */
    columns: string[];
    /** True when there are zero rows *and* no filter is applied. */
    empty?: boolean;
    /** True when a filter or search is applied and matched nothing. */
    noResults?: boolean;
  }>(),
  {},
);
</script>

<template>
  <div class="wrap">
    <!-- The empty states replace the table rather than rendering an empty one:
         a header row above nothing reads as "still loading". -->
    <slot v-if="noResults" name="no-results" />
    <slot v-else-if="empty" name="empty" />
    <div v-else class="scroll">
      <table>
        <caption class="sr-only">
          {{
            label
          }}
        </caption>
        <thead>
          <tr>
            <th v-for="column in columns" :key="column" scope="col">
              {{ column }}
            </th>
          </tr>
        </thead>
        <tbody>
          <slot />
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.wrap {
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-panel);
  background: var(--surface-default);
  /* `hidden` so the child's scrollbar stays inside the rounded corner. The
     child is what scrolls. */
  overflow: hidden;
}
/* The one scrolling box. A wide table scrolls here, and the page does not. */
.scroll {
  overflow: auto;
}
table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
  text-align: left;
}
/* Visually hidden, still announced. `display: none` would remove it from the
   accessibility tree, which defeats the point of having a caption. */
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip-path: inset(50%);
  white-space: nowrap;
}
th {
  position: sticky;
  top: 0;
  z-index: 1;
  height: 40px;
  padding: 0 14px;
  background: var(--surface-raised);
  border-bottom: 1px solid var(--border-subtle);
  color: var(--text-secondary);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  white-space: nowrap;
}
:slotted(td) {
  height: var(--density-row);
  padding: 0 14px;
  border-top: 1px solid var(--border-subtle);
  color: var(--text-primary);
  vertical-align: middle;
}
/* Hover, not stripes. */
:slotted(tr:hover) td {
  background: var(--surface-raised);
}
/* The selected row's tint is accent-subtle, and text on it must be
   text-primary or accent-strong — never text-secondary, which measures 4.22:1
   there in the default theme. */
:slotted(tr[aria-selected="true"]) td {
  background: var(--accent-subtle);
  color: var(--text-primary);
}
/* The path under the name: a second line, not a second column. */
:slotted(td) :deep(small) {
  display: block;
  margin-top: 2px;
  color: var(--text-secondary);
  font-family: var(--font-mono);
  font-size: 11px;
  overflow-wrap: anywhere;
}
</style>
