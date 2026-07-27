// Workspace favourites and recents (P4-13, FR-WORKSPACE-004/005).
//
// These are shortcuts for starting a session, so the store is built around one
// premise: **a favourite is never evidence that a path is allowed.** The server
// re-authorizes on every use and reports a per-entry `usability` on every read, so
// this store deliberately does *not* cache a verdict — it caches rows, and the
// verdict travels with them.
//
// Three behaviours here exist because of how optimistic toggles go wrong:
//
//   * a toggle is applied immediately and **rolled back on failure**, so a refused
//     favourite does not stay on screen looking saved;
//   * a path is keyed by `(node, path)` while a pending add has no id yet, so a
//     second click on the same row cannot create a duplicate request;
//   * `forbidden` is a terminal state, not an error to retry: a Viewer has no
//     `session.create`, so retrying will never start working.
//
// `load()` also carries a sequence guard, because the dialog reloads on every open:
// without it a slow first fetch could land after a faster second one and replace the
// current lists with older rows — including older `usability` verdicts.

import { defineStore } from "pinia";

import { ApiError } from "../api/client";
import type { RecentWorkspace, WorkspaceFavorite } from "../api/dto";
import { api } from "./auth";

export type FavoritesState =
  | "idle"
  | "loading"
  | "success"
  | "empty"
  | "forbidden"
  | "error";

interface FavoritesStoreState {
  favorites: WorkspaceFavorite[];
  recent: RecentWorkspace[];
  state: FavoritesState;
  error: unknown;
  // `(node_id, path)` keys with a request in flight. Keyed on the pair rather than
  // the row id because an optimistic add has no id yet.
  pending: string[];
  // Monotonic counter identifying the newest `load()`. A response from an older one
  // is dropped rather than applied.
  loadSeq: number;
}

export function favoriteKey(nodeId: string, path: string): string {
  return `${nodeId} ${path}`;
}

export const useFavoritesStore = defineStore("favorites", {
  state: (): FavoritesStoreState => ({
    favorites: [],
    recent: [],
    state: "idle",
    error: null,
    pending: [],
    loadSeq: 0,
  }),

  getters: {
    // Only entries that could start a session right now. The unusable ones stay in
    // `favorites` so the UI can show them with a reason — dropping them here would
    // make "my favourite vanished" the user's experience of a disabled node.
    usableFavorites: (s): WorkspaceFavorite[] =>
      s.favorites.filter((f) => f.usability === "usable"),

    favoritesForNode:
      (s) =>
      (nodeId: string): WorkspaceFavorite[] =>
        s.favorites.filter((f) => f.node_id === nodeId),

    recentForNode:
      (s) =>
      (nodeId: string): RecentWorkspace[] =>
        s.recent.filter((r) => r.node_id === nodeId),

    isFavorite:
      (s) =>
      (nodeId: string, path: string): boolean =>
        s.favorites.some((f) => f.node_id === nodeId && f.path === path),

    favoriteId:
      (s) =>
      (nodeId: string, path: string): string | null =>
        s.favorites.find((f) => f.node_id === nodeId && f.path === path)?.id ??
        null,

    isPending:
      (s) =>
      (nodeId: string, path: string): boolean =>
        s.pending.includes(favoriteKey(nodeId, path)),
  },

  actions: {
    /** Load both lists. One state for both: they are one UI region, and reporting
     * them separately would let the dialog show a half-loaded shortcut row. */
    async load(): Promise<void> {
      const seq = this.loadSeq + 1;
      this.loadSeq = seq;
      this.state = "loading";
      this.error = null;
      try {
        const [favorites, recent] = await Promise.all([
          api().listFavorites(),
          api().listRecentWorkspaces(),
        ]);
        if (seq !== this.loadSeq) return;
        this.favorites = favorites;
        this.recent = recent;
        this.state =
          favorites.length === 0 && recent.length === 0 ? "empty" : "success";
      } catch (caught) {
        // A superseded load's failure is not the current load's failure: reporting it
        // would show an error over rows that loaded fine.
        if (seq !== this.loadSeq) return;
        this.error = caught;
        // A 403 means the role has no `session.create`. Retrying cannot help, so
        // the region hides itself rather than offering a button that never works.
        this.state =
          caught instanceof ApiError && caught.status === 403
            ? "forbidden"
            : "error";
      }
    },

    /** Favourite a path, showing it immediately and removing it again if refused.
     *
     * Returns the stored row, or null if the server refused. The refusal is kept in
     * `error` so the caller can render the reason (a path outside an allowed root
     * is the expected one).
     */
    async add(
      nodeId: string,
      path: string,
      displayName?: string | null,
    ): Promise<WorkspaceFavorite | null> {
      const key = favoriteKey(nodeId, path);
      if (this.pending.includes(key)) return null;
      const already = this.favorites.find(
        (f) => f.node_id === nodeId && f.path === path,
      );
      if (already) return already;
      this.pending.push(key);
      // Optimistic row. The temporary id is never sent anywhere: it is replaced by
      // the server's row on success and dropped entirely on failure.
      const optimistic: WorkspaceFavorite = {
        id: `pending:${key}`,
        node_id: nodeId,
        node_name: "",
        path,
        display_name: displayName ?? null,
        created_at: new Date().toISOString(),
        usability: "usable",
      };
      this.favorites = [optimistic, ...this.favorites];
      try {
        const saved = await api().addFavorite({
          node_id: nodeId,
          path,
          display_name: displayName ?? null,
        });
        this.favorites = this.favorites.map((f) =>
          f.id === optimistic.id ? saved : f,
        );
        if (this.state === "empty") this.state = "success";
        return saved;
      } catch (caught) {
        // Roll back. Leaving the optimistic row would show a saved favourite the
        // server refused — the one outcome worse than the refusal itself.
        this.favorites = this.favorites.filter((f) => f.id !== optimistic.id);
        this.error = caught;
        return null;
      } finally {
        this.pending = this.pending.filter((k) => k !== key);
      }
    },

    /** Remove a favourite, restoring it in place if the delete fails. */
    async remove(id: string): Promise<boolean> {
      const index = this.favorites.findIndex((f) => f.id === id);
      if (index === -1) return false;
      const removed = this.favorites[index];
      const key = favoriteKey(removed.node_id, removed.path);
      if (this.pending.includes(key)) return false;
      this.pending.push(key);
      this.favorites = this.favorites.filter((f) => f.id !== id);
      try {
        await api().removeFavorite(id);
        if (this.favorites.length === 0 && this.recent.length === 0) {
          this.state = "empty";
        }
        return true;
      } catch (caught) {
        // Restored at its original index, so a failed delete does not silently
        // reorder the list the user is looking at.
        const restored = [...this.favorites];
        restored.splice(index, 0, removed);
        this.favorites = restored;
        this.error = caught;
        return false;
      } finally {
        this.pending = this.pending.filter((k) => k !== key);
      }
    },

    /** Toggle by `(node, path)`, which is what a star button actually knows. */
    async toggle(nodeId: string, path: string): Promise<void> {
      const existing = this.favoriteId(nodeId, path);
      if (existing === null) {
        await this.add(nodeId, path);
      } else {
        await this.remove(existing);
      }
    },

    /** Clear everything. Called on logout: favourites are per-user, so keeping
     * them across a user switch would show one person's paths to the next. */
    clear(): void {
      this.favorites = [];
      this.recent = [];
      this.state = "idle";
      this.error = null;
      this.pending = [];
      // Bumped, not reset: an in-flight load from the previous user must not be able
      // to repopulate the lists after the clear.
      this.loadSeq += 1;
    },
  },
});
