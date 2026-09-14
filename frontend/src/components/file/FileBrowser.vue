<script setup lang="ts">
// The narrow-viewport file browser (plan/29 MS-14).
//
// One level at a time, with a breadcrumb and an up control, where `FileTree`
// shows every expanded level at once. The tree is the right shape beside a
// terminal on a wide display; in a 390px column four levels of indentation
// leave about twelve characters for the filename, which is not a compromise so
// much as a different failure.
//
// Everything security-relevant is unchanged and deliberately not re-decided
// here: the daemon is the path authority (ADR 0014), only workspace-relative
// paths are sent, search covers the whole workspace by filename substring and
// carries no root, and a truncated level says so and offers a real
// continuation. This component chooses a layout; it does not choose a
// contract.

import {
  ChevronRight,
  CornerLeftUp,
  Folder,
  File,
  Link,
} from "lucide-vue-next";
import { computed, toRef } from "vue";

import type { FileEntry, FileSearchHit } from "../../api/dto";
import { useFileBrowser } from "../../composables/useFileBrowser";
import { useFilesStore } from "../../stores/files";
import UiButton from "../ui/UiButton.vue";
import UiEmptyState from "../ui/UiEmptyState.vue";
import UiInlineNotice from "../ui/UiInlineNotice.vue";
import UiLoadingState from "../ui/UiLoadingState.vue";
import FileSearchBar from "./FileSearchBar.vue";

const props = defineProps<{
  sessionId: string | null;
  rootLabel: string;
  canBrowse: boolean;
  /** Why browsing is unavailable, when it is. Server-decided, not guessed. */
  disabledReason?: string;
}>();

const emit = defineEmits<{ open: [relPath: string] }>();

const store = useFilesStore();
const browser = useFileBrowser({
  sessionId: toRef(props, "sessionId"),
  rootLabel: toRef(props, "rootLabel"),
  canBrowse: toRef(props, "canBrowse"),
});

// Searching replaces the listing rather than filtering it, because it is a
// different question: the listing answers "what is in this folder", the search
// answers "where in the workspace is this name".
const searching = computed(() => store.search.state !== "idle");

function activate(entry: FileEntry): void {
  const file = browser.enter(entry);
  if (file) emit("open", file.rel_path);
}

function pick(hit: FileSearchHit): void {
  emit("open", hit.rel_path);
}

function icon(entry: FileEntry) {
  if (entry.type === "directory") return Folder;
  return entry.symlink ? Link : File;
}
</script>

<template>
  <div class="browser">
    <UiInlineNotice
      v-if="!canBrowse"
      tone="warning"
      :message="disabledReason ?? '你的角色沒有瀏覽這個工作區的權限。'"
    />

    <template v-else>
      <FileSearchBar
        :slice="store.search"
        :busy="store.search.state === 'loading'"
        @submit="(keyword) => store.runSearch(keyword)"
        @clear="store.clearSearch()"
        @pick="pick"
      />

      <template v-if="!searching">
        <!-- Relative, never absolute. The middle elides rather than the end:
             both the workspace root and the current folder are the parts that
             orient the user. -->
        <nav class="crumbs" aria-label="目前位置">
          <template
            v-for="(crumb, index) in browser.crumbs.value"
            :key="crumb.path"
          >
            <ChevronRight
              v-if="index > 0"
              class="sep"
              :size="12"
              aria-hidden="true"
            />
            <button
              type="button"
              class="crumb"
              :aria-current="
                index === browser.crumbs.value.length - 1
                  ? 'location'
                  : undefined
              "
              @click="browser.goTo(crumb.path)"
            >
              {{ crumb.label }}
            </button>
          </template>
        </nav>

        <ul class="entries" :aria-label="`${browser.cwd.value} 的內容`">
          <li v-if="!browser.atRoot.value">
            <button type="button" class="entry up" @click="browser.up()">
              <CornerLeftUp class="icon" :size="15" aria-hidden="true" />
              <span class="name">上一層</span>
            </button>
          </li>
          <li v-for="entry in browser.entries.value" :key="entry.rel_path">
            <button
              type="button"
              class="entry"
              :disabled="entry.excluded"
              @click="activate(entry)"
            >
              <component
                :is="icon(entry)"
                class="icon"
                :size="15"
                aria-hidden="true"
              />
              <span class="name">{{ entry.name }}</span>
              <!-- An excluded directory is listed and not loadable; saying why
                   is cheaper than letting the user find out by tapping. -->
              <span v-if="entry.excluded" class="tag">未納入</span>
              <ChevronRight
                v-else-if="entry.type === 'directory'"
                class="chev"
                :size="14"
                aria-hidden="true"
              />
            </button>
          </li>
        </ul>

        <UiLoadingState
          v-if="browser.state.value === 'loading'"
          label="正在載入資料夾"
        />
        <UiEmptyState
          v-else-if="browser.state.value === 'empty'"
          variant="empty"
          title="這個資料夾是空的"
          detail="沒有可顯示的項目。"
        />
        <UiInlineNotice
          v-else-if="
            browser.state.value === 'forbidden' ||
            browser.state.value === 'offline' ||
            browser.state.value === 'error'
          "
          tone="error"
          :message="browser.message.value ?? '無法載入這個資料夾。'"
        />

        <!-- A truncated level is never presented as a complete one. -->
        <div v-if="browser.truncated.value" class="more">
          <p class="note">這一層還沒載入完，目前顯示前面的項目。</p>
          <UiButton variant="secondary" @click="browser.loadMore()">
            載入更多
          </UiButton>
        </div>
      </template>
    </template>
  </div>
</template>

<style scoped>
.browser {
  display: grid;
  gap: 8px;
  align-content: start;
  min-height: 0;
  overflow: auto;
}
.crumbs {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 2px;
}
.crumb {
  min-height: var(--density-touch);
  padding: 0 6px;
  border: 0;
  background: none;
  color: var(--accent-strong);
  font: inherit;
  font-size: 12px;
}
.crumb[aria-current="location"] {
  color: var(--text-primary);
  font-weight: 600;
}
.sep {
  color: var(--text-secondary);
  flex-shrink: 0;
}
.entries {
  list-style: none;
  margin: 0;
  padding: 0;
}
/* The whole row is the control, and it is at least the touch floor tall. */
.entry {
  width: 100%;
  min-height: var(--density-row);
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 8px;
  border: 0;
  border-bottom: 1px solid var(--border-subtle);
  background: none;
  color: var(--text-primary);
  font: inherit;
  font-size: 13px;
  text-align: left;
}
.entry:disabled {
  color: var(--text-disabled);
}
.entry .icon {
  flex-shrink: 0;
  color: var(--text-secondary);
}
.name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
}
.chev {
  margin-left: auto;
  flex-shrink: 0;
  color: var(--text-secondary);
}
.tag {
  margin-left: auto;
  flex-shrink: 0;
  font-size: 11px;
  color: var(--text-secondary);
}
.more {
  display: grid;
  gap: 6px;
  padding: 8px 0;
}
.note {
  margin: 0;
  font-size: 11px;
  color: var(--status-warning-fg);
}
</style>
