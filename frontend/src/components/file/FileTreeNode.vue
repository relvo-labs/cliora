<script setup lang="ts">
// One row of the workspace file tree. Entry rows are real `treeitem`s; status
// and "load more" rows are presentational so keyboard navigation only ever lands
// on a file or a directory.
//
// Every distinction (directory / file / symlink / hidden / excluded / loading) is
// carried by an icon *and* text — never colour alone (style.md state contract).

import {
  ChevronDown,
  ChevronRight,
  File,
  FileCode,
  FileText,
  Folder,
  FolderOpen,
  Link2,
  Lock,
  PlugZap,
  RefreshCw,
  TriangleAlert,
} from "lucide-vue-next";
import { computed } from "vue";

import type { TreeRow } from "../../composables/useFileTree";

const props = defineProps<{
  row: TreeRow;
  // Stable-per-render DOM id: the tree points aria-activedescendant at it.
  domId: string;
  focused: boolean;
  selected: boolean;
  // True while a drag is hovering this row's destination (ADR 0026). The parent
  // owns which row that is, because the destination for a *file* row is its parent
  // directory and only the parent knows the tree shape.
  dropTarget?: boolean;
  // Where a drop on this row would land. Shown while dragging, so the user sees
  // the destination before letting go.
  dropLabel?: string;
}>();

const emit = defineEmits<{
  activate: [row: TreeRow];
  toggle: [row: TreeRow];
}>();

const isEntry = computed(
  () => props.row.kind === "entry" || props.row.kind === "root",
);
const isDirectory = computed(
  () => props.row.kind === "root" || props.row.entry?.type === "directory",
);
const excluded = computed(() => props.row.entry?.excluded === true);
const hidden = computed(() => props.row.entry?.hidden === true);

const CODE_EXTENSIONS = new Set([
  "ts",
  "tsx",
  "js",
  "jsx",
  "mjs",
  "cjs",
  "py",
  "go",
  "rs",
  "vue",
  "java",
  "rb",
  "php",
  "c",
  "h",
  "cpp",
  "cs",
  "sh",
  "sql",
]);

const fileIcon = computed(() => {
  if (props.row.entry?.type === "symlink") {
    return Link2;
  }
  const ext = props.row.name.split(".").pop()?.toLowerCase() ?? "";
  if (CODE_EXTENSIONS.has(ext)) {
    return FileCode;
  }
  if (["md", "markdown", "txt", "json", "yaml", "yml", "toml"].includes(ext)) {
    return FileText;
  }
  return File;
});

const statusIcon = computed(() => {
  switch (props.row.state) {
    case "loading":
      return RefreshCw;
    case "forbidden":
      return Lock;
    case "offline":
      return PlugZap;
    default:
      return TriangleAlert;
  }
});

// Screen-reader text for a row: name plus every non-colour distinction.
const label = computed(() => {
  const bits: string[] = [props.row.name];
  if (props.row.kind === "root") {
    bits.push("workspace root");
  } else if (isDirectory.value) {
    bits.push("folder");
  } else if (props.row.entry?.type === "symlink") {
    bits.push("symbolic link");
  } else {
    bits.push("file");
  }
  if (hidden.value) bits.push("hidden");
  if (excluded.value) bits.push("excluded, not loaded");
  if (props.row.busy) bits.push("loading");
  return bits.join(", ");
});
</script>

<template>
  <!-- Real tree item: a file, a symlink, a directory, or the workspace root. -->
  <!-- No tabindex: the tree container is the single tab stop and marks the
       focused row with aria-activedescendant, so a re-render that replaces this
       element can never drop keyboard focus out of the tree. -->
  <div
    v-if="isEntry"
    :id="domId"
    class="row"
    role="treeitem"
    :aria-level="row.level"
    :aria-expanded="row.expandable ? row.expanded : undefined"
    :aria-selected="selected"
    :aria-busy="row.busy || undefined"
    :aria-label="label"
    :data-key="row.key"
    :data-focused="focused || undefined"
    :data-selected="selected || undefined"
    :data-drop-target="dropTarget || undefined"
    :style="{ paddingInlineStart: `${(row.level - 1) * 14 + 6}px` }"
    @click="emit('activate', row)"
  >
    <button
      v-if="row.expandable"
      class="twisty"
      type="button"
      tabindex="-1"
      :aria-label="row.expanded ? `Collapse ${row.name}` : `Expand ${row.name}`"
      @click.stop="emit('toggle', row)"
    >
      <ChevronDown v-if="row.expanded" :size="13" aria-hidden="true" />
      <ChevronRight v-else :size="13" aria-hidden="true" />
    </button>
    <span v-else class="twisty spacer" aria-hidden="true" />

    <component
      :is="isDirectory ? (row.expanded ? FolderOpen : Folder) : fileIcon"
      class="icon"
      :size="14"
      aria-hidden="true"
    />
    <span class="name" :data-hidden="hidden || undefined">{{ row.name }}</span>
    <span v-if="excluded" class="badge">已排除</span>
    <span v-if="row.entry?.type === 'symlink'" class="badge">連結</span>
    <RefreshCw v-if="row.busy" class="spin" :size="12" aria-hidden="true" />
    <!-- The actual destination, not the row under the cursor: dropping on a file
         means "put it next to this file", so the label has to name that folder or
         the user is guessing. -->
    <span v-if="dropTarget && dropLabel" class="drop-hint">
      放到 {{ dropLabel }}/
    </span>
  </div>

  <!-- "Load more": the daemon truncated this level (partial state). -->
  <button
    v-else-if="row.kind === 'more'"
    class="row more"
    type="button"
    :style="{ paddingInlineStart: `${(row.level - 1) * 14 + 20}px` }"
    @click="emit('activate', row)"
  >
    <span class="name">還有更多項目 — 載入下一頁</span>
  </button>

  <!-- Status row: loading / empty / forbidden / offline / error for this level. -->
  <p
    v-else
    class="row status"
    :data-state="row.state"
    role="status"
    :style="{ paddingInlineStart: `${(row.level - 1) * 14 + 20}px` }"
  >
    <component :is="statusIcon" class="icon" :size="13" aria-hidden="true" />
    <span class="name">{{ row.message ?? row.state }}</span>
  </p>
</template>

<style scoped>
.row {
  display: flex;
  align-items: center;
  gap: 4px;
  min-height: 24px;
  padding-block: 2px;
  padding-inline-end: 6px;
  border-radius: var(--radius-panel);
  font-size: 12px;
  color: var(--text-primary);
  cursor: default;
  background: none;
  border: 0;
  width: 100%;
  text-align: start;
}
.row[role="treeitem"] {
  cursor: pointer;
}
.row[data-selected] {
  background: var(--surface-raised);
  color: var(--text-primary);
  font-weight: 600;
}
.row[data-focused] {
  outline: 2px solid var(--focus-ring);
  outline-offset: -2px;
}
.twisty {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 14px;
  height: 14px;
  padding: 0;
  border: 0;
  background: none;
  color: var(--text-secondary);
}
.twisty.spacer {
  display: inline-block;
}
.icon {
  flex: none;
  color: var(--text-secondary);
}
.name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.name[data-hidden] {
  color: var(--text-secondary);
}
/* Outline plus text, never colour alone (style.md state contract): a hovered row
 * gets a dashed outline AND a label naming where the file would land. */
.row[data-drop-target] {
  outline: 1px dashed var(--accent-strong);
  outline-offset: -1px;
  background: var(--surface-raised);
}
.drop-hint {
  margin-inline-start: auto;
  padding-inline: 6px;
  font-size: 10px;
  font-weight: 600;
  color: var(--accent-strong);
  white-space: nowrap;
}
.badge {
  flex: none;
  padding: 0 5px;
  border: 1px solid var(--border-subtle);
  border-radius: 999px;
  font-size: 10px;
  color: var(--text-secondary);
}
.more {
  color: var(--accent-strong);
  font-weight: 600;
  cursor: pointer;
}
.status {
  margin: 0;
  color: var(--text-secondary);
}
.status[data-state="error"],
.status[data-state="forbidden"] {
  color: var(--status-error-fg);
}
.status[data-state="offline"] {
  color: var(--status-neutral-fg);
}
.spin {
  animation: spin 1s linear infinite;
  color: var(--text-secondary);
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
@media (prefers-reduced-motion: reduce) {
  .spin {
    animation: none;
  }
}
</style>
