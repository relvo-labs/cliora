import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it } from "vitest";
import { createMemoryHistory, createRouter, type Router } from "vue-router";

import { useAuthStore } from "../stores/auth";
import { registerGuards, routes } from "./index";

function makeRouter(): Router {
  const router = createRouter({ history: createMemoryHistory(), routes });
  registerGuards(router);
  return router;
}

describe("router auth guard", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    localStorage.clear();
  });

  it("redirects an unauthenticated user to login, preserving the target", async () => {
    const router = makeRouter();
    await router.push("/nodes");
    expect(router.currentRoute.value.name).toBe("login");
    expect(router.currentRoute.value.query.redirect).toBe("/nodes");
  });

  it("lets an unauthenticated user reach login", async () => {
    const router = makeRouter();
    await router.push("/login");
    expect(router.currentRoute.value.name).toBe("login");
  });

  it("keeps an authenticated user away from login", async () => {
    useAuthStore().setTokens({
      access_token: "a",
      refresh_token: "r",
      token_type: "bearer",
    });
    const router = makeRouter();
    await router.push("/login");
    // The dashboard is the landing page from P4-08.
    expect(router.currentRoute.value.name).toBe("dashboard");
  });

  it("allows an authenticated user to reach a protected route", async () => {
    useAuthStore().setTokens({
      access_token: "a",
      refresh_token: "r",
      token_type: "bearer",
    });
    const router = makeRouter();
    await router.push("/nodes");
    expect(router.currentRoute.value.name).toBe("nodes");
  });
});
