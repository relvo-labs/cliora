// Audit-trail query state (P4-05). The store owns the filter, the accumulated
// pages, and the AbortController of the one in-flight request.
//
// Three behaviours here exist because of how paged, filtered views go wrong:
//
//   * a new filter **replaces** the rows; appending would silently mix results
//     from two different questions;
//   * a response is dropped unless it belongs to the filter that is still
//     current, so a slow first query cannot overwrite a faster later one;
//   * a failure while loading a *further* page keeps the rows already shown and
//     reports `partial` — discarding them would punish the user for a transient
//     error on page three.

import { defineStore } from "pinia";

import { ApiError, isAbortError } from "../api/client";
import type { AuditItem, AuditQuery } from "../api/dto";
import { api } from "./auth";

export type AuditState =
  | "idle"
  | "loading"
  | "success"
  | "empty"
  | "partial"
  | "forbidden"
  | "error";

// What the user asked for. `range` is a preset the view turns into an absolute
// `from`; "custom" uses `from`/`to` verbatim.
export type AuditRange = "1h" | "24h" | "7d" | "custom";

export interface AuditFilter {
  actions: string[];
  userId: string;
  nodeId: string;
  sessionId: string;
  range: AuditRange;
  from: string;
  to: string;
}

interface AuditStoreState {
  filter: AuditFilter;
  items: AuditItem[];
  nextCursor: string | null;
  state: AuditState;
  message: string;
  requestId: string | null;
  // The rejection itself, so `ErrorNotice` can render the catalog's cause and next
  // step for its code. `message` and `requestId` stay because the `partial` and
  // `forbidden` states show their own wording rather than the generic panel.
  error: unknown;
  // True while a further page is being fetched, so the view can keep the loaded
  // rows visible instead of replacing them with a skeleton.
  loadingMore: boolean;
}

const RANGE_HOURS: Record<Exclude<AuditRange, "custom">, number> = {
  "1h": 1,
  "24h": 24,
  "7d": 24 * 7,
};

export function defaultFilter(): AuditFilter {
  return {
    actions: [],
    userId: "",
    nodeId: "",
    sessionId: "",
    range: "24h",
    from: "",
    to: "",
  };
}

// Serialize the filter for the query string so a view can be shared and reloaded.
export function filterToQuery(filter: AuditFilter): Record<string, string> {
  const query: Record<string, string> = { range: filter.range };
  if (filter.actions.length) query.action = filter.actions.join(",");
  if (filter.userId) query.user_id = filter.userId;
  if (filter.nodeId) query.node_id = filter.nodeId;
  if (filter.sessionId) query.session_id = filter.sessionId;
  if (filter.range === "custom") {
    if (filter.from) query.from = filter.from;
    if (filter.to) query.to = filter.to;
  }
  return query;
}

export function filterFromQuery(
  query: Record<string, string | string[] | undefined>,
): AuditFilter {
  const one = (key: string): string => {
    const value = query[key];
    return (Array.isArray(value) ? value[0] : value) ?? "";
  };
  // An unrecognized range falls back to the default rather than being passed on:
  // a hand-edited URL must not be able to widen the window.
  const known: AuditRange[] = ["1h", "24h", "7d", "custom"];
  const range = known.find((value) => value === one("range"));
  return {
    ...defaultFilter(),
    actions: one("action") ? one("action").split(",").filter(Boolean) : [],
    userId: one("user_id"),
    nodeId: one("node_id"),
    sessionId: one("session_id"),
    range: range ?? defaultFilter().range,
    from: one("from"),
    to: one("to"),
  };
}

// Turn the filter into wire parameters. A preset range is resolved to an absolute
// `from` here rather than server-side so the window the user sees is the window
// that was queried, even if the request is retried minutes later.
export function toWireQuery(filter: AuditFilter, now: Date): AuditQuery {
  const query: AuditQuery = {};
  if (filter.actions.length) query.action = [...filter.actions];
  if (filter.userId.trim()) query.user_id = filter.userId.trim();
  if (filter.nodeId.trim()) query.node_id = filter.nodeId.trim();
  if (filter.sessionId.trim()) query.session_id = filter.sessionId.trim();
  if (filter.range === "custom") {
    if (filter.from) query.from = new Date(filter.from).toISOString();
    if (filter.to) query.to = new Date(filter.to).toISOString();
  } else {
    query.from = new Date(
      now.getTime() - RANGE_HOURS[filter.range] * 3600_000,
    ).toISOString();
    query.to = now.toISOString();
  }
  return query;
}

// Plumbing, not data: kept out of the reactive state.
let inflight: AbortController | null = null;

function classify(error: unknown): {
  state: "forbidden" | "error";
  message: string;
  requestId: string | null;
} {
  if (error instanceof ApiError) {
    if (error.status === 403) {
      return {
        state: "forbidden",
        message: "只有 Admin 可以檢視 Audit Log。",
        requestId: error.requestId ?? null,
      };
    }
    return {
      state: "error",
      message: error.message,
      requestId: error.requestId ?? null,
    };
  }
  return {
    state: "error",
    message: "無法連線至 Central。",
    requestId: null,
  };
}

export const useAuditStore = defineStore("audit", {
  state: (): AuditStoreState => ({
    filter: defaultFilter(),
    items: [],
    nextCursor: null,
    state: "idle",
    message: "",
    requestId: null,
    error: null,
    loadingMore: false,
  }),
  getters: {
    loadedCount: (state): number => state.items.length,
    hasMore: (state): boolean => state.nextCursor !== null,
  },
  actions: {
    setFilter(filter: AuditFilter): void {
      this.filter = { ...filter };
    },

    reset(): void {
      inflight?.abort();
      inflight = null;
      this.$reset();
    },

    // Fetch the first page for the current filter, discarding anything loaded
    // under a previous one.
    async search(now: Date = new Date()): Promise<void> {
      await this.load({ append: false, now });
    },

    // Advance the cursor. A no-op when the window is already exhausted, so a
    // double click cannot re-request the last page.
    async loadMore(now: Date = new Date()): Promise<void> {
      if (this.nextCursor === null) {
        return;
      }
      await this.load({ append: true, now });
    },

    async load(options: { append: boolean; now: Date }): Promise<void> {
      inflight?.abort();
      const controller = new AbortController();
      inflight = controller;
      // Snapshot the filter this request belongs to: a response that arrives
      // after the filter changed answers a question nobody is asking any more.
      const asked = JSON.stringify(this.filter);
      const query = toWireQuery(this.filter, options.now);
      if (options.append && this.nextCursor) {
        query.cursor = this.nextCursor;
      }

      if (options.append) {
        this.loadingMore = true;
      } else {
        this.items = [];
        this.nextCursor = null;
        this.state = "loading";
        this.message = "";
        this.requestId = null;
        this.error = null;
      }

      try {
        const page = await api().listAudit(query, {
          signal: controller.signal,
        });
        if (JSON.stringify(this.filter) !== asked) {
          return;
        }
        this.items = options.append
          ? [...this.items, ...page.items]
          : page.items;
        this.nextCursor = page.next_cursor;
        this.state = this.items.length === 0 ? "empty" : "success";
        this.message = "";
        this.requestId = null;
        this.error = null;
      } catch (caught) {
        if (isAbortError(caught)) {
          return;
        }
        if (JSON.stringify(this.filter) !== asked) {
          return;
        }
        const { state, message, requestId } = classify(caught);
        this.message = message;
        this.requestId = requestId;
        this.error = caught;
        // A failure on a further page must not throw away what is on screen.
        this.state =
          options.append && this.items.length > 0 ? "partial" : state;
      } finally {
        this.loadingMore = false;
        if (inflight === controller) {
          inflight = null;
        }
      }
    },
  },
});

// Test seam: whether a request is still in flight (leak gate).
export function auditInflight(): boolean {
  return inflight !== null;
}
