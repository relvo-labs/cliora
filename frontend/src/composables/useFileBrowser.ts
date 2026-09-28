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
// No fetching logic lives here. `stores/files.ts` already loads per directory,
// keyed by workspace-relative path, and already aborts and wipes on a session
// change; that behaviour is load-bearing (addendum §2) and this composable
// uses it rather than re-implementing it.
//
// It does have to *bind* the store, though, exactly as `useFileTree.bind` does
// (#76). The store refuses to load anything until `useSession` has named a
// session, and on a phone `useFileTree` is not mounted, so nothing else will.
// Relying on the desktop tree to have bound it first is what left a fresh
// session on a phone with a breadcrumb and an empty list, no request sent.
// Binding is idempotent for the same id, so a width change that swaps this
// component for the tree keeps the cache; a different id, or none, wipes it.

import { computed, onScopeDispose, ref, watch, type Ref } from "vue";

import type { FileEntry } from "../api/dto";
import { ROOT_PATH, useFilesStore, type DirState } from "../stores/files";

export interface Crumb {
  /** Workspace-relative path this crumb navigates to. */
  path: string;
  /** Folder name, never a path. The root's label comes from the caller. */
  label: string;
}

/**
 * Where the user was when they opened a file, so a phone can bring them back
 * to it (plan/29 MS-16, plan/31/05 BP-06 §0). In memory only: a
 * workspace-relative path must never reach the URL or history state.
 */
export interface BrowserPlace {
  /** The folder on screen. Ignored while a search is showing. */
  cwd: string;
  /** The list's own scroll offset. */
  scrollTop: number;
  /** The row (or search hit) that opened the preview; focus returns to it. */
  focus: string;
}

export interface FileBrowserOptions {
  sessionId: Ref<string | null>;
  /** Folder name for the workspace root, not a full path (ADR 0014). */
  rootLabel: Ref<string>;
  /**
   * False when the role lacks file.browse *or* the session can no longer be
   * browsed (ended). Either way nothing is bound and nothing is requested.
   */
  canBrowse: Ref<boolean>;
}

export function useFileBrowser(options: FileBrowserOptions) {
  const store = useFilesStore();
  const cwd = ref(ROOT_PATH);

  // The one session the store may hold data for, or none. Losing permission
  // or the session ending unbinds, which wipes, so no listing outlives the
  // right to see it.
  const boundId = computed(() =>
    options.canBrowse.value ? options.sessionId.value : null,
  );

  // Bind, then load — in one watcher, so the order cannot depend on how two
  // watchers happen to be scheduled.
  //
  // A binding change resets the location as well as the data. The store wipes
  // its own contents; if `cwd` survived, the new session would open on a path
  // that belonged to the old one — which is the one thing a
  // workspace-relative path must never do.
  watch(
    [boundId, cwd],
    ([sessionId, path], previous) => {
      // On the immediate first run `previous` holds no id, so this binds too.
      if (sessionId !== previous?.[0]) {
        store.useSession(sessionId);
        if (path !== ROOT_PATH) {
          // Re-enters this watcher with the same id and the root path.
          cwd.value = ROOT_PATH;
          return;
        }
      }
      if (sessionId) void store.loadDir(path);
    },
    { immediate: true },
  );

  // Leaving the view (mode switch, preview, width change) cancels this
  // browser's in-flight listings; the binding and the cache stay, so coming
  // back to the same session is served from cache. Same contract as
  // `useFileTree`, and it runs before a sibling mounts in the same patch, so it
  // cannot cancel the sibling's own requests.
  onScopeDispose(() => store.abortInflight());

  /** True while bound to a session that may be browsed. */
  const bound = computed(() => boundId.value !== null);

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

  /** Re-read the current level; also the retry after a failed load. */
  function refresh(): void {
    if (!bound.value) return;
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
    bound,
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
