<script setup lang="ts">
// Read-only file preview pane (P3-08). Owns nothing itself: `useMonacoModel`
// owns the editor and its models, this component only renders the header
// affordances (read-only marker, find, word wrap, copy, goto line, refresh) and
// swaps between the editor host and the denial pane.
//
// The editor host element stays mounted in every state so Monaco is created once;
// it is hidden (not unmounted) while a denial or an empty state shows.

import { computed, onMounted, ref, watch } from "vue";

import { api } from "../../stores/auth";
import { useMonacoModel } from "../../composables/useMonacoModel";
import PreviewDenied from "./PreviewDenied.vue";

const props = defineProps<{
  sessionId: string | null;
  // Set by the tree when a file row is activated; null closes the preview.
  relPath: string | null;
}>();

const host = ref<HTMLElement | null>(null);
const copied = ref(false);

const sessionId = computed(() => props.sessionId);

const preview = useMonacoModel(
  (relPath, signal) =>
    api().readFileContent(props.sessionId ?? "", relPath, { signal }),
  { sessionId },
);

onMounted(() => {
  if (host.value) {
    preview.mount(host.value);
  }
  if (props.relPath) {
    void preview.openFile(props.relPath);
  }
});

watch(
  () => props.relPath,
  (next) => {
    copied.value = false;
    if (next) {
      void preview.openFile(next);
    } else {
      preview.close();
    }
  },
);

async function copy(): Promise<void> {
  copied.value = await preview.copyAll();
}

const showEditor = computed(() => preview.state.value === "ready");
const fileName = computed(
  () => preview.currentPath.value?.split("/").pop() ?? "",
);
</script>

<template>
  <section class="preview" aria-labelledby="preview-heading">
    <header class="head">
      <h2 id="preview-heading">
        <span class="file">{{ fileName || "Preview" }}</span>
        <span class="readonly" aria-label="唯讀預覽">唯讀</span>
      </h2>
      <div class="tools" role="group" aria-label="預覽工具">
        <button
          type="button"
          :disabled="!showEditor"
          title="搜尋（Ctrl+F）"
          @click="preview.find()"
        >
          搜尋
        </button>
        <button
          type="button"
          :disabled="!showEditor"
          :aria-pressed="preview.wordWrap.value"
          title="切換自動換行"
          @click="preview.toggleWordWrap()"
        >
          換行
        </button>
        <button
          type="button"
          :disabled="!showEditor"
          title="跳至行號（Ctrl+G）"
          @click="preview.gotoLine()"
        >
          行號
        </button>
        <button type="button" :disabled="!showEditor" @click="copy">
          {{ copied ? "已複製" : "複製" }}
        </button>
        <button
          type="button"
          :disabled="!preview.currentPath.value"
          @click="preview.refresh()"
        >
          重新整理
        </button>
      </div>
    </header>

    <p v-if="preview.meta.value && showEditor" class="meta">
      {{ preview.meta.value.relPath }} · {{ preview.meta.value.language }} ·
      {{ preview.meta.value.encoding ?? "utf-8" }}
    </p>

    <div class="body">
      <!-- Editor host: always mounted, hidden unless a file is previewable. -->
      <div
        ref="host"
        class="host"
        :hidden="!showEditor"
        :aria-hidden="!showEditor || undefined"
      />

      <p v-if="preview.state.value === 'idle'" class="hint" role="status">
        從左側檔案樹選擇檔案即可預覽（唯讀）。
      </p>
      <p
        v-else-if="preview.state.value === 'loading'"
        class="hint"
        role="status"
      >
        載入檔案內容…
      </p>
      <p
        v-else-if="preview.state.value === 'error'"
        class="hint bad"
        role="alert"
      >
        {{ preview.errorMessage.value || "無法讀取檔案內容。" }}
        <button type="button" class="link" @click="preview.refresh()">
          重試
        </button>
      </p>
      <PreviewDenied
        v-else-if="preview.state.value === 'denied' && preview.denial.value"
        :denial="preview.denial.value"
        :rel-path="preview.currentPath.value ?? ''"
        @refresh="preview.refresh()"
      />
    </div>
  </section>
</template>

<style scoped>
.preview {
  display: grid;
  grid-template-rows: auto auto 1fr;
  gap: 6px;
  min-height: 0;
  height: 100%;
}
.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: wrap;
}
h2 {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 0;
  font-size: 12px;
  color: var(--text-secondary);
}
.file {
  font-family:
    JetBrains Mono,
    ui-monospace,
    monospace;
}
.readonly {
  padding: 1px 6px;
  border: 1px solid var(--border-default);
  border-radius: 999px;
  font-size: 10px;
  font-weight: 600;
  color: var(--text-muted);
  text-transform: uppercase;
}
.tools {
  display: flex;
  gap: 4px;
}
.tools button {
  padding: 3px 8px;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  background: var(--surface-default);
  color: var(--text-secondary);
  font-size: 11px;
  font-weight: 600;
}
.tools button:disabled {
  color: var(--action-disabled);
}
.tools button[aria-pressed="true"] {
  border-color: var(--action-primary);
  color: var(--action-primary);
}
.meta {
  margin: 0;
  font-size: 11px;
  color: var(--text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.body {
  position: relative;
  min-height: 0;
  border-radius: var(--radius-md);
  overflow: hidden;
  background: var(--terminal-background);
}
.host {
  width: 100%;
  height: 100%;
}
.hint {
  margin: 0;
  padding: 16px;
  font-size: 12px;
  color: #9aa4b2;
}
.hint.bad {
  color: var(--status-error);
}
.link {
  border: 0;
  background: none;
  color: var(--action-primary);
  font-weight: 600;
}
</style>
