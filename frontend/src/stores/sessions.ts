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
      const session = await api().getSession(id);
      this.current = session;
      return session;
    },
    async create(input: CreateSessionInput): Promise<SessionDetail> {
      const session = await api().createSession(input);
      this.current = session;
      return session;
    },
    async terminate(id: string): Promise<SessionDetail> {
      const session = await api().terminateSession(id);
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
      this.list = [];
      this.current = null;
    },
  },
});
