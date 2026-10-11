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

// Keep request ordering outside reactive/serialized session data.
interface RequestOwnership {
  epoch: number;
  detail: number;
  list: number;
}
const requests = new WeakMap<object, RequestOwnership>();
function ownership(store: object): RequestOwnership {
  // Pinia devtools creates a new transparent action proxy for each invocation.
  const key = toRaw(store);
  let value = requests.get(key);
  if (!value) {
    value = { epoch: 0, detail: 0, list: 0 };
    requests.set(key, value);
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
      const epoch = owner.epoch;
      const request = ++owner.detail;
      const session = await api().getSession(id);
      if (owner.epoch === epoch && owner.detail === request)
        this.current = session;
      return session;
    },
    async create(input: CreateSessionInput): Promise<SessionDetail> {
      const owner = ownership(this);
      const epoch = owner.epoch;
      const request = ++owner.detail;
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
      return session;
    },
    patchList(session: SessionDetail): void {
      const index = this.list.findIndex((item) => item.id === session.id);
      if (index >= 0) {
        this.list[index] = { ...this.list[index], ...session };
      }
    },
    reset(): void {
      ownership(this).epoch += 1;
      this.list = [];
      this.current = null;
    },
  },
});
