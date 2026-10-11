import { defineStore } from "pinia";
import { toRaw } from "vue";

import type {
  CreateSessionInput,
  SessionDetail,
  SessionSummary,
} from "../api/dto";
import { api } from "./auth";

interface SessionsState {
  list: SessionSummary[];
  current: SessionDetail | null;
}

type ListParams = { node_id?: string; status?: string };

// Request ownership is plumbing, not session data. Keep it per store instance
// and out of reactive/serialized state, including across reset on auth loss.
interface Read<T> {
  source: object;
  promise: Promise<T>;
  fallback?: Read<T>;
  value?: T;
  failed?: boolean;
  installed?: boolean;
}

interface RequestOwnership {
  epoch: number;
  detail: number;
  detailTarget?: string | null;
  listParams?: ListParams;
  listLoaded: boolean;
  listPending: number;
  detailRead?: Read<SessionDetail>;
  listRead?: Read<SessionSummary[]>;
}
const requests = new WeakMap<object, RequestOwnership>();
function ownership(store: object): RequestOwnership {
  // Pinia devtools creates a new transparent action proxy for each invocation.
  const key = toRaw(store);
  let value = requests.get(key);
  if (!value) {
    value = {
      epoch: 0,
      detail: 0,
      listLoaded: false,
      listPending: 0,
    };
    requests.set(key, value);
  }
  return value;
}

// Only a background refresh may restore its predecessor. Ordinary navigation
// and Retry still invalidate earlier reads, including after a failed request.
function ownRead<T>(
  load: () => Promise<T>,
  current: () => Read<T> | undefined,
  claim: (read: Read<T>) => void,
  install: (value: T) => void,
  live: () => boolean,
  refresh: boolean,
): Promise<T> {
  // The promise is assigned synchronously before exposing this handle to callers.
  const fallback = refresh ? current() : undefined;
  const read = { source: fallback?.source ?? {}, fallback } as Read<T>;
  claim(read);
  read.promise = (async () => {
    try {
      const value = await load();
      read.value = value;
      if (live() && current() === read) {
        install(value);
        read.installed = true;
      }
      read.fallback = undefined;
      return value;
    } catch (caught) {
      read.failed = true;
      if (live() && current() === read && read.fallback) {
        let fallback = read.fallback;
        while (fallback.failed && fallback.fallback)
          fallback = fallback.fallback;
        claim(fallback);
        // A reply may have settled while the refresh owned the store. Already
        // installed data retains the mutation patch; pending reads install later.
        if (fallback.value !== undefined && !fallback.installed) {
          install(fallback.value);
          fallback.installed = true;
        }
      }
      throw caught;
    }
  })();
  return read.promise;
}

// Await only requests already issued. Re-check ownership after each completion
// because a failed refresh can restore a pending or already settled predecessor.
async function settleRead<T>(
  current: () => Read<T> | undefined,
  live: () => boolean,
): Promise<T> {
  while (live() && current()) {
    const read = current()!;
    try {
      const value = await read.promise;
      if (!live()) break;
      if (current() === read) return value;
    } catch (caught) {
      if (!live() || current() === read) throw caught;
    }
  }
  throw new Error("Read ownership changed.");
}

// An off-target refresh never takes current ownership from navigation/create.
async function readSession(
  store: SessionsState,
  id: string,
  updateCurrent: boolean,
  refresh = false,
): Promise<SessionDetail> {
  if (!updateCurrent) return api().getSession(id);
  const owner = ownership(store);
  const epoch = owner.epoch;
  owner.detail += 1;
  owner.detailTarget = id;
  return ownRead(
    () => api().getSession(id),
    () => owner.detailRead,
    (read) => {
      owner.detailRead = read;
    },
    (session) => {
      store.current = session;
    },
    () => owner.epoch === epoch,
    refresh,
  );
}

async function readList(
  store: SessionsState,
  params?: ListParams,
  refresh = false,
): Promise<SessionSummary[]> {
  const owner = ownership(store);
  const epoch = owner.epoch;
  owner.listParams = params ? { ...params } : undefined;
  owner.listPending += 1;
  try {
    return await ownRead(
      () => api().listSessions(owner.listParams),
      () => owner.listRead,
      (read) => {
        owner.listRead = read;
      },
      (list) => {
        store.list = list;
        owner.listLoaded = true;
      },
      () => owner.epoch === epoch,
      refresh,
    );
  } finally {
    if (owner.epoch === epoch) owner.listPending -= 1;
  }
}

export const useSessionsStore = defineStore("sessions", {
  state: (): SessionsState => ({ list: [], current: null }),
  actions: {
    async fetchList(params?: ListParams): Promise<SessionSummary[]> {
      const owner = ownership(this);
      const epoch = owner.epoch;
      const loading = readList(this, params);
      const source = owner.listRead?.source;
      let result: { value: SessionSummary[] } | { error: unknown };
      try {
        result = { value: await loading };
      } catch (caught) {
        result = { error: caught };
      }
      const owned = () =>
        owner.epoch === epoch &&
        source !== undefined &&
        owner.listRead?.source === source;
      if (owned()) {
        try {
          // The list resource must settle with the owning server response,
          // rather than report emptiness while its refresh still owns the store.
          await settleRead(() => owner.listRead, owned);
          return this.list;
        } catch (caught) {
          if (owned()) throw caught;
        }
      }
      if ("error" in result) throw result.error;
      return result.value;
    },
    async fetchSession(id: string): Promise<SessionDetail> {
      return readSession(this, id, true);
    },
    // A workspace's original GET may finish after a refresh. Settle against the
    // owning read, including a restored fallback, rather than its stale result.
    async settleSession(id: string): Promise<SessionDetail> {
      const owner = ownership(this);
      const epoch = owner.epoch;
      await settleRead(
        () => owner.detailRead,
        () => owner.epoch === epoch && owner.detailTarget === id,
      );
      if (owner.epoch === epoch && this.current?.id === id) return this.current;
      throw new Error("Session load was superseded.");
    },
    async create(input: CreateSessionInput): Promise<SessionDetail> {
      const owner = ownership(this);
      const epoch = owner.epoch;
      const request = ++owner.detail;
      owner.detailTarget = null;
      owner.detailRead = undefined;
      const session = await api().createSession(input);
      if (owner.epoch === epoch && owner.detail === request)
        this.current = session;
      return session;
    },
    async terminate(id: string): Promise<SessionDetail> {
      const owner = ownership(this);
      const epoch = owner.epoch;
      const session = await api().terminateSession(id);
      if (owner.epoch !== epoch) return session;
      if (this.current?.id === id) this.current = session;
      this.patchList(session);
      // Request start order cannot establish server snapshot freshness. Refresh
      // once after the mutation, preserving the accepted state if a read fails.
      const updateCurrent =
        owner.detailTarget === id ||
        (owner.detailTarget === undefined && this.current?.id === id);
      void readSession(this, id, updateCurrent, true).catch(() => {});
      if (owner.listLoaded || owner.listPending) {
        void readList(this, owner.listParams, true).catch(() => {});
      }
      return session;
    },
    patchList(session: SessionDetail): void {
      const index = this.list.findIndex((item) => item.id === session.id);
      if (index >= 0) {
        this.list[index] = { ...this.list[index], ...session };
      }
    },
    reset(): void {
      const owner = ownership(this);
      owner.epoch += 1;
      owner.detail += 1;
      owner.detailTarget = undefined;
      owner.listParams = undefined;
      owner.listLoaded = false;
      owner.listPending = 0;
      owner.detailRead = undefined;
      owner.listRead = undefined;
      this.list = [];
      this.current = null;
    },
  },
});
