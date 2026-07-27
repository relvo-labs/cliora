import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../api/client";
import type { RecentWorkspace, WorkspaceFavorite } from "../api/dto";
import * as auth from "./auth";
import { useFavoritesStore } from "./favorites";

const NODE = "11111111-1111-1111-1111-111111111111";
const OTHER_NODE = "22222222-2222-2222-2222-222222222222";

function favorite(over: Partial<WorkspaceFavorite> = {}): WorkspaceFavorite {
  return {
    id: "fav-1",
    node_id: NODE,
    node_name: "vm",
    path: "/home/neil/projects/app",
    display_name: null,
    created_at: "2026-07-01T00:00:00Z",
    usability: "usable",
    ...over,
  };
}

function recent(over: Partial<RecentWorkspace> = {}): RecentWorkspace {
  return {
    node_id: NODE,
    node_name: "vm",
    path: "/home/neil/projects/app",
    last_used_at: "2026-07-01T00:00:00Z",
    node_online: true,
    node_enabled: true,
    ...over,
  };
}

interface Stubs {
  listFavorites?: ReturnType<typeof vi.fn>;
  listRecentWorkspaces?: ReturnType<typeof vi.fn>;
  addFavorite?: ReturnType<typeof vi.fn>;
  removeFavorite?: ReturnType<typeof vi.fn>;
}

function stubApi(stubs: Stubs): Required<Stubs> {
  const resolved = {
    listFavorites: stubs.listFavorites ?? vi.fn().mockResolvedValue([]),
    listRecentWorkspaces:
      stubs.listRecentWorkspaces ?? vi.fn().mockResolvedValue([]),
    addFavorite: stubs.addFavorite ?? vi.fn(),
    removeFavorite:
      stubs.removeFavorite ?? vi.fn().mockResolvedValue(undefined),
  };
  vi.spyOn(auth, "api").mockReturnValue(
    resolved as unknown as ReturnType<typeof auth.api>,
  );
  return resolved;
}

describe("useFavoritesStore", () => {
  beforeEach(() => setActivePinia(createPinia()));
  afterEach(() => vi.restoreAllMocks());

  // --- the five states ---

  it("reports empty when the user has neither favourites nor history", async () => {
    stubApi({});
    const store = useFavoritesStore();
    await store.load();
    expect(store.state).toBe("empty");
  });

  it("reports success when either list has entries", async () => {
    stubApi({ listRecentWorkspaces: vi.fn().mockResolvedValue([recent()]) });
    const store = useFavoritesStore();
    await store.load();
    expect(store.state).toBe("success");
  });

  it("treats a 403 as forbidden rather than a retryable error", async () => {
    // A Viewer has no `session.create`. Offering "retry" would promise something
    // that can never succeed, so the region hides itself instead.
    stubApi({
      listFavorites: vi
        .fn()
        .mockRejectedValue(new ApiError("FORBIDDEN", "no", 403)),
    });
    const store = useFavoritesStore();
    await store.load();
    expect(store.state).toBe("forbidden");
  });

  it("reports error for a failure that could plausibly clear", async () => {
    stubApi({
      listFavorites: vi
        .fn()
        .mockRejectedValue(new ApiError("INTERNAL", "boom", 500)),
    });
    const store = useFavoritesStore();
    await store.load();
    expect(store.state).toBe("error");
  });

  it("drops a superseded load rather than letting stale rows win", async () => {
    // The dialog reloads on every open. A slow first fetch landing after a faster
    // second one would replace the current rows — and their usability verdicts —
    // with older ones.
    let releaseFirst: (rows: WorkspaceFavorite[]) => void = () => {};
    const listFavorites = vi
      .fn()
      .mockImplementationOnce(
        () => new Promise<WorkspaceFavorite[]>((r) => (releaseFirst = r)),
      )
      .mockResolvedValueOnce([favorite({ id: "second" })]);
    stubApi({ listFavorites });
    const store = useFavoritesStore();

    const first = store.load();
    await store.load();
    expect(store.favorites.map((f) => f.id)).toEqual(["second"]);

    releaseFirst([favorite({ id: "first" })]);
    await first;

    expect(store.favorites.map((f) => f.id)).toEqual(["second"]);
  });

  it("does not let a superseded failure show an error over loaded rows", async () => {
    let rejectFirst: (error: unknown) => void = () => {};
    const listFavorites = vi
      .fn()
      .mockImplementationOnce(
        () =>
          new Promise<WorkspaceFavorite[]>(
            (_, reject) => (rejectFirst = reject),
          ),
      )
      .mockResolvedValueOnce([favorite()]);
    stubApi({ listFavorites });
    const store = useFavoritesStore();

    const first = store.load();
    await store.load();
    rejectFirst(new ApiError("INTERNAL", "boom", 500));
    await first;

    expect(store.state).toBe("success");
  });

  it("cannot be repopulated by a load that was in flight when it was cleared", async () => {
    let release: (rows: WorkspaceFavorite[]) => void = () => {};
    const listFavorites = vi.fn(
      () => new Promise<WorkspaceFavorite[]>((r) => (release = r)),
    );
    stubApi({ listFavorites });
    const store = useFavoritesStore();

    const pending = store.load();
    store.clear();
    release([favorite()]);
    await pending;

    // Otherwise signing out would be undone by a response still on the wire.
    expect(store.favorites).toEqual([]);
    expect(store.state).toBe("idle");
  });

  // --- optimistic add ---

  it("shows a new favourite immediately and replaces it with the stored row", async () => {
    let release: (value: WorkspaceFavorite) => void = () => {};
    const addFavorite = vi.fn(
      () => new Promise<WorkspaceFavorite>((resolve) => (release = resolve)),
    );
    stubApi({ addFavorite });
    const store = useFavoritesStore();

    const pending = store.add(NODE, "/home/neil/projects/app");
    // Visible before the server has answered — that is the point of the optimism.
    expect(store.isFavorite(NODE, "/home/neil/projects/app")).toBe(true);
    expect(store.isPending(NODE, "/home/neil/projects/app")).toBe(true);

    release(favorite({ id: "server-id" }));
    await pending;

    expect(store.favorites.map((f) => f.id)).toEqual(["server-id"]);
    expect(store.isPending(NODE, "/home/neil/projects/app")).toBe(false);
  });

  it("rolls the row back when the server refuses it", async () => {
    // The case that matters: a path outside an allowed root must not stay on screen
    // looking saved. That would be worse than the refusal itself.
    const refusal = new ApiError(
      "WORKSPACE_OUTSIDE_ALLOWED_ROOT",
      "outside",
      400,
    );
    stubApi({ addFavorite: vi.fn().mockRejectedValue(refusal) });
    const store = useFavoritesStore();

    const saved = await store.add(NODE, "/etc");

    expect(saved).toBeNull();
    expect(store.favorites).toEqual([]);
    expect(store.isFavorite(NODE, "/etc")).toBe(false);
    // Kept so the caller can render *why*.
    expect(store.error).toBe(refusal);
  });

  it("does not send a second request while one is in flight for the same path", async () => {
    let release: (value: WorkspaceFavorite) => void = () => {};
    const addFavorite = vi.fn(
      () => new Promise<WorkspaceFavorite>((resolve) => (release = resolve)),
    );
    stubApi({ addFavorite });
    const store = useFavoritesStore();

    const first = store.add(NODE, "/home/neil/projects/app");
    const second = await store.add(NODE, "/home/neil/projects/app");

    expect(second).toBeNull();
    expect(addFavorite).toHaveBeenCalledTimes(1);
    release(favorite());
    await first;
  });

  it("returns the existing row instead of duplicating an already-saved path", async () => {
    const addFavorite = vi.fn();
    stubApi({
      listFavorites: vi.fn().mockResolvedValue([favorite()]),
      addFavorite,
    });
    const store = useFavoritesStore();
    await store.load();

    const again = await store.add(NODE, "/home/neil/projects/app");

    expect(again?.id).toBe("fav-1");
    expect(addFavorite).not.toHaveBeenCalled();
    expect(store.favorites).toHaveLength(1);
  });

  it("leaves empty behind once the first favourite is saved", async () => {
    stubApi({ addFavorite: vi.fn().mockResolvedValue(favorite()) });
    const store = useFavoritesStore();
    await store.load();
    expect(store.state).toBe("empty");
    await store.add(NODE, "/home/neil/projects/app");
    expect(store.state).toBe("success");
  });

  // --- optimistic remove ---

  it("restores a failed removal at its original position", async () => {
    // Reordering the list under the user would make a transient failure look like a
    // successful change to something else.
    const rows = [
      favorite({ id: "a", path: "/home/neil/projects/a" }),
      favorite({ id: "b", path: "/home/neil/projects/b" }),
      favorite({ id: "c", path: "/home/neil/projects/c" }),
    ];
    stubApi({
      listFavorites: vi.fn().mockResolvedValue(rows),
      removeFavorite: vi
        .fn()
        .mockRejectedValue(new ApiError("INTERNAL", "boom", 500)),
    });
    const store = useFavoritesStore();
    await store.load();

    const removed = await store.remove("b");

    expect(removed).toBe(false);
    expect(store.favorites.map((f) => f.id)).toEqual(["a", "b", "c"]);
  });

  it("removes a favourite and falls back to empty when it was the last one", async () => {
    stubApi({ listFavorites: vi.fn().mockResolvedValue([favorite()]) });
    const store = useFavoritesStore();
    await store.load();

    expect(await store.remove("fav-1")).toBe(true);
    expect(store.favorites).toEqual([]);
    expect(store.state).toBe("empty");
  });

  it("ignores a removal of something it does not hold", async () => {
    const removeFavorite = vi.fn();
    stubApi({ removeFavorite });
    const store = useFavoritesStore();
    expect(await store.remove("nope")).toBe(false);
    expect(removeFavorite).not.toHaveBeenCalled();
  });

  it("toggles on and back off through the same (node, path) key", async () => {
    const stubs = stubApi({
      addFavorite: vi.fn().mockResolvedValue(favorite({ id: "server-id" })),
    });
    const store = useFavoritesStore();

    await store.toggle(NODE, "/home/neil/projects/app");
    expect(store.isFavorite(NODE, "/home/neil/projects/app")).toBe(true);

    await store.toggle(NODE, "/home/neil/projects/app");
    expect(store.isFavorite(NODE, "/home/neil/projects/app")).toBe(false);
    expect(stubs.removeFavorite).toHaveBeenCalledWith("server-id");
  });

  // --- scoping and usability ---

  it("scopes both lists to the selected node", async () => {
    stubApi({
      listFavorites: vi
        .fn()
        .mockResolvedValue([
          favorite({ id: "a" }),
          favorite({ id: "b", node_id: OTHER_NODE }),
        ]),
      listRecentWorkspaces: vi
        .fn()
        .mockResolvedValue([recent(), recent({ node_id: OTHER_NODE })]),
    });
    const store = useFavoritesStore();
    await store.load();

    expect(store.favoritesForNode(NODE).map((f) => f.id)).toEqual(["a"]);
    expect(store.recentForNode(OTHER_NODE)).toHaveLength(1);
  });

  it("keeps unusable favourites in the list while excluding them from the usable set", async () => {
    // Silently dropping them would make "my favourite vanished" the user's
    // experience of a disabled node.
    stubApi({
      listFavorites: vi
        .fn()
        .mockResolvedValue([
          favorite({ id: "ok" }),
          favorite({ id: "off", usability: "node_offline" }),
          favorite({ id: "gone", usability: "outside_allowed_root" }),
        ]),
    });
    const store = useFavoritesStore();
    await store.load();

    expect(store.favorites).toHaveLength(3);
    expect(store.usableFavorites.map((f) => f.id)).toEqual(["ok"]);
  });

  it("does not carry one user's paths into the next session", async () => {
    stubApi({
      listFavorites: vi.fn().mockResolvedValue([favorite()]),
      listRecentWorkspaces: vi.fn().mockResolvedValue([recent()]),
    });
    const store = useFavoritesStore();
    await store.load();

    store.clear();

    expect(store.favorites).toEqual([]);
    expect(store.recent).toEqual([]);
    expect(store.state).toBe("idle");
    expect(store.error).toBeNull();
  });
});
