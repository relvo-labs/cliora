import { defineStore } from "pinia";

import { ApiClient, type TokenStore } from "../api/client";
import type { TokenPair, User } from "../api/dto";

// Token persistence policy (ADR 0006/0007): tokens live in localStorage so a
// reload keeps the session; logout and a failed refresh clear them. The access
// token is short-lived (15m) and the refresh token is server-revocable.
const ACCESS_KEY = "cliora.access_token";
const REFRESH_KEY = "cliora.refresh_token";

interface AuthState {
  accessToken: string | null;
  refreshToken: string | null;
  user: User | null;
}

export const useAuthStore = defineStore("auth", {
  state: (): AuthState => ({
    accessToken: localStorage.getItem(ACCESS_KEY),
    refreshToken: localStorage.getItem(REFRESH_KEY),
    user: null,
  }),
  getters: {
    isAuthenticated: (state): boolean => state.accessToken !== null,
  },
  actions: {
    hasPermission(action: string): boolean {
      return this.user?.permissions.includes(action) ?? false;
    },
    setTokens(pair: TokenPair): void {
      this.accessToken = pair.access_token;
      this.refreshToken = pair.refresh_token;
      localStorage.setItem(ACCESS_KEY, pair.access_token);
      localStorage.setItem(REFRESH_KEY, pair.refresh_token);
    },
    clearTokens(): void {
      this.accessToken = null;
      this.refreshToken = null;
      this.user = null;
      localStorage.removeItem(ACCESS_KEY);
      localStorage.removeItem(REFRESH_KEY);
    },
    async login(username: string, password: string): Promise<void> {
      const result = await api().login(username, password);
      this.user = result.user;
    },
    async logout(): Promise<void> {
      await api().logout();
    },
    async loadMe(): Promise<void> {
      this.user = await api().me();
    },
  },
});

let client: ApiClient | null = null;

// api() returns the shared client, wired to read/rotate tokens through the auth
// store. Lazy so it is only touched once Pinia is active.
export function api(): ApiClient {
  if (!client) {
    const tokenStore: TokenStore = {
      accessToken: () => useAuthStore().accessToken,
      refreshToken: () => useAuthStore().refreshToken,
      setTokens: (pair) => useAuthStore().setTokens(pair),
      clear: () => useAuthStore().clearTokens(),
    };
    client = new ApiClient(tokenStore);
  }
  return client;
}

// Test seam: reset the memoized client between tests.
export function _resetApiClient(): void {
  client = null;
}
