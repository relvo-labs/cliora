// Monaco read-only preview lifecycle (P3-08, ADR 0015).
//
// This composable is the single owner of the editor instance and of every text
// model it creates. Models live in a bounded LRU cache (8): a cache hit reuses
// the model, an eviction disposes it immediately, and leaving the view or
// switching session disposes all of them plus the editor. Rapid file switching
// therefore cannot accumulate models or workers.
//
// The security-critical rule is the denial path: whenever the server answers
// with a denial for a file we may have shown before (replaced by a sensitive
// file, grown past the size cap, permission revoked, deleted), the model is
// disposed and detached *before* the denial pane renders, so no stale — possibly
// now-sensitive — content stays on screen.

import {
  computed,
  onScopeDispose,
  ref,
  shallowRef,
  watch,
  type Ref,
} from "vue";
import type * as Monaco from "monaco-editor/editor/editor.api";

import { isAbortError } from "../api/client";
import type { FileContent } from "../api/dto";
import { PREVIEW_THEME, monacoLanguage, setupMonaco } from "../monaco/setup";

export const MODEL_CACHE_LIMIT = 8;

export type PreviewState = "idle" | "loading" | "ready" | "denied" | "error";

export interface PreviewDenial {
  code: string;
  reason?: string;
  size?: number;
  mime?: string;
  modifiedAt?: string;
}

export interface PreviewMeta {
  relPath: string;
  language: string;
  size?: number;
  encoding?: string;
  modifiedAt?: string;
}

// Injected by the view so the composable never depends on the API client (and
// unit tests need no fetch mock).
export type ContentLoader = (
  relPath: string,
  signal: AbortSignal,
) => Promise<FileContent>;

export interface MonacoModelOptions {
  // Reactive session id; a change disposes every model (cache is session-scoped).
  sessionId: Ref<string | null>;
}

export function useMonacoModel(
  load: ContentLoader,
  options: MonacoModelOptions,
) {
  const state = ref<PreviewState>("idle");
  const denial = shallowRef<PreviewDenial | null>(null);
  const meta = shallowRef<PreviewMeta | null>(null);
  const errorMessage = ref("");
  const wordWrap = ref(true);
  const currentPath = ref<string | null>(null);

  let monaco: typeof Monaco | null = null;
  let editor: Monaco.editor.IStandaloneCodeEditor | null = null;
  const models = new Map<string, Monaco.editor.ITextModel>();
  let inflight: AbortController | null = null;
  let disposed = false;

  function keyFor(relPath: string): string {
    return `${options.sessionId.value ?? "-"}::${relPath}`;
  }

  function mount(element: HTMLElement): void {
    if (editor || disposed) {
      return;
    }
    monaco = setupMonaco();
    editor = monaco.editor.create(element, {
      // Read-only in both the model sense and the DOM sense: no typing, no
      // paste, no drop, no editing affordances (FR-FILE-002, SEC-004).
      readOnly: true,
      domReadOnly: true,
      automaticLayout: true,
      theme: PREVIEW_THEME,
      lineNumbers: "on",
      wordWrap: wordWrap.value ? "on" : "off",
      minimap: { enabled: false },
      scrollBeyondLastLine: false,
      renderWhitespace: "selection",
      fontFamily: "JetBrains Mono, ui-monospace, monospace",
      fontSize: 12,
      contextmenu: true,
      quickSuggestions: false,
      occurrencesHighlight: "off",
      folding: true,
      ariaLabel: "檔案預覽（唯讀）",
    });
  }

  // Detach and dispose the model for a path so nothing of it remains visible.
  function dropModel(relPath: string): void {
    const key = keyFor(relPath);
    const model = models.get(key);
    if (!model) {
      return;
    }
    if (editor?.getModel() === model) {
      editor.setModel(null);
    }
    model.dispose();
    models.delete(key);
  }

  function clearDisplay(): void {
    editor?.setModel(null);
  }

  // LRU eviction: never evict the model currently attached to the editor.
  function evictIfNeeded(): void {
    const attached = editor?.getModel() ?? null;
    while (models.size > MODEL_CACHE_LIMIT) {
      let evicted = false;
      for (const [key, model] of models) {
        if (model === attached) {
          continue;
        }
        model.dispose();
        models.delete(key);
        evicted = true;
        break;
      }
      if (!evicted) {
        return;
      }
    }
  }

  function attach(key: string, model: Monaco.editor.ITextModel): void {
    // Re-insert to mark most-recently-used.
    models.delete(key);
    models.set(key, model);
    editor?.setModel(model);
    evictIfNeeded();
  }

  function createModel(
    relPath: string,
    text: string,
    language: string,
  ): Monaco.editor.ITextModel | null {
    if (!monaco) {
      return null;
    }
    const uri = monaco.Uri.from({
      scheme: "cliora-preview",
      path: `/${relPath}`,
      query: options.sessionId.value ?? "",
    });
    const existing = monaco.editor.getModel(uri);
    if (existing) {
      existing.setValue(text);
      monaco.editor.setModelLanguage(existing, language);
      return existing;
    }
    return monaco.editor.createModel(text, language, uri);
  }

  async function openFile(
    relPath: string,
    options_: { force?: boolean } = {},
  ): Promise<void> {
    if (disposed) {
      return;
    }
    inflight?.abort();
    const controller = new AbortController();
    inflight = controller;
    const key = keyFor(relPath);
    currentPath.value = relPath;
    denial.value = null;
    errorMessage.value = "";

    const cached = models.get(key);
    if (cached && !options_.force) {
      attach(key, cached);
      state.value = "ready";
      return;
    }

    // Clear the previous file before the new one arrives: no residual content
    // from another file while loading.
    clearDisplay();
    state.value = "loading";

    let payload: FileContent;
    try {
      payload = await load(relPath, controller.signal);
    } catch (caught) {
      if (isAbortError(caught) || inflight !== controller) {
        return;
      }
      state.value = "error";
      errorMessage.value =
        caught instanceof Error ? caught.message : "無法讀取檔案內容。";
      meta.value = null;
      return;
    }
    if (inflight !== controller || disposed || currentPath.value !== relPath) {
      return;
    }

    if (!payload.success) {
      // A previously previewable file may have become denied: drop its model
      // first, then render the denial.
      dropModel(relPath);
      clearDisplay();
      denial.value = {
        code: payload.error?.code ?? "FILE_DENIED",
        reason: payload.error?.reason,
        size: payload.size,
        mime: payload.mime,
        modifiedAt: payload.modified_at,
      };
      meta.value = { relPath, language: "plaintext", size: payload.size };
      state.value = "denied";
      return;
    }

    const language = monacoLanguage(payload.language_hint);
    const model = createModel(relPath, payload.content ?? "", language);
    if (!model) {
      state.value = "error";
      errorMessage.value = "預覽器尚未就緒。";
      return;
    }
    attach(key, model);
    meta.value = {
      relPath,
      language,
      size: payload.size,
      encoding: payload.encoding,
      modifiedAt: payload.modified_at,
    };
    state.value = "ready";
  }

  // Re-read the current file from the node (FR-FILE-006). This is the path that
  // must catch an allowed→denied transition.
  async function refresh(): Promise<void> {
    if (currentPath.value) {
      await openFile(currentPath.value, { force: true });
    }
  }

  function close(): void {
    inflight?.abort();
    inflight = null;
    clearDisplay();
    currentPath.value = null;
    denial.value = null;
    meta.value = null;
    errorMessage.value = "";
    state.value = "idle";
  }

  function toggleWordWrap(): void {
    wordWrap.value = !wordWrap.value;
    editor?.updateOptions({ wordWrap: wordWrap.value ? "on" : "off" });
  }

  function gotoLine(): void {
    editor?.focus();
    editor?.trigger("preview", "editor.action.gotoLine", null);
  }

  function find(): void {
    editor?.focus();
    editor?.trigger("preview", "actions.find", null);
  }

  // Copy the visible content of a previewable file. Denial panes hold no
  // content, so there is nothing to copy in those states.
  async function copyAll(): Promise<boolean> {
    const model = editor?.getModel();
    if (!model || state.value !== "ready") {
      return false;
    }
    try {
      await navigator.clipboard.writeText(model.getValue());
      return true;
    } catch {
      return false;
    }
  }

  function disposeAll(): void {
    inflight?.abort();
    inflight = null;
    editor?.setModel(null);
    for (const model of models.values()) {
      model.dispose();
    }
    models.clear();
    currentPath.value = null;
    denial.value = null;
    meta.value = null;
    state.value = "idle";
  }

  function dispose(): void {
    if (disposed) {
      return;
    }
    disposed = true;
    disposeAll();
    editor?.dispose();
    editor = null;
  }

  // Session switch: every cached model belongs to the previous session and must
  // go, along with anything on screen.
  watch(options.sessionId, () => disposeAll());

  onScopeDispose(dispose);

  return {
    mount,
    openFile,
    refresh,
    close,
    dispose,
    disposeAll,
    toggleWordWrap,
    gotoLine,
    find,
    copyAll,
    state,
    denial,
    meta,
    errorMessage,
    wordWrap,
    currentPath,
    // Test seam for the leak gate: live models must never exceed the cache cap.
    modelCount: () => models.size,
    isReady: computed(() => state.value === "ready"),
  };
}
