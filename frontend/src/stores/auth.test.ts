import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it } from "vitest";

import { _resetApiClient, useAuthStore } from "./auth";

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
