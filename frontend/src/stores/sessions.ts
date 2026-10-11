import { defineStore } from "pinia";

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
interface RequestOwnership {
  epoch: number;
  detail: number;
  list: number;
  detailTarget?: string | null;
  listParams?: ListParams;
  listLoaded: boolean;
  listPending: number;
}
const requests = new WeakMap<object, RequestOwnership>();
function ownership(store: object): RequestOwnership {
  let value = requests.get(store);
  if (!value) {
    value = {
      epoch: 0,
      detail: 0,
      list: 0,
      listLoaded: false,
      listPending: 0,
    };
    requests.set(store, value);
  }
  return value;
}

// Background reads for another session must not take ownership from a pending
// workspace load. Reads of the active target use the same ordering as navigation.
async function readSession(
  store: SessionsState,
  id: string,
  updateCurrent: boolean,
): Promise<SessionDetail> {
  const owner = ownership(store);
  const epoch = owner.epoch;
  const request = updateCurrent ? ++owner.detail : owner.detail;
  if (updateCurrent) owner.detailTarget = id;
  const session = await api().getSession(id);
  if (updateCurrent && owner.epoch === epoch && owner.detail === request) {
    store.current = session;
  }
  return session;
}

export const useSessionsStore = defineStore("sessions", {
  state: (): SessionsState => ({ list: [], current: null }),
  actions: {
    async fetchList(params?: ListParams): Promise<SessionSummary[]> {
      const owner = ownership(this);
      const epoch = owner.epoch;
      const request = ++owner.list;
      owner.listParams = params ? { ...params } : undefined;
      owner.listPending += 1;
      try {
        const list = await api().listSessions(owner.listParams);
        if (owner.epoch === epoch && owner.list === request) {
          this.list = list;
          owner.listLoaded = true;
        }
        return list;
      } finally {
        if (owner.epoch === epoch) owner.listPending -= 1;
      }
    },
    async fetchSession(id: string): Promise<SessionDetail> {
      return readSession(this, id, true);
    },
    async create(input: CreateSessionInput): Promise<SessionDetail> {
      const owner = ownership(this);
      const epoch = owner.epoch;
      const request = ++owner.detail;
      owner.detailTarget = null;
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
      void readSession(this, id, updateCurrent).catch(() => {});
      if (owner.listLoaded || owner.listPending) {
        void this.fetchList(owner.listParams).catch(() => {});
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
      owner.list += 1;
      owner.detailTarget = undefined;
      owner.listParams = undefined;
      owner.listLoaded = false;
      owner.listPending = 0;
      this.list = [];
      this.current = null;
    },
  },
});
