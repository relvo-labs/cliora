// One directory at a time, for the narrow viewport (plan/29 MS-14).
//
// This sits beside `useFileTree` rather than replacing it, and shares the same
// store. The two present the same data differently: the tree keeps every
// expanded level on screen at once, which is the right shape next to a terminal
// on a wide display and the wrong one on a 390px column, where four levels of
// indentation leave about twelve characters for the filename.
//
// Folding both into one composable was the alternative. It would carry
// `expandable`, `ancestors` and the `more` row into a presentation that has no
// use for any of them — and unused-but-present concepts are the ones the next
// change assumes someone depends on.
//
// No fetching lives here. `stores/files.ts` already loads per directory, keyed
// by workspace-relative path, and already aborts and wipes on a session change;
// that behaviour is load-bearing (addendum §2) and this composable is a reader
// of it.

import { computed, ref, watch, type Ref } from "vue";

import type { FileEntry } from "../api/dto";
import { ROOT_PATH, useFilesStore, type DirState } from "../stores/files";

export interface Crumb {
  /** Workspace-relative path this crumb navigates to. */
  path: string;
  /** Folder name, never a path. The root's label comes from the caller. */
  label: string;
}

export interface FileBrowserOptions {
  sessionId: Ref<string | null>;
  /** Folder name for the workspace root, not a full path (ADR 0014). */
  rootLabel: Ref<string>;
  canBrowse: Ref<boolean>;
}

export function useFileBrowser(options: FileBrowserOptions) {
  const store = useFilesStore();
  const cwd = ref(ROOT_PATH);

  // A session change resets the location as well as the data. The store wipes
  // its own contents; if `cwd` survived, the new session would open on a path
  // that belonged to the old one — which is the one thing a
  // workspace-relative path must never do.
  watch(
    () => options.sessionId.value,
    () => {
      cwd.value = ROOT_PATH;
    },
  );

  watch(
    [() => options.sessionId.value, () => options.canBrowse.value, cwd],
    ([sessionId, canBrowse, path]) => {
      if (!sessionId || !canBrowse) return;
      void store.loadDir(path);
    },
    { immediate: true },
  );

  const node = computed(() => store.dirs[cwd.value]);
  const state = computed<DirState>(() => node.value?.state ?? "idle");
  const entries = computed<FileEntry[]>(() => node.value?.entries ?? []);
  const message = computed(() => node.value?.message);
  const truncated = computed(() => node.value?.truncated === true);

  const atRoot = computed(() => cwd.value === ROOT_PATH);

  // Breadcrumbs from the path, because the path is the only thing held. Walking
  // a parent chain in state would be a second source for the same fact, and the
  // two would disagree the first time a level was reached by search rather than
  // by browsing.
  const crumbs = computed<Crumb[]>(() => {
    const root: Crumb = {
      path: ROOT_PATH,
      label: options.rootLabel.value || "workspace",
    };
    if (atRoot.value) return [root];
    const parts = cwd.value.split("/").filter(Boolean);
    return [
      root,
      ...parts.map((label, index) => ({
        path: parts.slice(0, index + 1).join("/"),
        label,
      })),
    ];
  });

  /** The parent directory, or `undefined` at the workspace root. */
  const parent = computed(() => {
    if (atRoot.value) return undefined;
    const parts = cwd.value.split("/").filter(Boolean);
    parts.pop();
    return parts.length === 0 ? ROOT_PATH : parts.join("/");
  });

  function goTo(path: string): void {
    cwd.value = path || ROOT_PATH;
  }

  function up(): void {
    const target = parent.value;
    if (target !== undefined) cwd.value = target;
  }

  /**
   * Open an entry. Directories navigate; everything else is handed back to the
   * caller, because opening a file is a preview decision and preview has its
   * own capability gate.
   */
  function enter(entry: FileEntry): FileEntry | undefined {
    // `excluded` directories are listed but not loadable — the daemon says so,
    // and walking into one would produce an error the user was told to expect.
    if (entry.type === "directory" && !entry.excluded) {
      cwd.value = entry.rel_path;
      return undefined;
    }
    return entry;
  }

  function refresh(): void {
    void store.loadDir(cwd.value, { force: true });
  }

  /**
   * Continue a truncated level.
   *
   * The daemon caps a listing and hands back an opaque cursor; a UI that stops
   * there while looking complete is the failure ADR 0014/0015 name explicitly.
   */
  function loadMore(): void {
    const cursor = node.value?.nextCursor;
    if (!cursor) return;
    void store.loadDir(cwd.value, { cursor });
  }

  return {
    cwd,
    crumbs,
    atRoot,
    parent,
    node,
    state,
    entries,
    message,
    truncated,
    goTo,
    up,
    enter,
    refresh,
    loadMore,
  };
}
