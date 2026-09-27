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
  /**
   * Another tab installed a token pair and `/me` has not yet said whose it is
   * (#76). Until it does, nothing held for the previous user may be shown or
   * used: the pair may belong to someone else.
   */
  identityPending: boolean;
  /**
   * `/me` named a *different* user than the one this tab's page belongs to,
   * and the page is being left. Set and cleared by the auth-loss handler only.
   */
  discarding: boolean;
}

export const useAuthStore = defineStore("auth", {
  state: (): AuthState => ({
    accessToken: localStorage.getItem(ACCESS_KEY),
    refreshToken: localStorage.getItem(REFRESH_KEY),
    user: null,
    identityPending: false,
    discarding: false,
  }),
  getters: {
    isAuthenticated: (state): boolean => state.accessToken !== null,
    /**
     * Signed in *and* known to be the user whose page this is. False while a
     * cross-tab token swap is unconfirmed and while a different user's arrival
     * is being handled; protected content is covered and suspended until it is
     * true again. An ordinary refresh in this tab never makes it false.
     */
    identityConfirmed: (state): boolean =>
      state.accessToken !== null && !state.identityPending && !state.discarding,
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
      this.identityPending = false;
      localStorage.removeItem(ACCESS_KEY);
      localStorage.removeItem(REFRESH_KEY);
    },
    async login(username: string, password: string): Promise<void> {
      const result = await api().login(username, password);
      this.user = result.user;
      // Whoever just typed the password is, by definition, confirmed.
      this.identityPending = false;
    },
    async logout(): Promise<void> {
      // The client clears the tokens in its own `finally`, which is where the
      // auth-loss handler hears about it; the flag is how that handler tells a
      // sign-out the user asked for from one that happened to them.
      signingOut = true;
      try {
        await api().logout();
      } finally {
        signingOut = false;
      }
    },
    async loadMe(): Promise<void> {
      this.user = await api().me();
    },
  },
});

let client: ApiClient | null = null;

// True only while this tab's own `logout()` is running. Plain module state, not
// store state: it is read synchronously at the instant the tokens are cleared
// and means nothing at any other time.
let signingOut = false;

/** Whether the current loss of authentication is this tab's own sign-out. */
export function isSigningOut(): boolean {
  return signingOut;
}

// The token pairs the outstanding cross-tab identity check may still be
// answered for, refresh token → access token (#76 review 4). It starts as the
// pair the check was started for; each refresh *this tab* makes from one of
// them adds the pair it rotated to. Its own `/me` is the usual cause: the
// other tab's access token has often expired by the time this tab uses it, so
// the client refreshes and retries, and the answer then arrives under a pair
// the check has never seen. That pair was derived from the one being checked,
// so it names the same user and the answer stands. Anything else — a pair from
// another tab, a sign-in or sign-out here — is not in the set.
let verifyingPairs: Map<string, string> | null = null;

// api() returns the shared client, wired to read/rotate tokens through the auth
// store. Lazy so it is only touched once Pinia is active.
export function api(): ApiClient {
  if (!client) {
    const tokenStore: TokenStore = {
      accessToken: () => localStorage.getItem(ACCESS_KEY),
      refreshToken: () => localStorage.getItem(REFRESH_KEY),
      setTokens: (pair, reason) => {
        // Read before the write: the refresh token being replaced. The client
        // installs a refresh result only when that is the one it refreshed.
        const replaced = localStorage.getItem(REFRESH_KEY);
        if (
          reason === "refresh" &&
          replaced !== null &&
          verifyingPairs?.has(replaced)
        ) {
          verifyingPairs.set(pair.refresh_token, pair.access_token);
        }
        useAuthStore().setTokens(pair);
      },
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
      auth.identityPending = false;
      return;
    }
    // A pair this tab did not mint. It may be a refresh by the same user or a
    // sign-in by someone else, and only `/me` can say which (#76), so until it
    // answers the identity is unconfirmed: set before the tokens, so nothing
    // can observe the new pair as a confirmed one even for a moment.
    auth.identityPending = true;
    auth.accessToken = accessToken;
    auth.refreshToken = refreshToken;
    auth.user = null;

    // Two separate questions, answered separately (#76 review 4). Is this
    // still the latest check? — the generation, which only another storage
    // event (or uninstalling) moves. Is the pair installed now one this check
    // speaks for? — the original pair or one this tab's own refresh derived
    // from it. Comparing against the original pair alone threw away a correct
    // answer whenever `/me` had to refresh first, and left the page covered
    // with nothing left to uncover it.
    const pairs = new Map([[refreshToken, accessToken]]);
    verifyingPairs = pairs;
    const isStillCurrent = (): boolean => {
      if (generation !== eventGeneration) return false;
      const installed = localStorage.getItem(REFRESH_KEY);
      return (
        installed !== null &&
        pairs.get(installed) === localStorage.getItem(ACCESS_KEY)
      );
    };
    const settle = (): void => {
      if (verifyingPairs === pairs) verifyingPairs = null;
    };

    api()
      .me()
      .then((user) => {
        if (isStillCurrent()) {
          // User first: a different id is acted on (wiped, page left) inside
          // this assignment, before the pending flag drops and anything could
          // render for the new user.
          auth.user = user;
          auth.identityPending = false;
        }
      })
      .catch(() => {
        if (isStillCurrent()) {
          // Tokens first: dropping the pending flag while the unverified pair
          // is still installed would briefly make it look confirmed.
          auth.accessToken = null;
          auth.refreshToken = null;
          auth.user = null;
          auth.identityPending = false;
          localStorage.removeItem(ACCESS_KEY);
          localStorage.removeItem(REFRESH_KEY);
        }
      })
      .finally(settle);
  };
  window.addEventListener("storage", handler);
  return () => {
    generation += 1;
    verifyingPairs = null;
    window.removeEventListener("storage", handler);
  };
}
