// One place that reacts to this tab losing its signed-in user (#76).
//
// Authentication ends by more routes than the Logout button: another tab signs
// out (the storage sync clears this tab's tokens), Central refuses a token
// refresh (the API client clears them), a profile reload fails at start-up. None
// of those navigates, so the router guard — which only runs on a navigation —
// never hears about them, and every per-user cache held in memory stays on
// screen for whoever uses the tab next. The file cache is the sharp case: it is
// keyed by session id only, so the next user opening that id would be shown the
// previous user's listing without a request made on their behalf.
//
// Every one of those routes ends in the same observable fact, `accessToken`
// becoming null, so this watches that fact rather than each route. Synchronous
// flush: the caches are wiped inside the very call that cleared the tokens,
// before any component re-renders or any other watcher can issue a request
// with what is left.
//
// What is cleared is the user-scoped in-memory state: the file cache (with its
// in-flight requests aborted), favourites, and — once the workspace has
// unmounted — the current session payload. The workspace itself covers its
// content and drops its preview in the same tick (see `SessionWorkspaceView`).

import { watch } from "vue";
import type { RouteLocationRaw, Router } from "vue-router";

import { isSigningOut, useAuthStore } from "../stores/auth";
import { useFavoritesStore } from "../stores/favorites";
import { useFilesStore } from "../stores/files";
import { useSessionsStore } from "../stores/sessions";

export function installAuthLossHandler(router: Router): () => void {
  const auth = useAuthStore();
  const files = useFilesStore();
  const favorites = useFavoritesStore();
  const sessions = useSessionsStore();

  function wipeUserScoped(): void {
    // The store's own public reset: aborts every in-flight listing, search and
    // wipes the cache and the binding (stores/files.ts stays read-only here,
    // plan/29 MS-14).
    files.clearForSession(null);
    favorites.clear();
  }

  async function leave(target: RouteLocationRaw): Promise<void> {
    try {
      if (!router.currentRoute.value.meta.public) await router.push(target);
    } catch {
      // A navigation that throws still must not leave the payload behind; the
      // guard stops the protected view on the next attempt either way.
    } finally {
      // Only after the workspace has unmounted: clearing the session payload
      // under a mounted workspace would close an open phone preview through
      // the history stack in the middle of this navigation.
      sessions.reset();
    }
  }

  // The last user this tab was signed in as, to recognise a *different* user
  // arriving without a signed-out moment in between (below).
  let lastUserId: string | null = auth.user?.id ?? null;

  const stopAuth = watch(
    () => auth.isAuthenticated,
    (authenticated, was) => {
      if (authenticated || !was) return;
      lastUserId = null;
      wipeUserScoped();
      const from = router.currentRoute.value;
      // A sign-out the user asked for starts over at the landing page; one that
      // happened to them (expiry, another tab) comes back to where they were,
      // which is what the guard would have done on their next click.
      const query =
        isSigningOut() || from.meta.public ? {} : { redirect: from.fullPath };
      void leave({ name: "login", query });
    },
    { flush: "sync" },
  );

  // Another tab can sign out *and* sign in as someone else before this tab's
  // storage events are delivered (a backgrounded phone tab gets them late,
  // together), so the only thing this tab ever sees is one token pair replaced
  // by another. A token refresh looks the same at the token level, so the user
  // id — resolved by the storage sync's `/me` — is what tells the two apart.
  const stopUser = watch(
    () => auth.user?.id ?? null,
    (id) => {
      if (id === null) return;
      const previous = lastUserId;
      lastUserId = id;
      if (previous === null || previous === id) return;
      wipeUserScoped();
      void leave({ name: "dashboard" });
    },
    { flush: "sync" },
  );

  return () => {
    stopAuth();
    stopUser();
  };
}
