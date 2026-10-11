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
const requests = new WeakMap<object, number>();
function nextRequest(store: object): number {
  const request = (requests.get(store) ?? 0) + 1;
  requests.set(store, request);
  return request;
}

export const useSessionsStore = defineStore("sessions", {
  state: (): SessionsState => ({ list: [], current: null }),
  actions: {
    async fetchList(params?: {
      node_id?: string;
      status?: string;
    }): Promise<SessionSummary[]> {
      this.list = await api().listSessions(params);
      return this.list;
    },
    async fetchSession(id: string): Promise<SessionDetail> {
      const request = nextRequest(this);
      const session = await api().getSession(id);
      if (requests.get(this) === request) this.current = session;
      return session;
    },
    async create(input: CreateSessionInput): Promise<SessionDetail> {
      const session = await api().createSession(input);
      this.current = session;
      return session;
    },
    async terminate(id: string): Promise<SessionDetail> {
      const request = requests.get(this);
      const session = await api().terminateSession(id);
      if (requests.get(this) === request && this.current?.id === id)
        this.current = session;
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
      nextRequest(this);
      this.list = [];
      this.current = null;
    },
  },
});
