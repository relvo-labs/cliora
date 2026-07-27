import { defineStore } from "pinia";

import type { EnrollmentToken, EnrollmentTokenCreated } from "../api/dto";
import { api } from "./auth";

interface EnrollmentState {
  list: EnrollmentToken[];
  // The plaintext token is held only until the operator dismisses it.
  lastCreated: EnrollmentTokenCreated | null;
}

export const useEnrollmentStore = defineStore("enrollment", {
  state: (): EnrollmentState => ({ list: [], lastCreated: null }),
  actions: {
    async fetchList(): Promise<EnrollmentToken[]> {
      this.list = await api().listEnrollmentTokens();
      return this.list;
    },
    async create(input: {
      ttl_seconds?: number;
      max_uses?: number;
    }): Promise<EnrollmentTokenCreated> {
      const created = await api().createEnrollmentToken(input);
      this.lastCreated = created;
      await this.fetchList();
      return created;
    },
    async revoke(id: string): Promise<void> {
      await api().revokeEnrollmentToken(id);
      await this.fetchList();
    },
    dismissCreated(): void {
      this.lastCreated = null;
    },
  },
});
