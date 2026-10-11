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
  list: number;
  sequence: number;
  terminations: Map<string, { sequence: number; session: SessionDetail }>;
}
const requests = new WeakMap<object, RequestOwnership>();
function ownership(store: object): RequestOwnership {
  let value = requests.get(store);
  if (!value) {
    value = {
      epoch: 0,
      detail: 0,
      list: 0,
      sequence: 0,
      terminations: new Map(),
    };
    requests.set(store, value);
  }
  return value;
}

// Reads retain their own ordering and all returned rows. A successful mutation
// supersedes only snapshots requested before it completed, for that same id.
// Call only within the request's epoch: a reset must never mix identities.
function reconcile<T extends SessionSummary>(
  session: T,
  owner: RequestOwnership,
  sequence: number,
): T {
  const termination = owner.terminations.get(session.id);
  return termination && termination.sequence > sequence
    ? { ...session, ...termination.session }
    : session;
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
      const sequence = owner.sequence;
      const response = await api().listSessions(params);
      if (owner.epoch !== epoch) return response;
      const list = response.map((session) =>
        reconcile(session, owner, sequence),
      );
      if (owner.list === request) this.list = list;
      return list;
    },
    async fetchSession(id: string): Promise<SessionDetail> {
      const owner = ownership(this);
      const epoch = owner.epoch;
      const request = ++owner.detail;
      const sequence = owner.sequence;
      const response = await api().getSession(id);
      if (owner.epoch !== epoch) return response;
      const session = reconcile(response, owner, sequence);
      if (owner.detail === request) this.current = session;
      return session;
    },
    async create(input: CreateSessionInput): Promise<SessionDetail> {
      const owner = ownership(this);
      const epoch = owner.epoch;
      const request = ++owner.detail;
      const sequence = owner.sequence;
      const response = await api().createSession(input);
      if (owner.epoch !== epoch) return response;
      const session = reconcile(response, owner, sequence);
      if (owner.detail === request) this.current = session;
      return session;
    },
    async terminate(id: string): Promise<SessionDetail> {
      const owner = ownership(this);
      const epoch = owner.epoch;
      const session = await api().terminateSession(id);
      // Retain the accepted result even while another workspace is displayed:
      // a pending return fetch or first list still needs to reconcile this id.
      if (owner.epoch !== epoch) return session;
      owner.terminations.set(id, { sequence: ++owner.sequence, session });
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
      const owner = ownership(this);
      owner.epoch += 1;
      owner.detail += 1;
      owner.list += 1;
      owner.sequence = 0;
      owner.terminations.clear();
      this.list = [];
      this.current = null;
    },
  },
});
