<script setup lang="ts">
// Read-only file preview pane (P3-08). Owns nothing itself: `useMonacoModel`
// owns the editor and its models, this component only renders the header
// affordances (read-only marker, find, word wrap, copy, goto line, refresh) and
// swaps between the editor host and the denial pane.
//
// The editor host element stays mounted in every state so Monaco is created once;
// it is hidden (not unmounted) while a denial or an empty state shows.

//
// Images take a second route (ADR 0029, plan/31/05 BP-06 §1): when Central says
// this session may preview binaries *and* the name looks like one, the file
// goes to `useBinaryPreview` and a canvas instead of the text read. The hint is
// only a hint — the daemon decides what the file is — and with the capability
// false or absent (an old Central, an old or disabled node) every file takes
// the text path exactly as before, including the FILE_BINARY pane.

import { computed, defineAsyncComponent, onMounted, ref, watch } from "vue";

import { api } from "../../stores/auth";
import {
  routeHint,
  useBinaryPreview,
  type BinaryDenialState,
} from "../../composables/useBinaryPreview";
import { useMonacoModel } from "../../composables/useMonacoModel";
import { setPreviewTheme } from "../../monaco/setup";
import { ROOT_PATH, useFilesStore } from "../../stores/files";
import { usePreferencesStore } from "../../stores/preferences";
import { useSessionsStore } from "../../stores/sessions";
import UiButton from "../ui/UiButton.vue";
import ImagePreview from "./ImagePreview.vue";

// Its own chunk, with PDF.js behind it: nobody who never opens a PDF downloads
// the library (ADR 0029 §12; the first-load bundle does not change).
const PdfPreview = defineAsyncComponent(() => import("./PdfPreview.vue"));
import PreviewDenied from "./PreviewDenied.vue";

const props = defineProps<{
  sessionId: string | null;
  // Set by the tree when a file row is activated; null closes the preview.
  relPath: string | null;
  // Whether this node hands files back at all (ADR 0028 §6). The control is
  // hidden rather than disabled when false, the same rule the upload affordances
  // follow: a button that is always going to fail is worse than no button.
  canDownload?: boolean;
  // True while this pane's file is being fetched, so the control can say so.
  downloading?: boolean;
}>();

// The view owns the download, not this pane. Two reasons: the denial pane below
// offers the same action for a file this pane cannot render, and the composable's
// abort has to outlive a preview that closes mid-download.
// `close`: the user cancelled a binary load, or went back to the list from a
// refusal — either way the preview is done and the view closes it.
const emit = defineEmits<{ download: [relPath: string]; close: [] }>();

const host = ref<HTMLElement | null>(null);
const copied = ref(false);
const preferences = usePreferencesStore();

const sessionId = computed(() => props.sessionId);

const preview = useMonacoModel(
  (relPath, signal) =>
    api().readFileContent(props.sessionId ?? "", relPath, { signal }),
  { sessionId },
);

// Server-computed (flag ∧ the node's live report ∧ file.browse), read from the
// payload the view already loaded, for exactly the session this pane shows.
// Absent means false: a new console against an old Central keeps the text
// path (ADR 0029 §9).
const sessions = useSessionsStore();
const canPreviewBinary = computed(() => {
  const current = sessions.current;
  return (
    current !== null &&
    current.id === props.sessionId &&
    current.capabilities?.can_preview_binary === true
  );
});

const binary = useBinaryPreview({ sessionId, enabled: canPreviewBinary });

// A path sent back to the text route: the user chose "改用文字預覽", or Central
// said this node's live connection does not preview after all.
const textFallback = ref<string | null>(null);
const binaryRoute = computed(
  () =>
    props.relPath !== null &&
    canPreviewBinary.value &&
    routeHint(props.relPath) &&
    textFallback.value !== props.relPath,
);

// One place decides which route a path takes. The text branch is the call the
// pane always made; the binary branch closes the text one first, and vice
// versa, so neither route's content survives into the other.
function route(): void {
  const path = props.relPath;
  if (!path) {
    binary.close();
    preview.close();
    return;
  }
  if (binaryRoute.value) {
    preview.close();
    void binary.open(path);
  } else {
    binary.close();
    void preview.openFile(path);
  }
}

onMounted(() => {
  if (host.value) {
    preview.mount(host.value);
  }
  if (props.relPath) {
    route();
  }
});

// The path changing, the capability changing, or a fallback to text: all three
// re-route. The capability's own disposal has already happened synchronously
// inside the composable by the time this runs.
watch([() => props.relPath, binaryRoute], ([next], [previous]) => {
  if (next !== previous) {
    copied.value = false;
    textFallback.value = null;
  }
  route();
});

watch(binary.state, (state) => {
  if (state === "node_unsupported") textFallback.value = props.relPath;
});

const DENIAL_STATES = new Set<string>([
  "cancelled",
  "denied_sensitive",
  "denied_access",
  "permission",
  "too_large",
  "limit",
  "invalid",
  "changed",
  "unsupported",
  "render_failed",
  "unsupported_browser",
  "offline",
  "forbidden",
  "busy",
  "transfer_failed",
  "session_ended",
  "pdf_password_required",
  "pdf_too_many_pages",
]);
const binaryDenial = computed(() => {
  const state = binary.state.value;
  return DENIAL_STATES.has(state)
    ? { state: state as BinaryDenialState, detail: binary.detail.value }
    : null;
});

function cancelBinary(): void {
  binary.cancel();
  emit("close");
}

function useTextPreview(): void {
  textFallback.value = props.relPath;
}

// "Refresh the list" from a not-found/outside-root refusal: re-read the folder
// the file was in (the store's public action; stores/files.ts is unchanged),
// then go back to it.
function refreshList(): void {
  const parts = (props.relPath ?? "").split("/");
  parts.pop();
  void useFilesStore().refreshDir(parts.join("/") || ROOT_PATH);
  emit("close");
}

function refreshCurrent(): void {
  if (binaryRoute.value) void binary.retry();
  else void preview.refresh();
}

function formatSize(size: number): string {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / (1024 * 1024)).toFixed(2)} MB`;
}
const binaryMeta = computed(() => {
  const m = binary.meta.value;
  if (!m || binary.state.value !== "ready") return "";
  const pages = binary.pdf.value ? ` · ${binary.pdf.value.numPages} 頁` : "";
  const dims = m.width && m.height ? ` · ${m.width}×${m.height}` : pages;
  return `${props.relPath} · ${m.mime}${dims} · ${formatSize(m.size)}`;
});

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
// Downloadable whenever a path is open, including one the editor refused to
// render: "cannot be shown here" and "cannot be handed over" are different
// questions, and the denial pane is where the second one gets answered
// (ADR 0028 §3).
const canDownloadNow = computed(
  () => props.canDownload === true && Boolean(preview.currentPath.value),
);
const fileName = computed(
  () =>
    (binaryRoute.value ? props.relPath : preview.currentPath.value)
      ?.split("/")
      .pop() ?? "",
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
        <!-- Text-only tools. An image has nothing to search, wrap or copy, and
             a copy control on an image would be a save affordance by another
             name (ADR 0029 §11). -->
        <template v-if="!binaryRoute">
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
        </template>
        <button
          type="button"
          :disabled="
            binaryRoute
              ? binary.state.value === 'loading' ||
                binary.state.value === 'session_ended'
              : !preview.currentPath.value
          "
          @click="refreshCurrent"
        >
          重新整理
        </button>
        <button
          v-if="canDownloadNow"
          type="button"
          :disabled="downloading"
          :title="`下載 ${fileName}`"
          @click="emit('download', preview.currentPath.value!)"
        >
          {{ downloading ? "下載中…" : "下載" }}
        </button>
      </div>
    </header>

    <p v-if="preview.meta.value && showEditor" class="meta">
      {{ preview.meta.value.relPath }} · {{ preview.meta.value.language }} ·
      {{ preview.meta.value.encoding ?? "utf-8" }}
    </p>
    <p v-else-if="binaryRoute && binaryMeta" class="meta">{{ binaryMeta }}</p>

    <div class="body">
      <!-- Editor host: always mounted, hidden unless a file is previewable. -->
      <div
        ref="host"
        class="host"
        :hidden="!showEditor"
        :aria-hidden="!showEditor || undefined"
      />

      <!-- The binary route. Nothing here can save, share or open the file
           elsewhere, in any state (ADR 0029 §16). -->
      <template v-if="binaryRoute">
        <div
          v-if="binary.state.value === 'loading'"
          class="loading"
          role="status"
        >
          <p class="hint">正在載入預覽…</p>
          <progress
            class="bar"
            :max="binary.progress.value.total || undefined"
            :value="binary.progress.value.received || undefined"
            aria-label="預覽載入進度"
          />
          <!-- Throttled, so a screen reader hears a few steps, not every
               chunk. -->
          <p class="sr-only" aria-live="polite">
            {{ binary.announcement.value }}
          </p>
          <UiButton variant="secondary" @click="cancelBinary">取消</UiButton>
        </div>
        <ImagePreview
          v-else-if="binary.state.value === 'ready' && binary.bitmap.value"
          :bitmap="binary.bitmap.value"
          :name="fileName"
          :first-frame-only="binary.meta.value?.mime === 'image/gif'"
          :register="binary.registerCanvas"
        />
        <PdfPreview
          v-else-if="binary.state.value === 'ready' && binary.pdf.value"
          :doc="binary.pdf.value"
          :name="fileName"
          :register="binary.registerCanvas"
          :track-render="binary.trackRender"
        />
        <PreviewDenied
          v-else-if="binaryDenial"
          :binary="binaryDenial"
          :rel-path="relPath ?? ''"
          @retry="binary.retry()"
          @text="useTextPreview"
          @refresh-list="refreshList"
        />
      </template>

      <template v-else>
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
          :can-download="canDownloadNow"
          :downloading="downloading"
          @refresh="preview.refresh()"
          @download="emit('download', preview.currentPath.value!)"
        />
      </template>
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
.loading {
  display: grid;
  justify-items: start;
  align-content: center;
  gap: 10px;
  height: 100%;
  padding: 16px;
}
.loading .hint {
  padding: 0;
}
.bar {
  width: min(100%, 320px);
  accent-color: var(--accent-primary);
}
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
}

/* Narrow: the preview is the whole screen, so the toolbar has to survive at
   390px and its controls have to be tappable (plan/29 MS-16). Nothing about
   what the preview *is* changes here — still read-only, still text/code only,
   same denial taxonomy. */
@media (max-width: 767px) {
  .tools {
    flex-wrap: wrap;
  }
  .tools button {
    min-height: var(--density-touch);
    padding: 0 12px;
  }
  /* The preview reaches the bottom edge on a phone, and per MS-02 the element
     that touches the edge is the one that applies the inset. */
  .preview {
    padding-bottom: env(safe-area-inset-bottom, 0px);
  }
}
</style>
