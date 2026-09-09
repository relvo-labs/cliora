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
import { setPreviewTheme } from "../../monaco/setup";
import { usePreferencesStore } from "../../stores/preferences";
import PreviewDenied from "./PreviewDenied.vue";

const props = defineProps<{
  sessionId: string | null;
  // Set by the tree when a file row is activated; null closes the preview.
  relPath: string | null;
}>();

const host = ref<HTMLElement | null>(null);
const copied = ref(false);
const preferences = usePreferencesStore();

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

// The theme reaction lives here rather than in the workspace view, because this
// is the component that already has Monaco in its bundle — putting it upstairs
// would drag the editor into the view that is careful not to load it.
//
// `monaco.editor.setTheme` is global and needs neither a new editor nor a new
// model, so the scroll position, folding state and find matches all survive a
// theme switch. Theming an editor is also not granting it a capability:
// `readOnly` and the contribution list are untouched (ADR 0015).
watch(
  () => preferences.theme,
  (id) => setPreviewTheme(id),
  { immediate: true },
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
/* Same fix as the terminal panes (plan/09 LY-03): the row template this replaces
 * (`auto auto 1fr`) only worked when `.meta` was rendered. It is a `v-if`, so in
 * the raw, hint and error states `.body` fell into the second `auto` row and
 * Monaco's container collapsed to nothing. */
.preview {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-height: 0;
  height: 100%;
}
.head,
.meta {
  flex: 0 0 auto;
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
  color: var(--text-primary);
}
.file {
  font-family:
    JetBrains Mono,
    ui-monospace,
    monospace;
}
.readonly {
  padding: 1px 6px;
  border: 1px solid var(--border-subtle);
  border-radius: 999px;
  font-size: 10px;
  font-weight: 600;
  color: var(--text-secondary);
  text-transform: uppercase;
}
.tools {
  display: flex;
  gap: 4px;
}
.tools button {
  padding: 3px 8px;
  border: 1px solid var(--border-control);
  border-radius: var(--radius-control);
  background: var(--surface-raised);
  color: var(--text-primary);
  font-size: 11px;
  font-weight: 600;
}
.tools button:disabled {
  color: var(--text-disabled);
}
.tools button[aria-pressed="true"] {
  border-color: var(--accent-strong);
  color: var(--accent-strong);
}
.meta {
  margin: 0;
  font-size: 11px;
  color: var(--text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.body {
  flex: 1 1 auto;
  position: relative;
  min-height: 0;
  border-radius: var(--radius-panel);
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
  color: var(--text-on-terminal-dim);
}
.hint.bad {
  color: var(--status-error-fg);
}
.link {
  border: 0;
  background: none;
  color: var(--accent-strong);
  font-weight: 600;
}
</style>
