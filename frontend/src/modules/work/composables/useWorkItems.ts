// The board's server state, through the one cache (PX-27/PX-29/PX-36).
//
// **Counts and items are two requests on purpose.** Counts is what the poller asks for
// every twenty seconds (D95) and it is a single `GROUP BY` on the server; items is asked
// for once and then only when a count actually moved. Polling both would make an open
// board a background download every twenty seconds.
//
// Per-group cursors rather than one: a board has four columns and "Load more" belongs to
// the column somebody clicked, not to the page.

import { computed, ref, type Ref } from "vue";

import type { WorkCounts, WorkItemsPage } from "../../../api/dto";
import { api } from "../../../stores/auth";
import { countsDiffer, countsPoller, keys, workCache } from "../queryCache";
import { encodeFilter } from "../viewState";

export interface WorkQuery {
  projectId: string;
  view: string | null;
  filter: Record<string, unknown> | null;
  /** The `q=` search. Separate from `filter` here for the same reason it is separate on
   *  the server: fifteen validated fields plus one unconstrained one is not an
   *  allowlist (`search_clause`). */
  search: string | null;
  group: string | null;
  order: string | null;
  limit: number;
}

function params(query: WorkQuery, cursors: Record<string, string>) {
  return {
    view: query.view ?? undefined,
    filter: query.filter ? encodeFilter(query.filter) : undefined,
    q: query.search ?? undefined,
    group: query.group ?? undefined,
    order: query.order ?? undefined,
    limit: query.limit,
    cursors: Object.keys(cursors).length ? encodeFilter(cursors) : undefined,
  };
}

export interface WorkItemsHandle {
  page: Ref<WorkItemsPage | null>;
  counts: Ref<WorkCounts | null>;
  loading: Ref<boolean>;
  error: Ref<unknown>;
  /** True when the filter names a runtime attention level and the server could not
   *  consult the registry. The toolbar disables the two runtime chips on this. */
  runtimeAvailable: Ref<boolean>;
  load: () => Promise<void>;
  refreshCounts: () => Promise<void>;
  loadMore: (groupKey: string) => Promise<void>;
  /** Drop this project's cached pages. Called after any mutation. */
  invalidate: () => void;
  subscribeToPolling: () => () => void;
}

export function useWorkItems(query: () => WorkQuery): WorkItemsHandle {
  const page = ref<WorkItemsPage | null>(null);
  const counts = ref<WorkCounts | null>(null);
  const loading = ref(false);
  const error = ref<unknown>(null);
  const cursors = ref<Record<string, string>>({});
  const runtimeAvailable = computed(
    () =>
      page.value?.runtime_signals_available ??
      counts.value?.runtime_signals_available ??
      true,
  );

  async function load(): Promise<void> {
    const current = query();
    loading.value = true;
    error.value = null;
    try {
      const request = params(current, cursors.value);
      page.value = await workCache.fetch(
        keys.workItems(current.projectId, request),
        () => api().getWorkItems(current.projectId, request),
      );
    } catch (problem) {
      error.value = problem;
    } finally {
      loading.value = false;
    }
  }

  async function refreshCounts(): Promise<void> {
    const current = query();
    // **The same three inputs the items request sends**, minus paging. A counts request
    // that forgot `q` would produce a header disagreeing with the list under it, which is
    // exactly the disagreement exit condition 1 forbids.
    const request = {
      view: current.view ?? undefined,
      filter: current.filter ? encodeFilter(current.filter) : undefined,
      q: current.search ?? undefined,
    };
    try {
      const next = await workCache.fetch(
        keys.workCounts(current.projectId, request),
        () => api().getWorkCounts(current.projectId, request),
        true,
      );
      // **The delta is what makes "poll counts, not items" real.** Without it the items
      // would be refetched three times a minute whether or not anything changed.
      if (countsDiffer(counts.value as never, next as never)) {
        counts.value = next;
        workCache.invalidate(keys.project(current.projectId));
        await load();
      } else {
        counts.value = next;
      }
    } catch {
      // A failed poll leaves the board as it was. What is on screen was true twenty
      // seconds ago, and blanking it is a worse answer than a slightly old one.
    }
  }

  async function loadMore(groupKey: string): Promise<void> {
    const group = page.value?.groups.find((entry) => entry.key === groupKey);
    if (!group?.next_cursor) return;
    cursors.value = { ...cursors.value, [groupKey]: group.next_cursor };
    const current = query();
    const request = params(current, cursors.value);
    const next = await api().getWorkItems(current.projectId, request);
    // **Appended, never re-sorted.** The reader's eye is on the rows that are already
    // there; a re-sort on "Load more" moves the row they were about to click.
    page.value = {
      ...next,
      groups: (page.value?.groups ?? []).map((existing) => {
        const fresh = next.groups.find((entry) => entry.key === existing.key);
        if (!fresh || existing.key !== groupKey) return existing;
        const seen = new Set(existing.items.map((item) => item.id));
        return {
          ...fresh,
          items: [
            ...existing.items,
            ...fresh.items.filter((item) => !seen.has(item.id)),
          ],
        };
      }),
    };
  }

  function invalidate(): void {
    cursors.value = {};
    workCache.invalidate(keys.project(query().projectId));
  }

  function subscribeToPolling(): () => void {
    return countsPoller.subscribe(refreshCounts);
  }

  return {
    page,
    counts,
    loading,
    error,
    runtimeAvailable,
    load,
    refreshCounts,
    loadMore,
    invalidate,
    subscribeToPolling,
  };
}
