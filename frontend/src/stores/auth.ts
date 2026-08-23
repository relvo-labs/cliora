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
    // What the deployment has, as opposed to what this person may do. Both are
    // required before a control is shown, and the server checks both again.
    hasFeature(feature: string): boolean {
      return this.user?.features?.includes(feature) ?? false;
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
      accessToken: () => localStorage.getItem(ACCESS_KEY),
      refreshToken: () => localStorage.getItem(REFRESH_KEY),
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

// Cross-tab sync: another tab's refresh/logout writes straight to
// localStorage, bypassing this tab's Pinia state. Mirror those writes into
// the active store's reactive tokens so in-memory reads (and isAuthenticated)
// stay consistent with what ApiClient's TokenStore already reads live.
export function installAuthStorageSync(): () => void {
  let generation = 0;
  const handler = (event: StorageEvent): void => {
    if (
      event.key !== ACCESS_KEY &&
      event.key !== REFRESH_KEY &&
      event.key !== null
    ) {
      return;
    }
    generation += 1;
    const eventGeneration = generation;
    const auth = useAuthStore();
    const accessToken = localStorage.getItem(ACCESS_KEY);
    const refreshToken = localStorage.getItem(REFRESH_KEY);
    if (accessToken === null || refreshToken === null) {
      auth.accessToken = null;
      auth.refreshToken = null;
      auth.user = null;
      return;
    }
    auth.accessToken = accessToken;
    auth.refreshToken = refreshToken;
    auth.user = null;

    const isStillCurrent = (): boolean =>
      generation === eventGeneration &&
      localStorage.getItem(ACCESS_KEY) === accessToken &&
      localStorage.getItem(REFRESH_KEY) === refreshToken;

    api()
      .me()
      .then((user) => {
        if (isStillCurrent()) {
          auth.user = user;
        }
      })
      .catch(() => {
        if (isStillCurrent()) {
          auth.accessToken = null;
          auth.refreshToken = null;
          auth.user = null;
          localStorage.removeItem(ACCESS_KEY);
          localStorage.removeItem(REFRESH_KEY);
        }
      });
  };
  window.addEventListener("storage", handler);
  return () => {
    generation += 1;
    window.removeEventListener("storage", handler);
  };
}
