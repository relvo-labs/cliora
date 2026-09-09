<script setup lang="ts">
// Workspace file tree panel (P3-07): search bar, refresh toolbar, and the lazy
// `role="tree"` itself. The whole-tree states (forbidden / offline / error) are
// rendered instead of the tree; per-level states are rendered inside it.
//
// The tree is a single tab stop: arrow keys move focus between rows and only
// Enter/Space (or a click) opens a file, so walking a large directory never
// triggers a preview fetch.

import { computed, nextTick, ref, watch } from "vue";

import type { FileEntry, FileSearchHit } from "../../api/dto";
import { filesFromDrop } from "../../composables/useFileUpload";
import { useFileTree, type TreeRow } from "../../composables/useFileTree";
import { ROOT_PATH } from "../../stores/files";
import UiInlineNotice from "../../components/ui/UiInlineNotice.vue";
import FileSearchBar from "./FileSearchBar.vue";
import FileTreeNode from "./FileTreeNode.vue";
import FileTreeToolbar from "./FileTreeToolbar.vue";

const props = defineProps<{
  sessionId: string | null;
  // Workspace folder name — never the node's absolute path.
  rootLabel: string;
  // False when the viewer lacks file.browse: show the RBAC affordance, fetch nothing.
  canBrowse: boolean;
  // Set when the session itself is unusable (terminated/exited).
  disabledReason?: string;
  // True only when the server says this user may upload AND the node says it
  // accepts uploads (ADR 0026 §9). Both are server-derived: the browser must not
  // re-derive RBAC and must not guess the node's posture. When false the drop
  // target does not highlight and nothing is uploaded — hiding rather than
  // disabling, because a control that refuses on release is worse than none.
  canUpload?: boolean;
}>();

const emit = defineEmits<{
  open: [relPath: string, entry: FileEntry];
  clear: [];
  // Emitted with the files and the resolved destination; the view owns the queue
  // because it also owns the panel the progress list is rendered into.
  upload: [files: File[], directory: string];
  // A refusal that applies to the whole drop (a folder, an unreadable transfer).
  uploadRefused: [message: string];
}>();

const treeEl = ref<HTMLElement | null>(null);

// Row DOM ids are positional (`ftr-<index>`): a rel_path may contain whitespace
// or other characters that are invalid in an id, and both the id and
// aria-activedescendant are produced by the same render, so they always agree.
function rowDomId(index: number): string {
  return `ftr-${index}`;
}

// A missing permission or a dead session means we never bind a session id, so
// no request is issued at all.
const activeSessionId = computed(() =>
  props.canBrowse && !props.disabledReason ? props.sessionId : null,
);
const rootLabel = computed(() => props.rootLabel);

const tree = useFileTree({
  sessionId: activeSessionId,
  rootLabel,
  onOpen: (relPath, entry) => emit("open", relPath, entry),
  onClear: () => emit("clear"),
});

// The id of the row the composable considers focused; the container advertises
// it via aria-activedescendant so assistive tech follows arrow-key movement.
const activeDescendant = computed(() => {
  const index = tree.rows.value.findIndex(
    (row) => row.key === tree.focusedKey.value,
  );
  return index >= 0 ? rowDomId(index) : undefined;
});

// Keep the focused row in view when the arrow keys walk past the viewport edge.
watch(activeDescendant, async (id) => {
  if (!id) return;
  await nextTick();
  const target = Array.from(
    treeEl.value?.querySelectorAll<HTMLElement>("[data-key]") ?? [],
  ).find((element) => element.dataset.key === tree.focusedKey.value);
  target?.scrollIntoView?.({ block: "nearest" });
});

const rootState = computed(() => tree.rootState.value);
const busy = computed(() => rootState.value === "loading");

function activate(row: TreeRow): void {
  void tree.activate(row);
}
function toggle(row: TreeRow): void {
  void tree.toggle(row);
}
function pick(hit: FileSearchHit): void {
  void tree.reveal(hit.rel_path);
}

const currentDirLabel = computed(() => {
  const dir = tree.currentDir();
  return dir === ROOT_PATH ? props.rootLabel || "workspace" : dir;
});

// --- Drag and drop (FU-06, ADR 0026) --------------------------------------
//
// The hovered destination, not the hovered row: dropping on a file targets its
// parent directory (`tree.dropTargetFor`). `dragDepth` counts enter/leave pairs
// because every row has nested children — an unguarded `dragleave` handler would
// flicker the highlight off each time the cursor crossed an icon.

const dropDir = ref<string | null>(null);
let dragDepth = 0;

function labelFor(dir: string): string {
  return dir === ROOT_PATH ? props.rootLabel || "workspace" : dir;
}

function isDropTarget(row: TreeRow): boolean {
  if (!props.canUpload || dropDir.value === null) return false;
  return tree.dropTargetFor(row) === dropDir.value;
}

function onDragEnter(row: TreeRow): void {
  if (!props.canUpload) return;
  dragDepth += 1;
  const target = tree.dropTargetFor(row);
  if (target !== null) dropDir.value = target;
}

function onDragOver(row: TreeRow, event: DragEvent): void {
  if (!props.canUpload) return;
  const target = tree.dropTargetFor(row);
  if (target === null) return;
  // Without preventDefault the browser never fires `drop` — and would navigate to
  // the file instead.
  event.preventDefault();
  if (event.dataTransfer) event.dataTransfer.dropEffect = "copy";
  dropDir.value = target;
}

function onDragLeave(): void {
  dragDepth -= 1;
  if (dragDepth <= 0) {
    dragDepth = 0;
    dropDir.value = null;
  }
}

function onDrop(row: TreeRow, event: DragEvent): void {
  dragDepth = 0;
  const target = props.canUpload ? tree.dropTargetFor(row) : null;
  dropDir.value = null;
  if (target === null) return;
  event.preventDefault();
  const { files, refusal } = filesFromDrop(event.dataTransfer);
  if (refusal) {
    emit("uploadRefused", refusal);
    return;
  }
  emit("upload", files, target);
}

// The picker: mandatory rather than a nicety, because drag and drop does not exist
// for keyboard or touch users. Its destination is the focused row's directory,
// which the toolbar shows.
function onPick(files: File[]): void {
  if (!props.canUpload || files.length === 0) return;
  emit("upload", files, tree.currentDir());
}
</script>

<template>
  <section class="tree-panel" aria-labelledby="file-tree-heading">
    <h2 id="file-tree-heading">Files</h2>

    <UiInlineNotice v-if="!canBrowse" tone="error" title="無法存取"
      >您的角色沒有 file.browse 權限，無法瀏覽工作區檔案。</UiInlineNotice
    >
    <UiInlineNotice
      v-else-if="disabledReason"
      tone="warning"
      title="來源目前離線"
      >{{ disabledReason }}</UiInlineNotice
    >

    <template v-else>
      <FileSearchBar
        :slice="tree.searchSlice.value"
        @submit="(keyword) => tree.search(keyword)"
        @clear="tree.clearSearch()"
        @pick="pick"
      />
      <FileTreeToolbar
        :dir-label="currentDirLabel"
        :busy="busy"
        :auto-refresh="tree.autoRefresh.value"
        :can-upload="canUpload"
        @refresh="tree.refresh()"
        @update:auto-refresh="tree.setAutoRefresh"
        @pick="onPick"
      />

      <UiInlineNotice
        v-if="rootState === 'forbidden'"
        tone="error"
        title="無法存取"
        >您沒有權限瀏覽此工作區的檔案。</UiInlineNotice
      >
      <UiInlineNotice
        v-else-if="rootState === 'offline'"
        tone="warning"
        title="來源目前離線"
        >Node 已離線，檔案樹暫時無法使用。</UiInlineNotice
      >
      <template v-else-if="rootState === 'error'">
        <UiInlineNotice tone="error" title="載入失敗"
          >{{ tree.rootMessage.value ?? "無法載入檔案樹。" }}
          <button class="link" type="button" @click="tree.refresh(ROOT_PATH)">
            重試
          </button></UiInlineNotice
        >
      </template>

      <div
        v-else
        ref="treeEl"
        class="tree"
        role="tree"
        aria-label="工作區檔案"
        tabindex="0"
        :aria-activedescendant="activeDescendant"
        :aria-busy="busy || undefined"
        @keydown="tree.onKeydown"
      >
        <FileTreeNode
          v-for="(row, index) in tree.rows.value"
          :key="row.key"
          :row="row"
          :dom-id="rowDomId(index)"
          :focused="row.key === tree.focusedKey.value"
          :selected="row.key === tree.selectedKey.value"
          :drop-target="isDropTarget(row)"
          :drop-label="labelFor(dropDir ?? ROOT_PATH)"
          @activate="activate"
          @toggle="toggle"
          @dragenter="onDragEnter(row)"
          @dragover="(event: DragEvent) => onDragOver(row, event)"
          @dragleave="onDragLeave"
          @drop="(event: DragEvent) => onDrop(row, event)"
        />
      </div>
    </template>
  </section>
</template>

<style scoped>
/* Column, not a four-row template (plan/09 LY-03). The template happened to be
 * correct — heading, search, toolbar, tree is exactly four children — but it was
 * correct by coincidence: one more line of copy above the tree and the tree
 * would have lost its `1fr`, with no test able to see it. */
.tree-panel {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-height: 0;
  height: 100%;
}
h2 {
  margin: 0;
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--text-secondary);
}
.tree {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
}
.link {
  border: 0;
  background: none;
  color: var(--accent-strong);
  font-weight: 600;
}
</style>
