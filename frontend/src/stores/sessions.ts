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

// Request ownership is plumbing, not session data. Keep it per store instance
// and out of reactive/serialized state, including across reset on auth loss.
interface RequestOwnership {
  epoch: number;
  detail: number;
  target: string | null;
  list: number;
}
const requests = new WeakMap<object, RequestOwnership>();
function ownership(store: object): RequestOwnership {
  let value = requests.get(store);
  if (!value) {
    value = { epoch: 0, detail: 0, target: null, list: 0 };
    requests.set(store, value);
  }
  return value;
}

export const useSessionsStore = defineStore("sessions", {
  state: (): SessionsState => ({ list: [], current: null }),
  actions: {
    async fetchList(params?: {
      node_id?: string;
      status?: string;
    }): Promise<SessionSummary[]> {
      const owner = ownership(this);
      const epoch = owner.epoch;
      const request = ++owner.list;
      const list = await api().listSessions(params);
      if (owner.epoch === epoch && owner.list === request) this.list = list;
      return list;
    },
    async fetchSession(id: string): Promise<SessionDetail> {
      const owner = ownership(this);
      const request = ++owner.detail;
      owner.target = id;
      const session = await api().getSession(id);
      if (owner.detail === request) this.current = session;
      return session;
    },
    async create(input: CreateSessionInput): Promise<SessionDetail> {
      const owner = ownership(this);
      const request = ++owner.detail;
      owner.target = null;
      const session = await api().createSession(input);
      if (owner.detail === request) this.current = session;
      return session;
    },
    async terminate(id: string): Promise<SessionDetail> {
      const owner = ownership(this);
      const epoch = owner.epoch;
      const session = await api().terminateSession(id);
      // A mutation belongs to the authenticated store lifetime, not the fetch
      // that happened to be current when it started. A → B → A still accepts it.
      if (owner.epoch !== epoch) return session;
      if (this.current?.id === id) {
        this.current = session;
        // An older detail for this target cannot undo the mutation. Leave a
        // pending fetch for a different workspace alone.
        if (owner.target === id) owner.detail += 1;
      }
      owner.list += 1;
      this.patchList(session);
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
      owner.target = null;
      this.list = [];
      this.current = null;
    },
  },
});
