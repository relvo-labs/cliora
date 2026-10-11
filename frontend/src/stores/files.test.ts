import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { FileTreePage, FileSearchResult } from "../api/dto";
import * as auth from "./auth";
import { useFilesStore, inflightCount } from "./files";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((r, j) => {
    resolve = r;
    reject = j;
  });
  return { promise, resolve, reject };
}
const entry = (name: string) => ({
  name,
  rel_path: name,
  type: "file" as const,
  modified_at: "2026-10-11T00:00:00Z",
  size: 1,
  hidden: false,
  symlink: false,
  excluded: false,
  expandable: false,
});
const page = (name: string): FileTreePage => ({
  path: ".",
  truncated: false,
  entries: [entry(name)],
});
const result = (name: string): FileSearchResult => ({
  results: [entry(name)],
  partial: false,
  scanned_count: 1,
});
beforeEach(() => {
  setActivePinia(createPinia());
  useFilesStore().useSession("A");
});
afterEach(() => {
  useFilesStore().clearForSession(null);
  vi.restoreAllMocks();
});

describe("#79 file request identity", () => {
  it.each(["success", "error", "abort"])(
    "an old listing's late %s cannot replace a newer listing",
    async (outcome) => {
      const old = deferred<FileTreePage>();
      vi.spyOn(auth, "api").mockReturnValue({
        listFileTree: vi
          .fn()
          .mockReturnValueOnce(old.promise)
          .mockResolvedValueOnce(page("new")),
      } as never);
      const store = useFilesStore();
      const first = store.loadDir(".");
      await store.refreshDir(".");
      if (outcome === "success") old.resolve(page("old"));
      else
        old.reject(
          outcome === "abort"
            ? new DOMException("aborted", "AbortError")
            : new Error("old failure"),
        );
      await first;
      expect(store.dirs["."].state).toBe("success");
      expect(store.dirs["."].entries[0].name).toBe("new");
    },
  );

  it("an old abort cannot delete the newer loading entry or its controller", async () => {
    const old = deferred<FileTreePage>();
    const latest = deferred<FileTreePage>();
    vi.spyOn(auth, "api").mockReturnValue({
      listFileTree: vi
        .fn()
        .mockReturnValueOnce(old.promise)
        .mockReturnValueOnce(latest.promise),
    } as never);
    const store = useFilesStore();
    const first = store.loadDir(".");
    const second = store.refreshDir(".");
    old.reject(new DOMException("aborted", "AbortError"));
    await first;
    expect(store.dirs["."].state).toBe("loading");
    expect(inflightCount()).toBe(1);
    latest.resolve(page("new"));
    await second;
    expect(store.dirs["."].entries[0].name).toBe("new");
    expect(inflightCount()).toBe(0);
  });

  it.each(["success", "error", "abort"])(
    "an old search's late %s cannot settle the newer search",
    async (outcome) => {
      const old = deferred<FileSearchResult>();
      const latest = deferred<FileSearchResult>();
      vi.spyOn(auth, "api").mockReturnValue({
        searchFiles: vi
          .fn()
          .mockReturnValueOnce(old.promise)
          .mockReturnValueOnce(latest.promise),
      } as never);
      const store = useFilesStore();
      const first = store.runSearch("old");
      const second = store.runSearch("new");
      if (outcome === "success") old.resolve(result("old"));
      else
        old.reject(
          outcome === "abort"
            ? new DOMException("aborted", "AbortError")
            : new Error("old failure"),
        );
      await first;
      expect(store.search.state).toBe("loading");
      expect(store.search.keyword).toBe("new");
      expect(inflightCount()).toBe(1);
      latest.resolve(result("new"));
      await second;
      expect(store.search.results[0].name).toBe("new");
    },
  );

  it.each(["success", "abort"])(
    "A → B → A rejects the first A listing's %s",
    async (outcome) => {
      const old = deferred<FileTreePage>();
      vi.spyOn(auth, "api").mockReturnValue({
        listFileTree: vi
          .fn()
          .mockReturnValueOnce(old.promise)
          .mockResolvedValueOnce(page("new")),
      } as never);
      const store = useFilesStore();
      const first = store.loadDir(".");
      store.useSession("B");
      store.useSession("A");
      await store.loadDir(".");
      if (outcome === "success") old.resolve(page("old"));
      else old.reject(new DOMException("aborted", "AbortError"));
      await first;
      expect(store.dirs["."].entries[0].name).toBe("new");
    },
  );
});

describe("#80 cancelled search settles", () => {
  it.each(["abort", "success", "error"])(
    "abortInflight immediately leaves loading and ignores late %s",
    async (outcome) => {
      const held = deferred<FileSearchResult>();
      vi.spyOn(auth, "api").mockReturnValue({
        searchFiles: () => held.promise,
      } as never);
      const store = useFilesStore();
      const pending = store.runSearch("needle");
      store.abortInflight();
      expect(store.search.state).toBe("idle");
      expect(store.search.keyword).toBe("needle");
      expect(inflightCount()).toBe(0);
      if (outcome === "success") held.resolve(result("needle"));
      else
        held.reject(
          outcome === "abort"
            ? new DOMException("aborted", "AbortError")
            : new Error("late failure"),
        );
      await pending;
      expect(store.search.state).toBe("idle");
    },
  );

  it("a current search AbortError settles without an error or permanent loading", async () => {
    vi.spyOn(auth, "api").mockReturnValue({
      searchFiles: async () => {
        throw new DOMException("aborted", "AbortError");
      },
    } as never);
    const store = useFilesStore();
    await store.runSearch("needle");
    expect(store.search.state).toBe("idle");
    expect(store.search.keyword).toBe("needle");
  });
});
