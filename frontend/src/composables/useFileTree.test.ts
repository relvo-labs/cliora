import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { effectScope, nextTick, ref } from "vue";

import { ApiError } from "../api/client";
import type { FileEntry, FileSearchResult, FileTreePage } from "../api/dto";

// --- fake Central: records every filesystem call the tree makes ---
const { calls, listImpl, searchImpl } = vi.hoisted(() => ({
  calls: [] as Array<{
    op: string;
    path?: string;
    cursor?: string;
    keyword?: string;
  }>,
  listImpl: {
    fn: null as
      | null
      | ((path: string, cursor?: string) => Promise<FileTreePage>),
  },
  searchImpl: {
    fn: null as null | ((keyword: string) => Promise<FileSearchResult>),
  },
}));

vi.mock("../stores/auth", () => ({
  api: () => ({
    listFileTree: (
      _sessionId: string,
      params: { path?: string; cursor?: string },
      options?: { signal?: AbortSignal },
    ) => {
      calls.push({ op: "list", path: params.path, cursor: params.cursor });
      const promise = listImpl.fn!(params.path ?? ".", params.cursor);
      return abortable(promise, options?.signal);
    },
    searchFiles: (
      _sessionId: string,
      params: { keyword: string },
      options?: { signal?: AbortSignal },
    ) => {
      calls.push({ op: "search", keyword: params.keyword });
      return abortable(searchImpl.fn!(params.keyword), options?.signal);
    },
  }),
}));

// Reject with a DOMException("AbortError") when the caller's signal fires, the
// way fetch does — the store must treat that as "superseded", not as an error.
function abortable<T>(promise: Promise<T>, signal?: AbortSignal): Promise<T> {
  if (!signal) {
    return promise;
  }
  return new Promise<T>((resolve, reject) => {
    if (signal.aborted) {
      reject(new DOMException("aborted", "AbortError"));
      return;
    }
    signal.addEventListener("abort", () =>
      reject(new DOMException("aborted", "AbortError")),
    );
    promise.then(resolve, reject);
  });
}

import { AUTO_REFRESH_MS, useFileTree, ancestorsOf } from "./useFileTree";
import { ROOT_PATH, inflightCount, useFilesStore } from "../stores/files";

function entry(
  over: Partial<FileEntry> & { name: string; rel_path: string },
): FileEntry {
  return {
    type: "file",
    size: 10,
    modified_at: "2026-07-25T00:00:00Z",
    hidden: false,
    symlink: false,
    excluded: false,
    expandable: false,
    ...over,
  };
}

function dir(
  name: string,
  relPath: string,
  over: Partial<FileEntry> = {},
): FileEntry {
  return entry({
    name,
    rel_path: relPath,
    type: "directory",
    expandable: true,
    ...over,
  });
}

function page(
  path: string,
  entries: FileEntry[],
  over: Partial<FileTreePage> = {},
): FileTreePage {
  return { path, entries, truncated: false, ...over };
}

// Standard fixture workspace: src/ (with main.py), README.md, node_modules/ (excluded).
function standardTree(): void {
  listImpl.fn = async (path) => {
    if (path === ".") {
      return page(".", [
        dir("src", "src"),
        dir("node_modules", "node_modules", {
          excluded: true,
          expandable: false,
        }),
        entry({ name: "README.md", rel_path: "README.md" }),
      ]);
    }
    if (path === "src") {
      return page("src", [
        dir("app", "src/app"),
        entry({ name: "main.py", rel_path: "src/main.py" }),
      ]);
    }
    if (path === "src/app") {
      return page("src/app", [
        entry({ name: "cli.py", rel_path: "src/app/cli.py" }),
      ]);
    }
    return page(path, []);
  };
}

let scope: ReturnType<typeof effectScope>;

function mountTree(
  sessionId = "s1",
  onOpen?: (p: string) => void,
  onClear?: () => void,
) {
  const id = ref<string | null>(sessionId);
  const label = ref("app");
  let tree!: ReturnType<typeof useFileTree>;
  scope = effectScope();
  scope.run(() => {
    tree = useFileTree({
      sessionId: id,
      rootLabel: label,
      onOpen: (relPath) => onOpen?.(relPath),
      onClear,
    });
  });
  return { tree, id };
}

// Let queued microtasks (the awaited fetches) settle.
const settle = async (): Promise<void> => {
  for (let i = 0; i < 6; i += 1) {
    await Promise.resolve();
    await nextTick();
  }
};

describe("useFileTree", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    calls.length = 0;
    standardTree();
    searchImpl.fn = async () => ({
      results: [],
      partial: false,
      scanned_count: 0,
    });
  });

  afterEach(() => {
    scope?.stop();
  });

  it("loads only the root level on bind (lazy)", async () => {
    const { tree } = mountTree();
    await settle();
    expect(calls).toEqual([{ op: "list", path: ".", cursor: undefined }]);
    expect(tree.rows.value.map((r) => r.name)).toEqual([
      "app",
      "src",
      "node_modules",
      "README.md",
    ]);
  });

  it("fetches a child level on expand and reuses the cache on re-expand", async () => {
    const { tree } = mountTree();
    await settle();
    const src = tree.rows.value.find((r) => r.key === "src")!;

    await tree.activate(src);
    await settle();
    expect(calls.filter((c) => c.path === "src")).toHaveLength(1);
    expect(tree.rows.value.map((r) => r.key)).toContain("src/main.py");

    // Collapse then expand again: served from cache, no second request.
    await tree.activate(tree.rows.value.find((r) => r.key === "src")!);
    await settle();
    await tree.activate(tree.rows.value.find((r) => r.key === "src")!);
    await settle();
    expect(calls.filter((c) => c.path === "src")).toHaveLength(1);
  });

  it("refresh discards the cached level and refetches it", async () => {
    const { tree } = mountTree();
    await settle();
    await tree.refresh(ROOT_PATH);
    await settle();
    expect(calls.filter((c) => c.path === ".")).toHaveLength(2);
  });

  it("marks an excluded directory as non-expandable", async () => {
    const { tree } = mountTree();
    await settle();
    const excluded = tree.rows.value.find((r) => r.key === "node_modules")!;
    expect(excluded.expandable).toBe(false);
    await tree.activate(excluded);
    await settle();
    // Activating it must not fetch anything.
    expect(calls.filter((c) => c.path === "node_modules")).toHaveLength(0);
  });

  it("renders the empty state for an empty folder", async () => {
    listImpl.fn = async (path) =>
      path === "." ? page(".", [dir("empty", "empty")]) : page(path, []);
    const { tree } = mountTree();
    await settle();
    await tree.activate(tree.rows.value.find((r) => r.key === "empty")!);
    await settle();
    const status = tree.rows.value.find((r) => r.kind === "status");
    expect(status?.state).toBe("empty");
  });

  it("surfaces forbidden when the role lacks file.browse", async () => {
    listImpl.fn = async () => {
      throw new ApiError("FORBIDDEN", "denied", 403);
    };
    const { tree } = mountTree();
    await settle();
    expect(tree.rootState.value).toBe("forbidden");
  });

  it("surfaces offline when the node is not connected", async () => {
    listImpl.fn = async () => {
      throw new ApiError("NODE_OFFLINE", "Node is not connected", 409);
    };
    const { tree } = mountTree();
    await settle();
    expect(tree.rootState.value).toBe("offline");
  });

  it("surfaces a safe error message and can retry", async () => {
    let fail = true;
    listImpl.fn = async (path) => {
      if (fail) {
        throw new ApiError(
          "INTERNAL_ERROR",
          "Node could not complete the request",
          502,
        );
      }
      return page(path, []);
    };
    const { tree } = mountTree();
    await settle();
    expect(tree.rootState.value).toBe("error");
    expect(tree.rootMessage.value).toBe("Node could not complete the request");
    fail = false;
    await tree.refresh(ROOT_PATH);
    await settle();
    expect(tree.rootState.value).toBe("empty");
  });

  it("shows a partial level and appends the next page with the cursor", async () => {
    listImpl.fn = async (path, cursor) => {
      if (path !== ".") return page(path, []);
      return cursor === "1"
        ? page(".", [entry({ name: "b.py", rel_path: "b.py" })])
        : page(".", [entry({ name: "a.py", rel_path: "a.py" })], {
            truncated: true,
            next_cursor: "1",
          });
    };
    const { tree } = mountTree();
    await settle();
    const more = tree.rows.value.find((r) => r.kind === "more");
    expect(more).toBeDefined();

    await tree.activate(more!);
    await settle();
    expect(tree.rows.value.map((r) => r.key)).toContain("b.py");
    expect(tree.rows.value.find((r) => r.kind === "more")).toBeUndefined();
  });

  it("reveals a search hit by expanding its ancestors and opening it", async () => {
    searchImpl.fn = async () => ({
      results: [
        {
          name: "cli.py",
          rel_path: "src/app/cli.py",
          type: "file",
          modified_at: "2026-07-25T00:00:00Z",
        },
      ],
      partial: true,
      stopped_reason: "results",
      scanned_count: 42,
    });
    const opened: string[] = [];
    const { tree } = mountTree("s1", (p) => opened.push(p));
    await settle();

    await tree.search("cli");
    await settle();
    expect(tree.searchSlice.value.state).toBe("partial");
    expect(tree.searchSlice.value.stoppedReason).toBe("results");

    await tree.reveal("src/app/cli.py");
    await settle();
    // Every ancestor level was loaded, and the hit is selected + opened.
    expect(calls.filter((c) => c.op === "list").map((c) => c.path)).toEqual([
      ".",
      "src",
      "src/app",
    ]);
    expect(tree.selectedKey.value).toBe("src/app/cli.py");
    expect(opened).toEqual(["src/app/cli.py"]);
  });

  it("clears the tree, the selection and the search when the session changes", async () => {
    let cleared = 0;
    const { tree, id } = mountTree("s1", undefined, () => {
      cleared += 1;
    });
    await settle();
    await tree.activate(tree.rows.value.find((r) => r.key === "src")!);
    await settle();
    await tree.search("cli");
    await settle();
    tree.selectedKey.value = "src/main.py";

    id.value = "s2";
    await settle();

    const store = useFilesStore();
    expect(cleared).toBe(1);
    expect(tree.selectedKey.value).toBeNull();
    expect(store.dirs["src"]).toBeUndefined();
    expect(store.search.keyword).toBe("");
    // The root of the *new* session is loaded; nothing of the old one remains.
    expect(tree.rows.value.filter((r) => r.kind === "entry").length).toBe(3);
  });

  it("aborts an in-flight expand when the session changes", async () => {
    // Held in an object so TypeScript does not narrow it to `null` (the
    // assignment happens inside the promise executor).
    const gate: { release: (() => void) | null } = { release: null };
    listImpl.fn = (path) =>
      new Promise<FileTreePage>((resolve) => {
        if (path === ".") {
          resolve(page(".", [dir("src", "src")]));
          return;
        }
        gate.release = () => resolve(page(path, []));
      });
    const { tree, id } = mountTree();
    await settle();
    void tree.activate(tree.rows.value.find((r) => r.key === "src")!);
    await settle();
    expect(inflightCount()).toBeGreaterThan(0);

    id.value = "s2";
    await settle();
    gate.release?.();
    await settle();

    const store = useFilesStore();
    expect(store.dirs["src"]).toBeUndefined();
  });

  it("leaves nothing in flight after the scope is disposed", async () => {
    const { tree } = mountTree();
    await settle();
    void tree.activate(tree.rows.value.find((r) => r.key === "src")!);
    scope.stop();
    await settle();
    expect(inflightCount()).toBe(0);
  });

  it("moves focus with the arrow keys without opening any file", async () => {
    const opened: string[] = [];
    const { tree } = mountTree("s1", (p) => opened.push(p));
    await settle();
    const before = calls.length;

    await tree.onKeydown(new KeyboardEvent("keydown", { key: "ArrowDown" }));
    expect(tree.focusedKey.value).toBe("src");
    await tree.onKeydown(new KeyboardEvent("keydown", { key: "ArrowDown" }));
    expect(tree.focusedKey.value).toBe("node_modules");
    await tree.onKeydown(new KeyboardEvent("keydown", { key: "End" }));
    expect(tree.focusedKey.value).toBe("README.md");
    await tree.onKeydown(new KeyboardEvent("keydown", { key: "Home" }));
    expect(tree.focusedKey.value).toBe(ROOT_PATH);

    // Focus movement is not selection: no content request, nothing opened.
    expect(calls.length).toBe(before);
    expect(opened).toEqual([]);
    expect(tree.selectedKey.value).toBeNull();
  });

  it("expands with ArrowRight, collapses with ArrowLeft, opens with Enter", async () => {
    const opened: string[] = [];
    const { tree } = mountTree("s1", (p) => opened.push(p));
    await settle();

    await tree.onKeydown(new KeyboardEvent("keydown", { key: "ArrowDown" }));
    await tree.onKeydown(new KeyboardEvent("keydown", { key: "ArrowRight" }));
    await settle();
    expect(tree.expanded.value.has("src")).toBe(true);

    await tree.onKeydown(new KeyboardEvent("keydown", { key: "ArrowLeft" }));
    expect(tree.expanded.value.has("src")).toBe(false);

    // Focus a file and press Enter: that (and only that) opens the preview.
    await tree.onKeydown(new KeyboardEvent("keydown", { key: "End" }));
    await tree.onKeydown(new KeyboardEvent("keydown", { key: "Enter" }));
    await settle();
    expect(opened).toEqual(["README.md"]);
    expect(tree.selectedKey.value).toBe("README.md");
  });

  it("ArrowLeft on a collapsed child moves focus to its parent", async () => {
    const { tree } = mountTree();
    await settle();
    await tree.activate(tree.rows.value.find((r) => r.key === "src")!);
    await settle();
    tree.focusedKey.value = "src/main.py";
    await tree.onKeydown(new KeyboardEvent("keydown", { key: "ArrowLeft" }));
    expect(tree.focusedKey.value).toBe("src");
  });

  // --- auto-refresh (FR-FILE-006) ---------------------------------------

  it("does not refetch anything on its own until asked", async () => {
    const { tree } = mountTree();
    await settle();
    calls.length = 0;

    vi.useFakeTimers();
    try {
      await vi.advanceTimersByTimeAsync(AUTO_REFRESH_MS * 3);
      expect(tree.autoRefresh.value).toBe(false);
      expect(calls).toEqual([]);
    } finally {
      vi.useRealTimers();
    }
  });

  it("re-reads every expanded level once auto-refresh is on", async () => {
    const { tree } = mountTree();
    await settle();
    await tree.expand("src");
    await settle();
    calls.length = 0;

    tree.setAutoRefresh(true);
    // Turning it on schedules the first pass; it does not fire immediately.
    expect(calls).toEqual([]);

    await tree.refreshExpanded();
    expect(calls.map((c) => c.path)).toEqual([".", "src"]);
  });

  it("stops re-reading when it is switched back off", async () => {
    const { tree } = mountTree();
    await settle();
    tree.setAutoRefresh(true);
    tree.setAutoRefresh(false);
    calls.length = 0;

    await tree.refreshExpanded();
    // The guard is the flag, not only the timer: a pass already queued when the
    // user unticks the box must not go on to fetch.
    expect(tree.autoRefresh.value).toBe(false);
    expect(calls.map((c) => c.path)).toEqual([]);
  });

  it("does not stack passes when a node answers slowly", async () => {
    const { tree } = mountTree();
    await settle();
    calls.length = 0;

    let release!: () => void;
    const blocked = new Promise<void>((resolve) => {
      release = resolve;
    });
    listImpl.fn = async (path) => {
      await blocked;
      return page(path, []);
    };

    tree.setAutoRefresh(true);
    const first = tree.refreshExpanded();
    const second = tree.refreshExpanded();
    await second; // returns straight away: a pass is already running
    expect(calls).toHaveLength(1);

    release();
    await first;
    expect(calls).toHaveLength(1);
  });

  it("leaves no timer behind when the scope is disposed", async () => {
    const { tree } = mountTree();
    await settle();
    tree.setAutoRefresh(true);

    vi.useFakeTimers();
    try {
      scope.stop();
      calls.length = 0;
      await vi.advanceTimersByTimeAsync(AUTO_REFRESH_MS * 3);
      expect(calls).toEqual([]);
      expect(inflightCount()).toBe(0);
    } finally {
      vi.useRealTimers();
    }
  });

  it("keeps the preference across a session change but never refreshes without one", async () => {
    const { tree, id } = mountTree();
    await settle();
    tree.setAutoRefresh(true);

    id.value = null;
    await settle();
    calls.length = 0;
    await tree.refreshExpanded();
    expect(calls).toEqual([]);
    // The box stays ticked, so the next session resumes rather than silently
    // dropping a preference the user set.
    expect(tree.autoRefresh.value).toBe(true);
  });

  it("derives ancestors segment by segment", () => {
    expect(ancestorsOf("a/b/c.py")).toEqual([".", "a", "a/b"]);
    expect(ancestorsOf("top.py")).toEqual(["."]);
    expect(ancestorsOf(".")).toEqual(["."]);
  });
});
