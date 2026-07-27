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
import { useFileTree, type TreeRow } from "../../composables/useFileTree";
import { ROOT_PATH } from "../../stores/files";
import AsyncState from "../common/AsyncState.vue";
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
}>();

const emit = defineEmits<{
  open: [relPath: string, entry: FileEntry];
  clear: [];
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
</script>

<template>
  <section class="tree-panel" aria-labelledby="file-tree-heading">
    <h2 id="file-tree-heading">Files</h2>

    <AsyncState v-if="!canBrowse" state="forbidden">
      您的角色沒有 file.browse 權限，無法瀏覽工作區檔案。
    </AsyncState>
    <AsyncState v-else-if="disabledReason" state="offline">
      {{ disabledReason }}
    </AsyncState>

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
        @refresh="tree.refresh()"
      />

      <AsyncState v-if="rootState === 'forbidden'" state="forbidden">
        您沒有權限瀏覽此工作區的檔案。
      </AsyncState>
      <AsyncState v-else-if="rootState === 'offline'" state="offline">
        Node 已離線，檔案樹暫時無法使用。
      </AsyncState>
      <template v-else-if="rootState === 'error'">
        <AsyncState state="error">
          {{ tree.rootMessage.value ?? "無法載入檔案樹。" }}
          <button class="link" type="button" @click="tree.refresh(ROOT_PATH)">
            重試
          </button>
        </AsyncState>
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
          @activate="activate"
          @toggle="toggle"
        />
      </div>
    </template>
  </section>
</template>

<style scoped>
.tree-panel {
  display: grid;
  grid-template-rows: auto auto auto 1fr;
  gap: 8px;
  min-height: 0;
  height: 100%;
}
h2 {
  margin: 0;
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--text-muted);
}
.tree {
  min-height: 0;
  overflow: auto;
}
.link {
  border: 0;
  background: none;
  color: var(--action-primary);
  font-weight: 600;
}
</style>
