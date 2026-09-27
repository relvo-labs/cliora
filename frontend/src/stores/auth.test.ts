import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  _resetApiClient,
  api,
  installAuthStorageSync,
  useAuthStore,
} from "./auth";

describe("auth store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    localStorage.clear();
    _resetApiClient();
  });

  it("is unauthenticated with no token", () => {
    expect(useAuthStore().isAuthenticated).toBe(false);
  });

  it("persists tokens and becomes authenticated", () => {
    const auth = useAuthStore();
    auth.setTokens({
      access_token: "a",
      refresh_token: "r",
      token_type: "bearer",
    });
    expect(auth.isAuthenticated).toBe(true);
    expect(localStorage.getItem("cliora.access_token")).toBe("a");
    expect(localStorage.getItem("cliora.refresh_token")).toBe("r");
  });

  it("clears tokens, user, and storage on logout", () => {
    const auth = useAuthStore();
    auth.setTokens({
      access_token: "a",
      refresh_token: "r",
      token_type: "bearer",
    });
    auth.user = {
      id: "u1",
      username: "admin",
      display_name: "Admin",
      role: "Admin",
      permissions: ["node.manage"],
    };
    auth.clearTokens();
    expect(auth.isAuthenticated).toBe(false);
    expect(auth.user).toBeNull();
    expect(localStorage.getItem("cliora.access_token")).toBeNull();
  });

  it("reads the latest shared localStorage token, not a stale Pinia snapshot", async () => {
    const auth = useAuthStore();
    auth.setTokens({
      access_token: "access-1",
      refresh_token: "refresh-1",
      token_type: "bearer",
    });
    // Another tab refreshed the tokens: it writes straight to localStorage,
    // which does not touch this tab's Pinia state.
    localStorage.setItem("cliora.access_token", "access-2");
    localStorage.setItem("cliora.refresh_token", "refresh-2");

    const originalFetch = globalThis.fetch;
    const fetchMock = vi.fn(
      (_url: unknown, _init?: { headers?: Record<string, string> }) =>
        Promise.resolve({
          status: 200,
          ok: true,
          text: () => Promise.resolve("[]"),
          json: () => Promise.resolve([]),
        }),
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const client = api();

    try {
      await client.listNodes();
    } finally {
      globalThis.fetch = originalFetch;
    }

    expect(
      new Headers(fetchMock.mock.calls[0][1]?.headers).get("Authorization"),
    ).toBe("Bearer access-2");
  });

  it("syncs reactive tokens and user when another tab changes localStorage", () => {
    const auth = useAuthStore();
    auth.setTokens({
      access_token: "access-1",
      refresh_token: "refresh-1",
      token_type: "bearer",
    });

    const cleanup = installAuthStorageSync();
    try {
      localStorage.setItem("cliora.access_token", "access-2");
      localStorage.setItem("cliora.refresh_token", "refresh-2");
      window.dispatchEvent(
        new StorageEvent("storage", {
          key: "cliora.access_token",
          newValue: "access-2",
          storageArea: localStorage,
        }),
      );

      expect(auth.accessToken).toBe("access-2");
      expect(auth.refreshToken).toBe("refresh-2");

      localStorage.removeItem("cliora.access_token");
      localStorage.removeItem("cliora.refresh_token");
      window.dispatchEvent(
        new StorageEvent("storage", {
          key: "cliora.access_token",
          newValue: null,
          storageArea: localStorage,
        }),
      );

      expect(auth.accessToken).toBeNull();
      expect(auth.refreshToken).toBeNull();
      expect(auth.user).toBeNull();
    } finally {
      cleanup();
    }
  });

  it("reloads the authoritative principal instead of retaining the stale one after a cross-tab token rotation", async () => {
    const auth = useAuthStore();
    auth.setTokens({
      access_token: "access-1",
      refresh_token: "refresh-1",
      token_type: "bearer",
    });
    const oldUser = {
      id: "u-old",
      username: "old",
      display_name: "Old User",
      role: "Viewer",
      permissions: ["node.view"],
    };
    auth.user = oldUser;

    const newUser = {
      id: "u-new",
      username: "new",
      display_name: "New User",
      role: "Admin",
      permissions: ["node.manage", "audit.view"],
    };

    const originalFetch = globalThis.fetch;
    const fetchMock = vi.fn(
      (_url: unknown, _init?: { headers?: Record<string, string> }) =>
        Promise.resolve({
          status: 200,
          ok: true,
          text: () => Promise.resolve(JSON.stringify(newUser)),
          json: () => Promise.resolve(newUser),
        }),
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const cleanup = installAuthStorageSync();
    try {
      // Another tab rotated the session onto a different principal: it writes
      // straight to localStorage, which is all a cross-tab StorageEvent carries.
      localStorage.setItem("cliora.access_token", "access-2");
      localStorage.setItem("cliora.refresh_token", "refresh-2");
      window.dispatchEvent(
        new StorageEvent("storage", {
          key: "cliora.access_token",
          newValue: "access-2",
          storageArea: localStorage,
        }),
      );

      // The stale principal must not survive the rotation for even one tick:
      // the old user's permissions must not keep gating UI after the tokens
      // that authorized them are already gone.
      expect(auth.user).toBeNull();
      // And until `/me` answers, the new pair is not a confirmed identity
      // (#76): protected pages are covered and suspended meanwhile.
      expect(auth.identityPending).toBe(true);
      expect(auth.isAuthenticated).toBe(true);
      expect(auth.identityConfirmed).toBe(false);

      await vi.waitFor(() => {
        expect(auth.user).toEqual(newUser);
      });
      expect(auth.identityPending).toBe(false);
      expect(auth.identityConfirmed).toBe(true);
    } finally {
      cleanup();
      globalThis.fetch = originalFetch;
    }
  });

  it("a cross-tab pair that /me rejects is dropped, and is never confirmed on the way out (#76)", async () => {
    const auth = useAuthStore();
    auth.setTokens({
      access_token: "access-1",
      refresh_token: "refresh-1",
      token_type: "bearer",
    });
    const originalFetch = globalThis.fetch;
    globalThis.fetch = vi.fn(() =>
      Promise.resolve(
        new Response(JSON.stringify({ error: { code: "NO" } }), {
          status: 403,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    ) as unknown as typeof fetch;
    // Every state the store passes through, so a transient "confirmed with the
    // unverified pair" would show up here even though it lasts no tick.
    const seen: boolean[] = [];
    const stop = auth.$subscribe(() => seen.push(auth.identityConfirmed), {
      flush: "sync",
    });

    const cleanup = installAuthStorageSync();
    try {
      localStorage.setItem("cliora.access_token", "access-2");
      localStorage.setItem("cliora.refresh_token", "refresh-2");
      window.dispatchEvent(
        new StorageEvent("storage", { key: "cliora.access_token" }),
      );
      await vi.waitFor(() => expect(auth.accessToken).toBeNull());

      expect(auth.identityPending).toBe(false);
      expect(auth.identityConfirmed).toBe(false);
      expect(seen.length).toBeGreaterThan(0);
      expect(seen.every((confirmed) => !confirmed)).toBe(true);
    } finally {
      stop();
      cleanup();
      globalThis.fetch = originalFetch;
    }
  });

  // The cross-tab verification's own `/me` can meet an expired access token.
  // The client then refreshes and rotates the pair *in this tab*; that pair
  // descends from the one being verified, so the answer still belongs to it
  // (#76 review 4). A pair this tab did not derive from it still discards it.
  describe("cross-tab verification whose /me refreshes in this tab (#76)", () => {
    type FetchInit = Parameters<typeof fetch>[1];
    const SAME = {
      id: "u-same",
      username: "same",
      display_name: "Same",
      role: "Developer",
      permissions: [],
    };
    const originalFetch = globalThis.fetch;

    function json(status: number, body: unknown): Response {
      return new Response(JSON.stringify(body), {
        status,
        headers: { "Content-Type": "application/json" },
      });
    }
    function bearer(init?: FetchInit): string | null {
      return new Headers(init?.headers).get("Authorization");
    }
    function refreshed(init?: FetchInit): string {
      return (JSON.parse(String(init?.body)) as { refresh_token: string })
        .refresh_token;
    }
    function crossTab(access: string, refresh: string): void {
      localStorage.setItem("cliora.access_token", access);
      localStorage.setItem("cliora.refresh_token", refresh);
      window.dispatchEvent(
        new StorageEvent("storage", { key: "cliora.access_token" }),
      );
    }

    beforeEach(() => {
      useAuthStore().setTokens({
        access_token: "access-1",
        refresh_token: "refresh-1",
        token_type: "bearer",
      });
      useAuthStore().user = SAME;
    });
    afterEach(() => {
      globalThis.fetch = originalFetch;
    });

    it("401 → refresh → /me: the answer is accepted and the gate clears for the same user", async () => {
      const auth = useAuthStore();
      const fetchMock = vi.fn(async (url: unknown, init?: FetchInit) => {
        const path = String(url);
        if (path.endsWith("/api/auth/refresh")) {
          expect(refreshed(init)).toBe("refresh-2");
          return json(200, {
            access_token: "access-3",
            refresh_token: "refresh-3",
            token_type: "bearer",
          });
        }
        if (path.endsWith("/api/auth/me")) {
          return bearer(init) === "Bearer access-3"
            ? json(200, SAME)
            : json(401, { error: { code: "TOKEN_EXPIRED" } });
        }
        throw new Error(`unexpected ${path}`);
      });
      globalThis.fetch = fetchMock as unknown as typeof fetch;

      const cleanup = installAuthStorageSync();
      try {
        crossTab("access-2", "refresh-2");
        expect(auth.identityPending).toBe(true);

        await vi.waitFor(() => expect(auth.identityPending).toBe(false));
        expect(auth.user).toEqual(SAME);
        expect(auth.identityConfirmed).toBe(true);
        expect(auth.accessToken).toBe("access-3");
        expect(localStorage.getItem("cliora.refresh_token")).toBe("refresh-3");
        expect(fetchMock).toHaveBeenCalledTimes(3);
      } finally {
        cleanup();
      }
    });

    it("a pair another tab installs while /me is out still discards the answer (no event delivered yet)", async () => {
      const auth = useAuthStore();
      let answer!: () => void;
      const held = new Promise<void>((resolve) => (answer = resolve));
      const fetchMock = vi.fn(async (url: unknown, init?: FetchInit) => {
        expect(String(url)).toMatch(/\/api\/auth\/me$/);
        if (bearer(init) === "Bearer access-2") await held;
        return json(200, SAME);
      });
      globalThis.fetch = fetchMock as unknown as typeof fetch;

      const cleanup = installAuthStorageSync();
      try {
        crossTab("access-2", "refresh-2");
        await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
        // Written by the other tab; its storage event has not arrived.
        localStorage.setItem("cliora.access_token", "access-4");
        localStorage.setItem("cliora.refresh_token", "refresh-4");
        answer();
        await new Promise((r) => setTimeout(r, 20));
        expect(auth.identityPending).toBe(true);
        expect(auth.user).toBeNull();

        // Its event arrives: that pair is verified on its own.
        window.dispatchEvent(
          new StorageEvent("storage", { key: "cliora.access_token" }),
        );
        await vi.waitFor(() => expect(auth.identityPending).toBe(false));
        expect(auth.user).toEqual(SAME);
      } finally {
        cleanup();
      }
    });

    it("a refresh of a pair another tab installed meanwhile does not count as this verification's rotation", async () => {
      const auth = useAuthStore();
      const fetchMock = vi.fn(async (url: unknown, init?: FetchInit) => {
        const path = String(url);
        if (path.endsWith("/api/auth/refresh")) {
          // The client refreshes whatever pair is installed *now*.
          expect(refreshed(init)).toBe("refresh-4");
          return json(200, {
            access_token: "access-5",
            refresh_token: "refresh-5",
            token_type: "bearer",
          });
        }
        if (bearer(init) === "Bearer access-2") {
          // Another tab replaces the pair while this `/me` is out.
          localStorage.setItem("cliora.access_token", "access-4");
          localStorage.setItem("cliora.refresh_token", "refresh-4");
          return json(401, { error: { code: "TOKEN_EXPIRED" } });
        }
        return json(200, SAME);
      });
      globalThis.fetch = fetchMock as unknown as typeof fetch;

      const cleanup = installAuthStorageSync();
      try {
        crossTab("access-2", "refresh-2");
        await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
        await new Promise((r) => setTimeout(r, 20));
        expect(auth.identityPending).toBe(true);
        expect(auth.user).toBeNull();
      } finally {
        cleanup();
      }
    });

    it("a sign-in in this tab while /me is out discards the late answer", async () => {
      const auth = useAuthStore();
      const OTHER_USER = { ...SAME, id: "u-other", username: "other" };
      let answer!: () => void;
      const held = new Promise<void>((resolve) => (answer = resolve));
      const fetchMock = vi.fn(async (url: unknown) => {
        const path = String(url);
        if (path.endsWith("/api/auth/login")) {
          return json(200, {
            user: OTHER_USER,
            tokens: {
              access_token: "access-9",
              refresh_token: "refresh-9",
              token_type: "bearer",
            },
          });
        }
        await held;
        return json(200, SAME);
      });
      globalThis.fetch = fetchMock as unknown as typeof fetch;

      const cleanup = installAuthStorageSync();
      try {
        crossTab("access-2", "refresh-2");
        await auth.login("other", "pw");
        expect(auth.user).toEqual(OTHER_USER);
        answer();
        await new Promise((r) => setTimeout(r, 20));
        expect(auth.user).toEqual(OTHER_USER);
        expect(auth.identityPending).toBe(false);
      } finally {
        cleanup();
      }
    });
  });

  it("checks permissions against the loaded user", () => {
    const auth = useAuthStore();
    expect(auth.hasPermission("node.manage")).toBe(false);
    auth.user = {
      id: "u1",
      username: "dev",
      display_name: "Dev",
      role: "Developer",
      permissions: ["node.view"],
    };
    expect(auth.hasPermission("node.view")).toBe(true);
    expect(auth.hasPermission("node.manage")).toBe(false);
  });
});
