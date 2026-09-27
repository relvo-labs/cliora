// The app's one reaction to this tab losing its signed-in user (#76).
//
// The workspace cases in `SessionWorkspaceView.files.test.ts` drive this end to
// end for the two routes the review named (another tab, a refused refresh).
// These pin the handler's own rules: which transitions count, where each one
// goes, and which ones — a token refresh, the first sign-in — must *not* wipe
// anything.

import { flushPromises } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  createMemoryHistory,
  createRouter,
  type RouteComponent,
  type Router,
} from "vue-router";

import type { User } from "../api/dto";
import { _resetApiClient, useAuthStore } from "../stores/auth";
import { useFavoritesStore } from "../stores/favorites";
import { useFilesStore } from "../stores/files";
import { useSessionsStore } from "../stores/sessions";
import { createAppRouter, installAuthLossHandler, registerGuards } from ".";

const SESSION = "44444444-4444-4444-8444-444444444444";

function user(id: string): User {
  return {
    id,
    username: id,
    display_name: id,
    role: "Developer",
    permissions: [],
  };
}

function signIn(id: string, token = id): void {
  const auth = useAuthStore();
  auth.setTokens({
    access_token: `${token}-access`,
    refresh_token: `${token}-refresh`,
    token_type: "bearer",
  });
  auth.user = user(id);
}

function populate(): void {
  const files = useFilesStore();
  files.useSession(SESSION);
  files.dirs["."] = {
    path: ".",
    entries: [{ name: "a.md", rel_path: "a.md" } as never],
    state: "success",
    truncated: false,
  };
  useFavoritesStore().favorites = [{ id: "f", path: "/srv/p" } as never];
  useSessionsStore().current = { id: SESSION } as never;
}

function expectWiped(): void {
  const files = useFilesStore();
  expect(files.sessionId).toBeNull();
  expect(files.dirs).toEqual({});
  expect(useFavoritesStore().favorites).toEqual([]);
  expect(useSessionsStore().current).toBeNull();
}

function expectUntouched(): void {
  expect(useFilesStore().sessionId).toBe(SESSION);
  expect(useFilesStore().dirs["."]?.entries).toHaveLength(1);
  expect(useFavoritesStore().favorites).toHaveLength(1);
  expect(useSessionsStore().current?.id).toBe(SESSION);
}

let stop: (() => void) | undefined;

async function start(
  path = `/sessions/${SESSION}`,
  dashboard: RouteComponent | (() => Promise<RouteComponent>) = {
    template: "<div/>",
  },
): Promise<Router> {
  const blank = { template: "<div/>" };
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      {
        path: "/login",
        name: "login",
        component: blank,
        meta: { public: true },
      },
      { path: "/dashboard", name: "dashboard", component: dashboard },
      { path: "/sessions/:id", name: "session-workspace", component: blank },
    ],
  });
  registerGuards(router);
  stop = installAuthLossHandler(router);
  await router.push(path);
  await router.isReady();
  return router;
}

beforeEach(() => {
  setActivePinia(createPinia());
  localStorage.clear();
  _resetApiClient();
});
afterEach(() => {
  stop?.();
  stop = undefined;
  vi.unstubAllGlobals();
  _resetApiClient();
  localStorage.clear();
});

describe("installAuthLossHandler", () => {
  it("tokens cleared with no navigation: wipes at once and leaves for login, remembering the page", async () => {
    signIn("a");
    const router = await start();
    populate();

    useAuthStore().clearTokens();
    // Synchronous: gone inside the call that cleared the tokens, before any
    // render or request can use what was left.
    expect(useFilesStore().sessionId).toBeNull();
    expect(useFavoritesStore().favorites).toEqual([]);
    await flushPromises();

    expectWiped();
    expect(router.currentRoute.value.name).toBe("login");
    expect(router.currentRoute.value.query.redirect).toBe(
      `/sessions/${SESSION}`,
    );
  });

  it("this tab's own sign-out, even when Central refuses it, goes to login without a redirect", async () => {
    signIn("a");
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(null, { status: 500 })),
    );
    const router = await start();
    populate();

    await expect(useAuthStore().logout()).rejects.toBeDefined();
    await flushPromises();

    expectWiped();
    expect(useAuthStore().isAuthenticated).toBe(false);
    expect(router.currentRoute.value.name).toBe("login");
    expect(router.currentRoute.value.query.redirect).toBeUndefined();
  });

  it("a different user arriving without a signed-out moment wipes and leaves the page", async () => {
    // Another tab signed out and in again before this one heard: all it sees
    // is one token pair replaced by another, then `/me` naming someone else.
    signIn("a");
    const router = await start();
    populate();

    const auth = useAuthStore();
    auth.user = null;
    signIn("b");
    await flushPromises();

    expectWiped();
    expect(router.currentRoute.value.name).toBe("dashboard");
  });

  it("a token refresh for the same user wipes nothing", async () => {
    signIn("a");
    const router = await start();
    populate();

    // What the storage sync does when another tab refreshed: new pair, user
    // briefly unknown, then the same user again.
    const auth = useAuthStore();
    auth.user = null;
    signIn("a", "a2");
    await flushPromises();

    expectUntouched();
    expect(router.currentRoute.value.name).toBe("session-workspace");
  });

  it("the profile arriving after a reload wipes nothing", async () => {
    useAuthStore().setTokens({
      access_token: "a-access",
      refresh_token: "a-refresh",
      token_type: "bearer",
    });
    const router = await start();
    populate();

    useAuthStore().user = user("a");
    await flushPromises();

    expectUntouched();
    expect(router.currentRoute.value.name).toBe("session-workspace");
  });

  it("signing in again after a loss starts from nothing", async () => {
    signIn("a");
    const router = await start();
    populate();
    useAuthStore().clearTokens();
    await flushPromises();

    signIn("b");
    await router.push(`/sessions/${SESSION}`);
    await flushPromises();

    // Cleared at the loss and not refilled by anything the new user did.
    expect(useFilesStore().sessionId).toBeNull();
    expect(useFilesStore().dirs).toEqual({});
    expect(router.currentRoute.value.name).toBe("session-workspace");
  });

  it("already on a public page: wipes without navigating", async () => {
    const router = await start("/login");
    signIn("a");
    populate();

    useAuthStore().clearTokens();
    await flushPromises();

    expectWiped();
    expect(router.currentRoute.value.name).toBe("login");
    expect(router.currentRoute.value.query.redirect).toBeUndefined();
  });

  it("is installed by the production router", async () => {
    signIn("a");
    createAppRouter();
    populate();

    useAuthStore().clearTokens();

    expect(useFilesStore().sessionId).toBeNull();
    expect(useFavoritesStore().favorites).toEqual([]);
  });
});

// Identity unconfirmed: another tab installed a pair and `/me` is outstanding
// (#76 review 3). What the storage sync does is replayed here by hand — the
// flag, the tokens, the user unknown, then `/me`'s answer in the same order the
// sync applies it — so each rule can be pinned on its own.
describe("installAuthLossHandler — identity unconfirmed", () => {
  function swapPending(token: string): void {
    const auth = useAuthStore();
    auth.identityPending = true;
    auth.accessToken = `${token}-access`;
    auth.refreshToken = `${token}-refresh`;
    auth.user = null;
  }
  function meAnswers(id: string): void {
    const auth = useAuthStore();
    auth.user = user(id);
    auth.identityPending = false;
  }

  it("pending: in-flight file work is aborted, nothing is wiped, nobody navigates", async () => {
    signIn("a");
    const router = await start();
    populate();
    const abort = vi.spyOn(useFilesStore(), "abortInflight");

    swapPending("x");
    expect(abort).toHaveBeenCalledOnce();
    expect(useAuthStore().identityConfirmed).toBe(false);
    await flushPromises();

    expectUntouched();
    expect(router.currentRoute.value.name).toBe("session-workspace");
  });

  it("/me names the same user: everything is kept and the identity is confirmed again", async () => {
    signIn("a");
    const router = await start();
    populate();

    swapPending("a2");
    meAnswers("a");
    await flushPromises();

    expectUntouched();
    expect(useAuthStore().identityConfirmed).toBe(true);
    expect(useAuthStore().discarding).toBe(false);
    expect(router.currentRoute.value.name).toBe("session-workspace");
  });

  it("/me names someone else: wiped and covered in the same call, before the pending flag drops", async () => {
    signIn("a");
    const router = await start();
    populate();
    swapPending("b");

    const auth = useAuthStore();
    auth.user = user("b");
    // The sync drops the pending flag next; at this instant the page must
    // already be wiped and marked as being left.
    const confirmedInBetween = auth.identityConfirmed;
    expect(useFilesStore().dirs).toEqual({});
    expect(useFavoritesStore().favorites).toEqual([]);
    auth.identityPending = false;

    expect(confirmedInBetween).toBe(false);
    expect(auth.discarding).toBe(true);
    expect(auth.identityConfirmed).toBe(false);
    await flushPromises();

    expectWiped();
    expect(router.currentRoute.value.name).toBe("dashboard");
    // Arrived, so uncovered.
    expect(auth.discarding).toBe(false);
    expect(auth.identityConfirmed).toBe(true);
  });

  it("/me names someone else and leaving fails: the old page stays covered", async () => {
    signIn("a");
    const router = await start(`/sessions/${SESSION}`, () =>
      Promise.reject(new Error("chunk failed to load")),
    );
    populate();

    swapPending("b");
    meAnswers("b");
    await flushPromises();

    expect(router.currentRoute.value.name).toBe("session-workspace");
    expect(useFilesStore().dirs).toEqual({});
    expect(useAuthStore().discarding).toBe(true);
    expect(useAuthStore().identityConfirmed).toBe(false);
  });

  it("an ordinary refresh in this tab confirms nothing and suspends nothing", async () => {
    signIn("a");
    await start();
    populate();
    const abort = vi.spyOn(useFilesStore(), "abortInflight");

    // What the API client does after a 401 it could refresh.
    useAuthStore().setTokens({
      access_token: "a2-access",
      refresh_token: "a2-refresh",
      token_type: "bearer",
    });
    await flushPromises();

    expect(useAuthStore().identityConfirmed).toBe(true);
    expect(abort).not.toHaveBeenCalled();
    expectUntouched();
  });

  it("signed out while pending: the pending flag and any switch in progress are over", async () => {
    signIn("a");
    const router = await start();
    populate();
    swapPending("b");

    useAuthStore().clearTokens();
    await flushPromises();

    expectWiped();
    expect(useAuthStore().identityPending).toBe(false);
    expect(useAuthStore().discarding).toBe(false);
    expect(router.currentRoute.value.name).toBe("login");
  });
});
