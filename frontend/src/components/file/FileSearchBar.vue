<script setup lang="ts">
// Filename search over the session workspace (FR-FILE-007). Filename substring
// only — never file content, and never a shell/ripgrep argument. Results are
// bounded by the daemon; a partial result says why it stopped, and clicking a
// hit goes back into the tree instead of opening an isolated list.

import { Search, X } from "lucide-vue-next";
import { computed, ref, watch } from "vue";

import type { FileSearchHit } from "../../api/dto";
import type { SearchSlice } from "../../stores/files";

const props = defineProps<{ slice: SearchSlice; busy?: boolean }>();
const emit = defineEmits<{
  submit: [keyword: string];
  clear: [];
  pick: [hit: FileSearchHit];
}>();

const keyword = ref(props.slice.keyword);

// A cleared or reset slice (session switch) clears the box too.
watch(
  () => props.slice.keyword,
  (next) => {
    if (next !== keyword.value) {
      keyword.value = next;
    }
  },
);

const STOP_REASONS: Record<string, string> = {
  results: "已達結果上限，僅顯示前面的相符項目。",
  depth: "已達搜尋深度上限，較深的目錄未掃描。",
  scanned: "已達掃描檔案數上限，結果不完整。",
  timeout: "搜尋逾時，僅顯示已找到的結果。",
};

const partialNote = computed(() =>
  props.slice.partial
    ? (STOP_REASONS[props.slice.stoppedReason ?? ""] ?? "結果不完整。")
    : "",
);

function submit(): void {
  const trimmed = keyword.value.trim();
  if (!trimmed) {
    emit("clear");
    return;
  }
  emit("submit", trimmed);
}

function clear(): void {
  keyword.value = "";
  emit("clear");
}
</script>

<template>
  <div class="search">
    <form class="field" role="search" @submit.prevent="submit">
      <Search class="lead" :size="13" aria-hidden="true" />
      <input
        v-model="keyword"
        type="search"
        name="file-keyword"
        aria-label="以檔名搜尋工作區"
        placeholder="搜尋檔名…"
        autocomplete="off"
        @keydown.esc.prevent="clear"
      />
      <button
        v-if="keyword"
        class="clear"
        type="button"
        aria-label="清除搜尋"
        @click="clear"
      >
        <X :size="13" aria-hidden="true" />
      </button>
    </form>

    <p v-if="slice.state === 'loading'" class="note" role="status">搜尋中…</p>
    <p
      v-else-if="
        slice.state === 'forbidden' ||
        slice.state === 'offline' ||
        slice.state === 'error'
      "
      class="note bad"
      role="status"
    >
      {{ slice.message }}
    </p>
    <p v-else-if="slice.state === 'empty'" class="note" role="status">
      沒有符合「{{ slice.keyword }}」的檔名。
    </p>

    <template v-if="slice.results.length">
      <p v-if="partialNote" class="note warn" role="status">
        {{ partialNote }}
      </p>
      <ul class="hits" :aria-label="`搜尋結果，共 ${slice.results.length} 筆`">
        <li v-for="hit in slice.results" :key="hit.rel_path">
          <button type="button" class="hit" @click="emit('pick', hit)">
            <span class="hit-name">{{ hit.name }}</span>
            <span class="hit-path">{{ hit.rel_path }}</span>
          </button>
        </li>
      </ul>
    </template>
  </div>
</template>

<style scoped>
.search {
  display: grid;
  gap: 6px;
}
.field {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 3px 6px;
  border: 1px solid var(--border-control);
  border-radius: var(--radius-control);
  background: var(--surface-raised);
}
.field:focus-within {
  outline: 2px solid var(--focus-ring);
  outline-offset: -1px;
}
.lead {
  flex: none;
  color: var(--text-secondary);
}
input {
  flex: 1;
  min-width: 0;
  border: 0;
  background: none;
  color: var(--text-primary);
  font-size: 12px;
}
input:focus {
  outline: none;
}
.clear {
  flex: none;
  border: 0;
  background: none;
  color: var(--text-secondary);
  display: inline-flex;
  align-items: center;
}
.note {
  margin: 0;
  font-size: 11px;
  color: var(--text-secondary);
}
.note.bad {
  color: var(--status-error-fg);
}
.note.warn {
  color: var(--status-warning-fg);
}
.hits {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 2px;
  max-height: 30vh;
  overflow: auto;
}
.hit {
  display: grid;
  width: 100%;
  gap: 1px;
  padding: 3px 6px;
  border: 0;
  border-radius: var(--radius-control);
  background: none;
  text-align: start;
  cursor: pointer;
}
.hit:hover,
.hit:focus-visible {
  background: var(--surface-raised);
}
.hit-name {
  font-size: 12px;
  color: var(--text-primary);
}
.hit-path {
  font-size: 10px;
  color: var(--text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
