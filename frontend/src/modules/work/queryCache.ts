// Server state for the read model (PX-27, D100, plan/26/09 §2).
//
// **Written rather than installed** (D56). The honest framing of that choice, from
// D114: kintra runs the same module layout on `@tanstack/vue-query`, so kintra is
// evidence that *this structure* is readable at this size — it is **not** evidence that
// hand-rolling the query layer is a good idea. The bet here is that a board needs five of
// a query library's capabilities and none of the rest, and the reversal point is written
// down: if this file starts growing a retry policy, suspense integration or devtools,
// `beta.2` swaps in the package (plan/26/11 §4).
//
// **`useAsyncResource` is not extended and not touched** — it is 78 lines with no key, no
// cross-caller storage, no dedupe and no invalidation, so there is nothing to extend. It
// stays on the do-not-touch list and V1's twenty-eight call sites keep it.
//
// Five capabilities, and each is here because the board breaks without it:
//
// 1. **stable structured keys**, so two components asking the same question share an
//    entry — key order must not matter, or they silently do not;
// 2. **in-flight dedupe**, so mounting a board and its toolbar is one request;
// 3. **prefix invalidation**, so "this project changed" is one call rather than a list of
//    keys somebody has to keep current;
// 4. **optimistic mutation with a mandatory rollback**, because a card that stays in its
//    new lane after a refusal is a card the user believes moved;
// 5. **a counts poller** that stops when the tab is hidden (D95).

import { onScopeDispose, ref, shallowRef, type Ref } from "vue";

/** A cache key as a structured value. `["work-items", projectId, {…}]` and so on.
 *
 *  Arrays and plain objects only. A key containing a function or a class instance would
 *  serialise to something that looks stable and is not. */
export type QueryKey = readonly (
  | string
  | number
  | boolean
  | null
  | undefined
  | KeyObject
)[];
type KeyObject = {
  readonly [key: string]:
    | string
    | number
    | boolean
    | null
    | undefined
    | readonly string[];
};

export interface CacheEntry<T> {
  data: T | null;
  error: unknown;
  /** Epoch millis of the last successful load, or 0. Used by `isStale`, not by equality. */
  updatedAt: number;
  inflight: Promise<T> | null;
}

/** Serialise a key so that property order cannot change the answer.
 *
 *  `{a: 1, b: 2}` and `{b: 2, a: 1}` are the same question, and a `JSON.stringify` would
 *  make them two cache entries — two requests, two answers, and a board whose toolbar
 *  disagrees with its columns. This is the single most load-bearing function in the file
 *  and it has its own test. */
export function serialiseKey(key: QueryKey): string {
  return JSON.stringify(key, (_field, value) => {
    if (value === null || typeof value !== "object" || Array.isArray(value))
      return value;
    const sorted: Record<string, unknown> = {};
    for (const name of Object.keys(value as Record<string, unknown>).sort()) {
      const inner = (value as Record<string, unknown>)[name];
      // `undefined` is dropped by JSON.stringify inside objects but kept inside arrays,
      // so it is normalised here — otherwise `{a: undefined}` and `{}` differ.
      if (inner !== undefined) sorted[name] = inner;
    }
    return sorted;
  });
}

/** Whether `key` starts with `prefix`. The basis of invalidation.
 *
 *  Compared element by element on the serialised form of each element, so an object in
 *  the middle of a prefix behaves the same way as a string. */
export function keyHasPrefix(key: QueryKey, prefix: QueryKey): boolean {
  if (prefix.length > key.length) return false;
  return prefix.every(
    (element, index) => serialiseKey([element]) === serialiseKey([key[index]]),
  );
}

export interface QueryHandle<T> {
  data: Ref<T | null>;
  error: Ref<unknown>;
  loading: Ref<boolean>;
  /** Fetch unless a fresh entry or an in-flight request already covers it. */
  load: () => Promise<T | null>;
  /** Fetch regardless. Used by the poller and by explicit retry. */
  refresh: () => Promise<T | null>;
}

export interface QueryCacheOptions {
  /** How long a successful entry is served without a network call. */
  staleAfterMs?: number;
  /** Injected for tests. Not `Date.now` directly, so a test can freeze it. */
  now?: () => number;
}

export class QueryCache {
  private readonly entries = new Map<string, CacheEntry<unknown>>();
  private readonly listeners = new Map<string, Set<() => void>>();
  private readonly staleAfterMs: number;
  private readonly now: () => number;

  constructor(options: QueryCacheOptions = {}) {
    this.staleAfterMs = options.staleAfterMs ?? 15_000;
    this.now = options.now ?? (() => Date.now());
  }

  /** The raw entry, for tests and for the poller's delta check. */
  peek<T>(key: QueryKey): CacheEntry<T> | undefined {
    return this.entries.get(serialiseKey(key)) as CacheEntry<T> | undefined;
  }

  isStale(key: QueryKey): boolean {
    const entry = this.peek(key);
    if (!entry || entry.data === null) return true;
    return this.now() - entry.updatedAt > this.staleAfterMs;
  }

  /** Fetch, deduplicating concurrent callers of the same key.
   *
   *  The second caller receives **the same promise**, not a second request. Mounting a
   *  board and its toolbar in the same tick is otherwise two identical queries, and at
   *  the counts endpoint's polling rate that doubles the hottest request in the phase. */
  async fetch<T>(
    key: QueryKey,
    loader: () => Promise<T>,
    force = false,
  ): Promise<T> {
    const id = serialiseKey(key);
    const entry = (this.entries.get(id) ?? {
      data: null,
      error: null,
      updatedAt: 0,
      inflight: null,
    }) as CacheEntry<T>;
    this.entries.set(id, entry as CacheEntry<unknown>);

    if (entry.inflight) return entry.inflight;
    if (!force && entry.data !== null && !this.isStale(key)) return entry.data;

    const request = loader()
      .then((value) => {
        entry.data = value;
        entry.error = null;
        entry.updatedAt = this.now();
        return value;
      })
      .catch((problem: unknown) => {
        // The **error is stored and the data is kept**. A failed refresh must not blank a
        // board that was on screen a second ago; the component decides whether to show
        // the stale data with a warning or to show the error.
        entry.error = problem;
        throw problem;
      })
      .finally(() => {
        entry.inflight = null;
        this.notify(id);
      });
    entry.inflight = request;
    return request;
  }

  /** Write a value in without going near the network. Used by optimistic mutation. */
  set<T>(key: QueryKey, data: T): void {
    const id = serialiseKey(key);
    const entry = (this.entries.get(id) ?? {
      data: null,
      error: null,
      updatedAt: 0,
      inflight: null,
    }) as CacheEntry<T>;
    entry.data = data;
    entry.updatedAt = this.now();
    this.entries.set(id, entry as CacheEntry<unknown>);
    this.notify(id);
  }

  /** Drop every entry whose key starts with `prefix`, and return how many.
   *
   *  A prefix rather than a list of keys: "this project changed" has to be expressible
   *  without anybody maintaining an inventory of the keys that describe it. The count is
   *  returned because a mutation that invalidated nothing is usually a key mismatch, and
   *  that is otherwise silent. */
  invalidate(prefix: QueryKey): number {
    let dropped = 0;
    for (const id of [...this.entries.keys()]) {
      if (!keyHasPrefix(JSON.parse(id) as QueryKey, prefix)) continue;
      this.entries.delete(id);
      dropped += 1;
      this.notify(id);
    }
    return dropped;
  }

  clear(): void {
    this.entries.clear();
  }

  /** Optimistic write with a **mandatory** rollback.
   *
   *  `rollback` is not optional, and that is the whole design: a card that stays in its
   *  new lane after the server refused is a card the user believes moved. The rollback
   *  runs before the error propagates, so by the time a component sees the failure the
   *  board is already back where it was. */
  async mutate<T>(
    action: () => Promise<T>,
    options: {
      apply: () => void;
      rollback: () => void;
      invalidate?: QueryKey[];
    },
  ): Promise<T> {
    options.apply();
    try {
      const result = await action();
      for (const prefix of options.invalidate ?? []) this.invalidate(prefix);
      return result;
    } catch (problem) {
      options.rollback();
      throw problem;
    }
  }

  subscribe(key: QueryKey, listener: () => void): () => void {
    const id = serialiseKey(key);
    const set = this.listeners.get(id) ?? new Set();
    set.add(listener);
    this.listeners.set(id, set);
    return () => set.delete(listener);
  }

  private notify(id: string): void {
    for (const listener of this.listeners.get(id) ?? []) listener();
  }

  /** A reactive handle onto one key. */
  query<T>(key: QueryKey, loader: () => Promise<T>): QueryHandle<T> {
    const data = shallowRef<T | null>((this.peek<T>(key)?.data as T) ?? null);
    const error = shallowRef<unknown>(null);
    const loading = ref(false);
    const sync = () => {
      const entry = this.peek<T>(key);
      data.value = entry?.data ?? null;
      error.value = entry?.error ?? null;
    };
    const unsubscribe = this.subscribe(key, sync);
    onScopeDispose(unsubscribe);

    const run = async (force: boolean): Promise<T | null> => {
      loading.value = true;
      try {
        const value = await this.fetch(key, loader, force);
        data.value = value;
        error.value = null;
        return value;
      } catch (problem) {
        error.value = problem;
        return data.value;
      } finally {
        loading.value = false;
      }
    };
    return {
      data,
      error,
      loading,
      load: () => run(false),
      refresh: () => run(true),
    };
  }
}

/** The counts poller (D95). Twenty seconds, paused while the tab is hidden.
 *
 *  **Reference-counted.** The board, the toolbar and My Work all want fresh counts, and
 *  three components each owning a timer is three times the load on the hottest endpoint
 *  in the phase. The interval starts with the first subscriber and stops when the last
 *  one leaves — which is the part `stores/dashboard.ts`'s timer left implicit and is
 *  therefore stated here.
 *
 *  **Items are not polled.** Only counts. When a count changes, the affected item queries
 *  are invalidated and re-fetched by whoever is displaying them; polling both would make
 *  a board of two hundred cards a background download every twenty seconds.
 */
export const COUNTS_POLL_MS = 20_000;

export interface CountsPollerOptions {
  intervalMs?: number;
  /** Injected so a test does not have to wait twenty seconds. */
  schedule?: (callback: () => void, ms: number) => number;
  cancel?: (handle: number) => void;
  /** Injected so a test can drive visibility. */
  isHidden?: () => boolean;
  onVisibilityChange?: (listener: () => void) => () => void;
}

export class CountsPoller {
  private readonly subscribers = new Set<() => void | Promise<unknown>>();
  private handle: number | null = null;
  private detachVisibility: (() => void) | null = null;
  private readonly intervalMs: number;
  private readonly schedule: (callback: () => void, ms: number) => number;
  private readonly cancel: (handle: number) => void;
  private readonly isHidden: () => boolean;
  private readonly onVisibilityChange: (listener: () => void) => () => void;

  constructor(options: CountsPollerOptions = {}) {
    this.intervalMs = options.intervalMs ?? COUNTS_POLL_MS;
    this.schedule =
      options.schedule ??
      ((callback, ms) => window.setInterval(callback, ms) as unknown as number);
    this.cancel = options.cancel ?? ((handle) => window.clearInterval(handle));
    this.isHidden = options.isHidden ?? (() => document.hidden);
    this.onVisibilityChange =
      options.onVisibilityChange ??
      ((listener) => {
        document.addEventListener("visibilitychange", listener);
        return () => document.removeEventListener("visibilitychange", listener);
      });
  }

  get running(): boolean {
    return this.handle !== null;
  }

  get subscriberCount(): number {
    return this.subscribers.size;
  }

  subscribe(refresh: () => void | Promise<unknown>): () => void {
    this.subscribers.add(refresh);
    this.start();
    return () => {
      this.subscribers.delete(refresh);
      if (this.subscribers.size === 0) this.stop();
    };
  }

  /** Fire every subscriber once, now. Called by the interval and on becoming visible.
   *
   *  A tab that has been hidden for an hour is a tab whose counts are an hour old, so
   *  becoming visible refreshes immediately rather than waiting for the next tick. */
  async tick(): Promise<void> {
    if (this.isHidden()) return;
    await Promise.all([...this.subscribers].map((refresh) => refresh()));
  }

  private start(): void {
    if (this.handle !== null) return;
    this.handle = this.schedule(() => void this.tick(), this.intervalMs);
    this.detachVisibility = this.onVisibilityChange(() => {
      if (!this.isHidden()) void this.tick();
    });
  }

  private stop(): void {
    if (this.handle !== null) {
      this.cancel(this.handle);
      this.handle = null;
    }
    this.detachVisibility?.();
    this.detachVisibility = null;
  }
}

/** The one cache and the one poller for the application.
 *
 *  Module singletons rather than a Pinia store: there is no state here a devtool needs to
 *  inspect and no action a component dispatches, and wrapping a Map in a store would add
 *  a layer whose only content is `this.cache`. */
export const workCache = new QueryCache();
export const countsPoller = new CountsPoller();

/** The key vocabulary, in one place.
 *
 *  Written as functions rather than assembled at call sites, because a typo in a key is
 *  not an error — it is a cache miss, forever, on one component. */
export const keys = {
  workItems: (projectId: string, query: KeyObject) =>
    ["work-items", projectId, query] as const,
  workCounts: (projectId: string, query: KeyObject) =>
    ["work-counts", projectId, query] as const,
  myWorkItems: (query: KeyObject) => ["me-work-items", query] as const,
  myCounts: (query: KeyObject) => ["me-attention-counts", query] as const,
  views: (projectId: string) => ["work-views", projectId] as const,
  task: (taskId: string) => ["task", taskId] as const,
  /** Everything about one project, for the coarse invalidation after a mutation. */
  project: (projectId: string) => ["work-items", projectId] as const,
};

/** Whether two count payloads differ in any cell.
 *
 *  The poller's delta check. Items are re-fetched only when this says yes, which is what
 *  keeps "poll counts, not items" from being a distinction without a difference. */
export function countsDiffer(
  before: Record<string, Record<string, number> | number | boolean> | null,
  after: Record<string, Record<string, number> | number | boolean> | null,
): boolean {
  if (before === null || after === null) return before !== after;
  return (
    serialiseKey([before as KeyObject]) !== serialiseKey([after as KeyObject])
  );
}
