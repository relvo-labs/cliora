// Curated Monaco build for the read-only workspace preview (P3-08, ADR 0015).
//
// Three deliberate constraints:
//   1. Workers are self-bundled through Vite (`?worker`), so an offline build
//      runs with no CDN or remote script fetch of any kind.
//   2. Only the editor features a read-only viewer needs are registered — no
//      rename, no formatting, no code actions, no suggest/quick-command palette.
//      Fewer contributions means a smaller bundle and no write affordances.
//   3. Only the languages the daemon's `language_hint` can return are
//      registered, and only their tokenizers (syntax highlighting) — not the
//      TypeScript/JSON/CSS/HTML language *services*, which would need their own
//      workers and provide editing intelligence we do not want here.

import * as monaco from "monaco-editor/editor/editor.api";
import EditorWorker from "monaco-editor/editor/editor.worker.js?worker";

// Core editor widget + the keybindings that make cursor movement work.
import "monaco-editor/features/codeEditor/register";
import "monaco-editor/editor/browser/coreCommands.js";
// Read-only affordances required by FR-FILE-002.
import "monaco-editor/features/find/register"; // find widget (search)
import "monaco-editor/features/gotoLine/register"; // Ctrl+G goto line
import "monaco-editor/features/clipboard/register"; // copy
import "monaco-editor/features/contextmenu/register";
import "monaco-editor/features/bracketMatching/register";
import "monaco-editor/features/folding/register";
import "monaco-editor/features/wordHighlighter/register";
import "monaco-editor/features/unicodeHighlighter/register";
import "monaco-editor/features/readOnlyMessage/register";
import "monaco-editor/features/wordOperations/register";
import "monaco-editor/features/lineSelection/register";
import "monaco-editor/features/multicursor/register";
import "monaco-editor/features/codicon/register";

// Language tokenizers, one per language id the daemon can hint (see
// daemon/internal/files/policy.go LanguageHint).
import "monaco-editor/languages/definitions/css/register";
import "monaco-editor/languages/definitions/go/register";
import "monaco-editor/languages/definitions/html/register";
import "monaco-editor/languages/definitions/ini/register";
import "monaco-editor/languages/definitions/javascript/register";
import "monaco-editor/languages/definitions/markdown/register";
import "monaco-editor/languages/definitions/python/register";
import "monaco-editor/languages/definitions/rust/register";
import "monaco-editor/languages/definitions/shell/register";
import "monaco-editor/languages/definitions/sql/register";
import "monaco-editor/languages/definitions/typescript/register";
import "monaco-editor/languages/definitions/xml/register";
import "monaco-editor/languages/definitions/yaml/register";

// Count worker constructions so the leak gate can prove rapid file switching
// does not accumulate workers.
let workersCreated = 0;

export function monacoWorkerCount(): number {
  return workersCreated;
}

// Monaco asks for a worker by label; every label resolves to the bundled editor
// worker because no language service is registered.
type MonacoEnvironment = {
  getWorker: (moduleId: string, label: string) => Worker;
};

function installEnvironment(): void {
  const globalScope = self as unknown as {
    MonacoEnvironment?: MonacoEnvironment;
  };
  if (globalScope.MonacoEnvironment) {
    return;
  }
  globalScope.MonacoEnvironment = {
    getWorker() {
      workersCreated += 1;
      return new EditorWorker();
    },
  };
}

// Preview theme: derived from the same semantic tokens as the terminal so the
// workspace reads as one surface (style.md). Not the stock vs-dark palette.
export const PREVIEW_THEME = "cliora-preview";

let themeDefined = false;

function defineTheme(): void {
  if (themeDefined) {
    return;
  }
  monaco.editor.defineTheme(PREVIEW_THEME, {
    base: "vs-dark",
    inherit: true,
    rules: [],
    colors: {
      "editor.background": "#0f1115",
      "editor.foreground": "#d7dde4",
      "editorLineNumber.foreground": "#66707d",
      "editorLineNumber.activeForeground": "#d7dde4",
      "editor.selectionBackground": "#78aaff40",
      "editor.lineHighlightBackground": "#171a20",
      "editorCursor.foreground": "#ffffff",
      "editorGutter.background": "#0f1115",
      "editorWidget.background": "#171a20",
      "editorWidget.border": "#2a2f39",
    },
  });
  themeDefined = true;
}

// Idempotent one-time setup; safe to call from every component mount.
export function setupMonaco(): typeof monaco {
  installEnvironment();
  defineTheme();
  return monaco;
}

// The daemon's language hints are a superset of the tokenizers registered above:
// `vue`, `toml` and `json` have no standalone Monaco tokenizer (Monaco ships JSON
// only as a full language *service*, ~930 kB, whose diagnostics and completion a
// read-only viewer must not have anyway). Each maps onto the closest registered
// tokenizer instead of degrading to plaintext.
const LANGUAGE_ALIASES: Record<string, string> = {
  vue: "html",
  toml: "ini",
  json: "javascript",
};

export function monacoLanguage(hint: string | undefined): string {
  if (!hint) {
    return "plaintext";
  }
  return LANGUAGE_ALIASES[hint] ?? hint;
}

export { monaco };
