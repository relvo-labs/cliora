// Workspace file cache for one session (P3-07). The store owns the per-directory
// listing cache, the search result, and the AbortController of every in-flight
// request; `useFileTree` owns the interaction state on top of it.
//
// Two invariants matter here:
//   * the cache is keyed to exactly one session id — switching session (or the
//     session reaching a terminal state) wipes it, so a path from a previous
//     node can never be rendered;
//   * nothing but a workspace-relative `rel_path` is ever stored, so no server
//     absolute path can reach the UI or a log line.

import { defineStore } from "pinia";

import { ApiError, isAbortError } from "../api/client";
import type {
  FileEntry,
  FileSearchHit,
  FileSearchStopReason,
} from "../api/dto";
import { api } from "./auth";

// The UI state contract (style.md) as it applies to one directory level.
// "partial" means the daemon truncated the listing and handed back a cursor.
export type DirState =
  | "idle"
  | "loading"
  | "success"
  | "empty"
  | "partial"
  | "offline"
  | "forbidden"
  | "error";

export type SearchState =
  | "idle"
  | "loading"
  | "success"
  | "empty"
  | "partial"
  | "offline"
  | "forbidden"
  | "error";

export interface DirNode {
  // Workspace-relative directory path; "." is the workspace root.
  path: string;
  entries: FileEntry[];
  state: DirState;
  // The daemon capped the response; `nextCursor` loads the following page.
  truncated: boolean;
  nextCursor?: string;
  message?: string;
}

export interface SearchSlice {
  keyword: string;
  state: SearchState;
  results: FileSearchHit[];
  partial: boolean;
  stoppedReason?: FileSearchStopReason;
  scanned: number;
  message?: string;
}

interface FilesState {
  sessionId: string | null;
  dirs: Record<string, DirNode>;
  search: SearchSlice;
}

export const ROOT_PATH = ".";

function emptySearch(): SearchSlice {
  return {
    keyword: "",
    state: "idle",
    results: [],
    partial: false,
    scanned: 0,
  };
}

// In-flight controllers live outside the reactive state: they are plumbing, not
// data, and must never be serialized or observed.
const inflight = new Map<string, AbortController>();

function abort(key: string): void {
  inflight.get(key)?.abort();
  inflight.delete(key);
}

function abortAll(): void {
  for (const controller of inflight.values()) {
    controller.abort();
  }
  inflight.clear();
}

// Map a relay failure onto the state contract. A 403 is RBAC (no file.browse),
// NODE_OFFLINE means the daemon is not connected; everything else is a generic
// error carrying the safe server message only.
function classify(error: unknown): {
  state: "offline" | "forbidden" | "error";
  message: string;
} {
  if (error instanceof ApiError) {
    if (error.status === 403) {
      return {
        state: "forbidden",
        message: "You do not have permission to browse files.",
      };
    }
    if (error.code === "NODE_OFFLINE") {
      return {
        state: "offline",
        message: "The node is offline; the file tree is unavailable.",
      };
    }
    return { state: "error", message: error.message };
  }
  return { state: "error", message: "Could not reach Central." };
}

export const useFilesStore = defineStore("files", {
  state: (): FilesState => ({
    sessionId: null,
    dirs: {},
    search: emptySearch(),
  }),
  getters: {
    dir(state) {
      return (path: string): DirNode | undefined => state.dirs[path];
    },
  },
  actions: {
    // Bind the cache to a session. A different id (or null) drops everything and
    // aborts in-flight work, so no response for the old session can land.
    useSession(sessionId: string | null): void {
      if (this.sessionId === sessionId) {
        return;
      }
      abortAll();
      this.sessionId = sessionId;
      this.dirs = {};
      this.search = emptySearch();
    },

    clearForSession(sessionId: string | null): void {
      if (sessionId !== null && this.sessionId !== sessionId) {
        return;
      }
      abortAll();
      this.sessionId = null;
      this.dirs = {};
      this.search = emptySearch();
    },

    // Load one directory level. Returns immediately from cache unless `force`
    // (refresh) or a cursor (next page) is given.
    async loadDir(
      path: string,
      options: { force?: boolean; cursor?: string } = {},
    ): Promise<DirNode | undefined> {
      const sessionId = this.sessionId;
      if (!sessionId) {
        return undefined;
      }
      const cached = this.dirs[path];
      const appending = Boolean(options.cursor);
      if (
        cached &&
        !options.force &&
        !appending &&
        (cached.state === "success" ||
          cached.state === "partial" ||
          cached.state === "empty")
      ) {
        return cached;
      }

      abort(path);
      const controller = new AbortController();
      inflight.set(path, controller);

      this.dirs[path] = {
        path,
        entries: appending ? (cached?.entries ?? []) : [],
        state: "loading",
        truncated: false,
        nextCursor: undefined,
      };

      try {
        const page = await api().listFileTree(
          sessionId,
          { path, cursor: options.cursor },
          { signal: controller.signal },
        );
        // A late response for a session we no longer show is dropped.
        if (this.sessionId !== sessionId) {
          return undefined;
        }
        const entries = appending
          ? [...(cached?.entries ?? []), ...page.entries]
          : page.entries;
        const node: DirNode = {
          path,
          entries,
          state: page.truncated
            ? "partial"
            : entries.length === 0
              ? "empty"
              : "success",
          truncated: page.truncated,
          nextCursor: page.next_cursor,
        };
        this.dirs[path] = node;
        return node;
      } catch (caught) {
        if (isAbortError(caught)) {
          // Superseded or cancelled: leave no error state behind.
          if (this.dirs[path]?.state === "loading") {
            delete this.dirs[path];
          }
          return undefined;
        }
        if (this.sessionId !== sessionId) {
          return undefined;
        }
        const { state, message } = classify(caught);
        this.dirs[path] = {
          path,
          entries: appending ? (cached?.entries ?? []) : [],
          state,
          truncated: false,
          message,
        };
        return this.dirs[path];
      } finally {
        if (inflight.get(path) === controller) {
          inflight.delete(path);
        }
      }
    },

    // Drop this level's cache and re-fetch it (FR-FILE-006 manual refresh).
    async refreshDir(path: string): Promise<DirNode | undefined> {
      return this.loadDir(path, { force: true });
    },

    async loadMore(path: string): Promise<DirNode | undefined> {
      const cursor = this.dirs[path]?.nextCursor;
      if (!cursor) {
        return this.dirs[path];
      }
      return this.loadDir(path, { cursor });
    },

    // Filename search. A new keyword aborts the previous walk (the daemon's own
    // bounds still apply); an empty keyword just clears the slice. Named
    // `runSearch` because `search` is the state slice it writes into.
    async runSearch(keyword: string, root?: string): Promise<void> {
      const sessionId = this.sessionId;
      abort("__search__");
      if (!sessionId || !keyword.trim()) {
        this.search = emptySearch();
        return;
      }
      const controller = new AbortController();
      inflight.set("__search__", controller);
      this.search = { ...emptySearch(), keyword, state: "loading" };
      try {
        const result = await api().searchFiles(
          sessionId,
          { keyword, root },
          { signal: controller.signal },
        );
        if (this.sessionId !== sessionId) {
          return;
        }
        this.search = {
          keyword,
          state: result.partial
            ? "partial"
            : result.results.length === 0
              ? "empty"
              : "success",
          results: result.results,
          partial: result.partial,
          stoppedReason: result.stopped_reason,
          scanned: result.scanned_count,
        };
      } catch (caught) {
        if (isAbortError(caught)) {
          return;
        }
        if (this.sessionId !== sessionId) {
          return;
        }
        const { state, message } = classify(caught);
        this.search = { ...emptySearch(), keyword, state, message };
      } finally {
        if (inflight.get("__search__") === controller) {
          inflight.delete("__search__");
        }
      }
    },

    clearSearch(): void {
      abort("__search__");
      this.search = emptySearch();
    },

    // Abort every in-flight request without dropping the cache (view unmount).
    abortInflight(): void {
      abortAll();
    },
  },
});

// Test seam: how many requests are still in flight. Used by the leak gates to
// prove nothing is left running after a session switch or unmount.
export function inflightCount(): number {
  return inflight.size;
}
