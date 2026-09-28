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
// unmounted — the current session payload. The workspace itself drops its
// preview and suspends its terminals in the same tick (see
// `SessionWorkspaceView`), and `App.vue` makes the whole protected page inert
// behind a dialog for as long as `identityConfirmed` is false.
//
// A cross-tab token swap is the in-between case: the tokens are there but
// nobody yet knows whose they are. Nothing is wiped (it may be the same user
// after a refresh in another tab) but in-flight file work is aborted and the
// page is covered, and `/me` decides: the same user uncovers it as it was, a
// different one wipes it before it can render for them.

import { watch } from "vue";
import type { RouteLocationRaw, Router } from "vue-router";

import { isSigningOut, useAuthStore } from "../stores/auth";
import { useBinaryPreviewStore } from "../stores/binaryPreview";
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
    useBinaryPreviewStore().clear();
    favorites.clear();
  }

  /**
   * Leave the protected page. True when the router actually got there; false
   * when the navigation was refused, superseded or threw (a lazy route chunk
   * that failed to load). On false the page is still mounted, and it stays
   * covered and suspended: `App.vue`'s gate keys off auth state, not off this
   * navigation, and offers a full-page link that does not depend on the
   * router working.
   */
  async function leave(target: RouteLocationRaw): Promise<boolean> {
    try {
      if (router.currentRoute.value.meta.public) return true;
      return (await router.push(target)) === undefined;
    } catch {
      return false;
    } finally {
      // Only after the navigation has settled: clearing the session payload
      // under a mounted workspace in the middle of it would close an open
      // phone preview through the history stack. On failure it goes anyway;
      // the page is covered, and the previous user's payload is not kept.
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
      // Signed out covers the page on its own; a switch in progress is over.
      auth.discarding = false;
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
      // Covered from here until the previous user's page has really been left
      // — before `identityPending` drops, so there is no tick in which the new
      // user is "confirmed" on the old user's page.
      auth.discarding = true;
      wipeUserScoped();
      void leave({ name: "dashboard" }).then((left) => {
        // Only a navigation that arrived uncovers anything. A failed one keeps
        // the old page mounted, so it stays covered; the gate's link reloads.
        if (left && auth.user?.id === id) auth.discarding = false;
      });
    },
    { flush: "sync" },
  );

  // Identity unconfirmed (a cross-tab token swap, `/me` outstanding): stop
  // whatever file work is in flight — it was asked for by, or is about to be
  // answered to, someone who may no longer be here — but keep the cache, in
  // case `/me` names the same user. The store's own public abort
  // (stores/files.ts read-only, plan/29 MS-14).
  const stopPending = watch(
    () => auth.identityPending,
    (pending) => {
      if (pending) files.abortInflight();
    },
    { flush: "sync" },
  );

  return () => {
    stopAuth();
    stopUser();
    stopPending();
  };
}
