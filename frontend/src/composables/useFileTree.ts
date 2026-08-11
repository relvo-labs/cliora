// File tree interaction state for one session (P3-07).
//
// The composable owns expansion, focus and selection; the files store owns the
// per-directory cache and the in-flight requests. Focus and selection are
// deliberately separate: moving focus with the arrow keys must never fetch a
// file preview, only Enter/Space (or a click) opens one.
//
// Rows carry `rel_path` only. The workspace root is rendered from a caller-
// supplied label (the workspace folder name), never a server absolute path.

import { computed, onScopeDispose, ref, watch, type Ref } from "vue";

import type { FileEntry, FileEntryType } from "../api/dto";
import { ROOT_PATH, useFilesStore, type DirState } from "../stores/files";

export type TreeRowKind = "root" | "entry" | "status" | "more";

export interface TreeRow {
  kind: TreeRowKind;
  // rel_path for entries, "." for the root row, synthetic for status/more rows.
  key: string;
  name: string;
  level: number;
  type: FileEntryType | "root";
  entry?: FileEntry;
  expandable: boolean;
  expanded: boolean;
  // A directory row whose children are being fetched (aria-busy).
  busy: boolean;
  // Only on status rows: which contract state to render.
  state?: DirState;
  message?: string;
  // Only on status/more rows: the directory they belong to.
  parent?: string;
}

export interface FileTreeOptions {
  // Reactive session id; a change rebinds the cache and clears the tree.
  sessionId: Ref<string | null>;
  // Display label for the workspace root row (folder name, not a full path).
  rootLabel: Ref<string>;
  // Called when the user activates a file row (Enter/Space/click).
  onOpen?: (relPath: string, entry: FileEntry) => void;
  // Called when a file row's selection is cleared (e.g. session switch).
  onClear?: () => void;
}

// Segment-wise ancestors of a rel_path, outermost first: "a/b/c.py" →
// [".", "a", "a/b"]. Used to reveal a search hit inside the tree.
export function ancestorsOf(relPath: string): string[] {
  const parts = relPath.split("/").filter((p) => p && p !== ".");
  const out = [ROOT_PATH];
  for (let i = 0; i < parts.length - 1; i += 1) {
    out.push(parts.slice(0, i + 1).join("/"));
  }
  return out;
}

// How often an auto-refreshing tree re-reads its expanded levels. Slow enough
// that an idle session costs a node almost nothing, quick enough that a file a
// CLI just wrote shows up without the user reaching for refresh.
export const AUTO_REFRESH_MS = 10_000;

export function useFileTree(options: FileTreeOptions) {
  const store = useFilesStore();
  const expanded = ref(new Set<string>([ROOT_PATH]));
  const focusedKey = ref<string>(ROOT_PATH);
  const selectedKey = ref<string | null>(null);
  const revealing = ref(false);

  function bind(sessionId: string | null): void {
    store.useSession(sessionId);
    expanded.value = new Set<string>([ROOT_PATH]);
    focusedKey.value = ROOT_PATH;
    if (selectedKey.value !== null) {
      selectedKey.value = null;
      options.onClear?.();
    }
    if (sessionId) {
      void store.loadDir(ROOT_PATH);
    }
  }

  // Switching session (or losing it) wipes the tree: an entry from the previous
  // node must never stay on screen.
  watch(options.sessionId, (next) => bind(next), { immediate: true });

  const rootState = computed<DirState>(
    () => store.dirs[ROOT_PATH]?.state ?? "idle",
  );
  const rootMessage = computed(() => store.dirs[ROOT_PATH]?.message);

  // Flatten the expanded cache into the visible row list. Synthetic status/more
  // rows follow the directory they describe so the state contract is visible at
  // the level it applies to.
  const rows = computed<TreeRow[]>(() => {
    const out: TreeRow[] = [];
    const rootNode = store.dirs[ROOT_PATH];
    out.push({
      kind: "root",
      key: ROOT_PATH,
      name: options.rootLabel.value || "workspace",
      level: 1,
      type: "root",
      expandable: true,
      expanded: expanded.value.has(ROOT_PATH),
      busy: rootNode?.state === "loading",
    });
    if (expanded.value.has(ROOT_PATH)) {
      pushLevel(out, ROOT_PATH, 2);
    }
    return out;
  });

  function pushLevel(out: TreeRow[], dirPath: string, level: number): void {
    const node = store.dirs[dirPath];
    if (!node) {
      return;
    }
    if (node.state === "loading" && node.entries.length === 0) {
      out.push(statusRow(dirPath, level, "loading", "Loading…"));
      return;
    }
    if (
      node.state === "empty" ||
      node.state === "error" ||
      node.state === "forbidden" ||
      node.state === "offline"
    ) {
      out.push(statusRow(dirPath, level, node.state, node.message));
      if (node.entries.length === 0) {
        return;
      }
    }
    for (const entry of node.entries) {
      const isDir = entry.type === "directory";
      const childNode = store.dirs[entry.rel_path];
      out.push({
        kind: "entry",
        key: entry.rel_path,
        name: entry.name,
        level,
        type: entry.type,
        entry,
        expandable: isDir && entry.expandable,
        expanded: expanded.value.has(entry.rel_path),
        busy: childNode?.state === "loading",
      });
      if (isDir && entry.expandable && expanded.value.has(entry.rel_path)) {
        pushLevel(out, entry.rel_path, level + 1);
      }
    }
    if (node.truncated && node.nextCursor) {
      out.push({
        kind: "more",
        key: `${dirPath}::more`,
        name: "Load more entries",
        level,
        type: "root",
        expandable: false,
        expanded: false,
        busy: node.state === "loading",
        parent: dirPath,
        state: "partial",
      });
    }
  }

  function statusRow(
    dirPath: string,
    level: number,
    state: DirState,
    message?: string,
  ): TreeRow {
    return {
      kind: "status",
      key: `${dirPath}::${state}`,
      name: message ?? state,
      level,
      type: "root",
      expandable: false,
      expanded: false,
      busy: state === "loading",
      state,
      message,
      parent: dirPath,
    };
  }

  // Only real tree items take focus; status and "load more" rows do not.
  const focusableRows = computed(() =>
    rows.value.filter((row) => row.kind === "root" || row.kind === "entry"),
  );

  function focusIndex(): number {
    const index = focusableRows.value.findIndex(
      (row) => row.key === focusedKey.value,
    );
    return index >= 0 ? index : 0;
  }

  function focusAt(index: number): void {
    const list = focusableRows.value;
    if (list.length === 0) {
      return;
    }
    const clamped = Math.min(Math.max(index, 0), list.length - 1);
    focusedKey.value = list[clamped].key;
  }

  async function expand(key: string): Promise<void> {
    expanded.value.add(key);
    await store.loadDir(key);
  }

  function collapse(key: string): void {
    expanded.value.delete(key);
  }

  async function toggle(row: TreeRow): Promise<void> {
    if (!row.expandable) {
      return;
    }
    if (expanded.value.has(row.key)) {
      collapse(row.key);
    } else {
      await expand(row.key);
    }
  }

  // Activate: directories toggle, files open the preview. This is the only path
  // that fetches file content.
  async function activate(row: TreeRow): Promise<void> {
    focusedKey.value = row.key;
    if (row.kind === "more" && row.parent) {
      await store.loadMore(row.parent);
      return;
    }
    if (row.expandable || row.kind === "root") {
      await toggle(row);
      return;
    }
    if (row.kind === "entry" && row.entry && row.entry.type !== "directory") {
      selectedKey.value = row.key;
      options.onOpen?.(row.key, row.entry);
    }
  }

  async function onKeydown(event: KeyboardEvent): Promise<void> {
    const list = focusableRows.value;
    const index = focusIndex();
    const row = list[index];
    switch (event.key) {
      case "ArrowDown":
        event.preventDefault();
        focusAt(index + 1);
        return;
      case "ArrowUp":
        event.preventDefault();
        focusAt(index - 1);
        return;
      case "Home":
        event.preventDefault();
        focusAt(0);
        return;
      case "End":
        event.preventDefault();
        focusAt(list.length - 1);
        return;
      case "ArrowRight":
        event.preventDefault();
        if (!row) return;
        if (row.expandable && !expanded.value.has(row.key)) {
          await expand(row.key);
        } else if (row.expandable) {
          focusAt(index + 1);
        }
        return;
      case "ArrowLeft": {
        event.preventDefault();
        if (!row) return;
        if (row.expandable && expanded.value.has(row.key)) {
          collapse(row.key);
          return;
        }
        const parentKey = ancestorsOf(row.key).pop() ?? ROOT_PATH;
        const parentIndex = list.findIndex(
          (candidate) => candidate.key === parentKey,
        );
        if (parentIndex >= 0) {
          focusAt(parentIndex);
        }
        return;
      }
      case "Enter":
      case " ":
        event.preventDefault();
        if (row) {
          await activate(row);
        }
        return;
      default:
        return;
    }
  }

  // The directory a drop on `row` would land in (ADR 0026, FU-06).
  //
  // Dropping on a *file* targets its parent, because "put this next to that file"
  // is what the gesture means — and requiring a precise hit on a folder row would
  // make the feature tedious. The row shows the resolved destination while
  // dragging, so nothing is guessed silently.
  //
  // Returns null for rows that cannot take a drop: an excluded directory (its
  // contents are tool-owned, and the node would refuse anyway), and the synthetic
  // status / "load more" rows. Those must not highlight either — refusing after the
  // drop is worse than not offering it.
  function dropTargetFor(row: TreeRow): string | null {
    if (row.kind === "root") {
      return ROOT_PATH;
    }
    if (row.kind !== "entry" || !row.entry) {
      return null;
    }
    if (row.entry.type === "directory") {
      return row.entry.excluded ? null : row.key;
    }
    // A file or a symlink: its parent. `ancestorsOf` already returns the chain
    // outermost-first, so the last element is the immediate parent.
    return ancestorsOf(row.key).pop() ?? ROOT_PATH;
  }

  // Bring a path (usually a search hit) into the tree: expand every ancestor in
  // order — each level must load before the next path segment is known to the
  // cache — then focus and open it.
  async function reveal(relPath: string): Promise<void> {
    revealing.value = true;
    try {
      for (const ancestor of ancestorsOf(relPath)) {
        expanded.value.add(ancestor);
        await store.loadDir(ancestor);
      }
      focusedKey.value = relPath;
      const parent = ancestorsOf(relPath).pop() ?? ROOT_PATH;
      const entry = store.dirs[parent]?.entries.find(
        (e) => e.rel_path === relPath,
      );
      if (entry && entry.type !== "directory") {
        selectedKey.value = relPath;
        options.onOpen?.(relPath, entry);
      }
    } finally {
      revealing.value = false;
    }
  }

  async function refresh(dirPath?: string): Promise<void> {
    const target = dirPath ?? currentDir();
    await store.refreshDir(target);
  }

  // --- Auto-refresh while a session runs (FR-FILE-006) -------------------
  //
  // Opt-in, like the dashboard's. A running CLI writes files, and re-expanding
  // every level by hand to notice is the tedium this removes; but a tree that
  // refetches on its own by default would put steady load on every node for the
  // majority of sessions where nothing changes.

  const autoRefresh = ref(false);
  let timer: ReturnType<typeof setInterval> | null = null;
  // One pass at a time: on a slow node the interval would otherwise stack passes
  // until the tree is refetching continuously.
  let passInFlight = false;

  async function refreshExpanded(): Promise<void> {
    if (passInFlight || revealing.value || !options.sessionId.value) {
      return;
    }
    passInFlight = true;
    try {
      // Snapshot first: expanding or collapsing mid-pass must not change what
      // this pass walks.
      for (const dirPath of [...expanded.value]) {
        if (!autoRefresh.value || !options.sessionId.value) {
          return;
        }
        await store.refreshDir(dirPath);
      }
    } finally {
      passInFlight = false;
    }
  }

  function stopAutoRefresh(): void {
    if (timer !== null) {
      clearInterval(timer);
      timer = null;
    }
  }

  function setAutoRefresh(enabled: boolean): void {
    autoRefresh.value = enabled;
    stopAutoRefresh();
    if (!enabled || !options.sessionId.value) {
      return;
    }
    timer = setInterval(() => void refreshExpanded(), AUTO_REFRESH_MS);
  }

  // Losing the session stops the timer but keeps the preference, so it resumes
  // on the next session rather than silently staying off.
  watch(options.sessionId, (next) => {
    stopAutoRefresh();
    if (autoRefresh.value && next) {
      timer = setInterval(() => void refreshExpanded(), AUTO_REFRESH_MS);
    }
  });

  onScopeDispose(stopAutoRefresh);

  // The directory the focused row lives in — the target of "refresh this level".
  function currentDir(): string {
    const row = focusableRows.value.find(
      (candidate) => candidate.key === focusedKey.value,
    );
    if (!row) {
      return ROOT_PATH;
    }
    if (row.kind === "root") {
      return ROOT_PATH;
    }
    if (row.entry?.type === "directory" && expanded.value.has(row.key)) {
      return row.key;
    }
    return ancestorsOf(row.key).pop() ?? ROOT_PATH;
  }

  // Leaving the view cancels in-flight expands/searches; the cache itself stays
  // so returning to the same session is cheap.
  onScopeDispose(() => store.abortInflight());

  return {
    rows,
    focusableRows,
    rootState,
    rootMessage,
    focusedKey,
    selectedKey,
    revealing,
    expanded,
    activate,
    toggle,
    expand,
    collapse,
    onKeydown,
    reveal,
    refresh,
    dropTargetFor,
    autoRefresh,
    setAutoRefresh,
    refreshExpanded,
    currentDir,
    search: (keyword: string) => store.runSearch(keyword),
    clearSearch: () => store.clearSearch(),
    searchSlice: computed(() => store.search),
  };
}
