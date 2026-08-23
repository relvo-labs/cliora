import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

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
      features: [],
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
      features: [],
    };
    auth.user = oldUser;

    const newUser = {
      id: "u-new",
      username: "new",
      display_name: "New User",
      role: "Admin",
      permissions: ["node.manage", "audit.view"],
      features: [],
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

      await vi.waitFor(() => {
        expect(auth.user).toEqual(newUser);
      });
    } finally {
      cleanup();
      globalThis.fetch = originalFetch;
    }
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
      features: [],
    };
    expect(auth.hasPermission("node.view")).toBe(true);
    expect(auth.hasPermission("node.manage")).toBe(false);
  });
});
