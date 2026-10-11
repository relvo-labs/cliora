import { createPinia, setActivePinia } from "pinia";
import { flushPromises } from "@vue/test-utils";
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import type {
  CreateSessionInput,
  SessionDetail,
  SessionSummary,
} from "../api/dto";
import * as auth from "./auth";
import { useSessionsStore } from "./sessions";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}
const detail = (id: string) => ({ id }) as SessionDetail;
const terminated = (id: string) =>
  ({ id, status: "terminated" }) as SessionDetail;
beforeEach(() => setActivePinia(createPinia()));
afterEach(() => vi.restoreAllMocks());

describe("#79 session request generation", () => {
  it("A → B → C answered C, B, A keeps only C current", async () => {
    const held = [
      deferred<SessionDetail>(),
      deferred<SessionDetail>(),
      deferred<SessionDetail>(),
    ];
    vi.spyOn(auth, "api").mockReturnValue({
      getSession: vi
        .fn()
        .mockReturnValueOnce(held[0].promise)
        .mockReturnValueOnce(held[1].promise)
        .mockReturnValueOnce(held[2].promise),
    } as never);
    const store = useSessionsStore();
    const requests = [
      store.fetchSession("A"),
      store.fetchSession("B"),
      store.fetchSession("C"),
    ];
    for (const i of [2, 1, 0]) {
      held[i].resolve(detail(["A", "B", "C"][i]));
      await requests[i];
      expect(store.current?.id).toBe("C");
    }
  });

  it("reset invalidates pending detail and termination replies", async () => {
    const fetch = deferred<SessionDetail>();
    const end = deferred<SessionDetail>();
    vi.spyOn(auth, "api").mockReturnValue({
      getSession: () => fetch.promise,
      terminateSession: () => end.promise,
    } as never);
    const store = useSessionsStore();
    store.current = detail("A");
    const loading = store.fetchSession("A");
    const ending = store.terminate("A");
    store.reset();
    fetch.resolve(detail("A"));
    end.resolve(detail("A"));
    await Promise.all([loading, ending]);
    expect(store.current).toBeNull();
  });

  it("late termination of A cannot overwrite loaded C", async () => {
    const end = deferred<SessionDetail>();
    vi.spyOn(auth, "api").mockReturnValue({
      getSession: async (id: string) => detail(id),
      terminateSession: () => end.promise,
    } as never);
    const store = useSessionsStore();
    await store.fetchSession("A");
    const ending = store.terminate("A");
    await store.fetchSession("C");
    end.resolve(detail("A"));
    await ending;
    expect(store.current?.id).toBe("C");
  });
});

describe("T2 terminate acceptance after returning to A", () => {
  it("a successful termination updates A after A -> B -> A", async () => {
    const end = deferred<SessionDetail>();
    const getSession = vi.fn(async (id: string) => ({ id, status: "running" }));
    vi.spyOn(auth, "api").mockReturnValue({
      getSession,
      terminateSession: () => end.promise,
    } as never);
    const store = useSessionsStore();
    await store.fetchSession("A");
    const ending = store.terminate("A");
    await store.fetchSession("B");
    await store.fetchSession("A");
    getSession.mockResolvedValueOnce(terminated("A"));
    end.resolve(terminated("A"));
    await ending;
    expect(store.current?.id).toBe("A");
    expect(store.current?.status).toBe("terminated");
  });
});

describe("Repair 1 store continuation ownership", () => {
  it("a pre-termination detail cannot undo a successful mutation", async () => {
    const fetch = deferred<SessionDetail>();
    vi.spyOn(auth, "api").mockReturnValue({
      getSession: vi
        .fn()
        .mockReturnValueOnce(fetch.promise)
        .mockResolvedValue(terminated("A")),
      terminateSession: async () => ({ id: "A", status: "terminated" }),
    } as never);
    const store = useSessionsStore();
    store.current = { id: "A", status: "running" } as SessionDetail;
    const loading = store.fetchSession("A");
    await store.terminate("A");
    fetch.resolve({ id: "A", status: "running" } as SessionDetail);
    await loading;
    expect(store.current?.status).toBe("terminated");
  });

  it("terminating displayed A cannot invalidate a pending fetch of B", async () => {
    const fetch = deferred<SessionDetail>();
    vi.spyOn(auth, "api").mockReturnValue({
      getSession: () => fetch.promise,
      terminateSession: async () => ({ id: "A", status: "terminated" }),
    } as never);
    const store = useSessionsStore();
    store.current = detail("A");
    const loading = store.fetchSession("B");
    await store.terminate("A");
    fetch.resolve(detail("B"));
    await loading;
    expect(store.current?.id).toBe("B");
  });

  it("a pre-reset mutation cannot alter a reloaded A or its new list", async () => {
    const end = deferred<SessionDetail>();
    vi.spyOn(auth, "api").mockReturnValue({
      getSession: async (id: string) => ({ id, status: "running" }),
      terminateSession: () => end.promise,
    } as never);
    const store = useSessionsStore();
    await store.fetchSession("A");
    const ending = store.terminate("A");
    store.reset();
    await store.fetchSession("A");
    store.list = [{ id: "A", status: "running" } as SessionSummary];
    end.resolve({ id: "A", status: "terminated" } as SessionDetail);
    await ending;
    expect(store.current?.status).toBe("running");
    expect(store.list[0].status).toBe("running");
  });

  it("a reset rejects pending list and create writes", async () => {
    const list = deferred<SessionSummary[]>();
    const created = deferred<SessionDetail>();
    vi.spyOn(auth, "api").mockReturnValue({
      listSessions: () => list.promise,
      createSession: () => created.promise,
    } as never);
    const store = useSessionsStore();
    const listing = store.fetchList();
    const creating = store.create({} as CreateSessionInput);
    store.reset();
    list.resolve([{ id: "A" } as SessionSummary]);
    created.resolve(detail("A"));
    await Promise.all([listing, creating]);
    expect(store.list).toEqual([]);
    expect(store.current).toBeNull();
  });

  it("an older list cannot replace the latest list", async () => {
    const old = deferred<SessionSummary[]>();
    vi.spyOn(auth, "api").mockReturnValue({
      listSessions: vi
        .fn()
        .mockReturnValueOnce(old.promise)
        .mockResolvedValueOnce([{ id: "B" }]),
    } as never);
    const store = useSessionsStore();
    const first = store.fetchList();
    await store.fetchList();
    old.resolve([{ id: "A" } as SessionSummary]);
    await first;
    expect(store.list[0].id).toBe("B");
  });

  it("a create reply cannot replace a later workspace fetch", async () => {
    const created = deferred<SessionDetail>();
    vi.spyOn(auth, "api").mockReturnValue({
      createSession: () => created.promise,
      getSession: async (id: string) => detail(id),
    } as never);
    const store = useSessionsStore();
    const creating = store.create({} as CreateSessionInput);
    await store.fetchSession("C");
    created.resolve(detail("A"));
    await creating;
    expect(store.current?.id).toBe("C");
  });
});

describe("Repair 1 list mutation ordering", () => {
  it("an older list cannot undo a successful termination", async () => {
    const list = deferred<SessionSummary[]>();
    vi.spyOn(auth, "api").mockReturnValue({
      listSessions: vi
        .fn()
        .mockReturnValueOnce(list.promise)
        .mockResolvedValue([terminated("A")]),
      terminateSession: async () => ({ id: "A", status: "terminated" }),
    } as never);
    const store = useSessionsStore();
    store.current = detail("A");
    store.list = [{ id: "A", status: "running" } as SessionSummary];
    const listing = store.fetchList();
    await store.terminate("A");
    list.resolve([{ id: "A", status: "running" } as SessionSummary]);
    await listing;
    expect(store.list[0].status).toBe("terminated");
  });
});

describe("T2 closure delta interleavings", () => {
  it("return-to-A detail still pending accepts A's successful termination", async () => {
    const ending = deferred<SessionDetail>();
    const returning = deferred<SessionDetail>();
    const getSession = vi
      .fn()
      .mockResolvedValueOnce({ id: "A", status: "running" })
      .mockResolvedValueOnce({ id: "B", status: "running" })
      .mockReturnValueOnce(returning.promise)
      .mockResolvedValue(terminated("A"));
    vi.spyOn(auth, "api").mockReturnValue({
      getSession,
      terminateSession: () => ending.promise,
    } as never);
    const store = useSessionsStore();
    await store.fetchSession("A");
    const end = store.terminate("A");
    await store.fetchSession("B");
    const back = store.fetchSession("A");
    ending.resolve({ id: "A", status: "terminated" } as SessionDetail);
    await end;
    returning.resolve({ id: "A", status: "running" } as SessionDetail);
    await back;
    expect(store.current?.id).toBe("A");
    expect(store.current?.status).toBe("terminated");
  });
  it("termination cannot discard the current list's first successful load", async () => {
    const ending = deferred<SessionDetail>();
    const listing = deferred<SessionSummary[]>();
    vi.spyOn(auth, "api").mockReturnValue({
      getSession: async () => ({ id: "A", status: "running" }),
      terminateSession: () => ending.promise,
      listSessions: () => listing.promise,
    } as never);
    const store = useSessionsStore();
    await store.fetchSession("A");
    const end = store.terminate("A");
    const list = store.fetchList();
    ending.resolve({ id: "A", status: "terminated" } as SessionDetail);
    await end;
    listing.resolve([
      { id: "A", status: "terminated" },
      { id: "B", status: "running" },
    ] as SessionSummary[]);
    await list;
    expect(store.list.map((row) => row.id)).toEqual(["A", "B"]);
  });
});

describe("Repair 2 termination reads (server refetch contract)", () => {
  const ended = (id: string) =>
    ({
      id,
      name: "termination payload",
      status: "terminated",
      capabilities: { can_terminate: false, can_view: true },
    }) as SessionDetail;

  it("refreshes the first list with all server rows and leaves old returned payloads unchanged", async () => {
    const old = deferred<SessionSummary[]>();
    const fresh = deferred<SessionSummary[]>();
    const listSessions = vi
      .fn()
      .mockReturnValueOnce(old.promise)
      .mockReturnValueOnce(fresh.promise);
    const getSession = vi.fn().mockResolvedValue(ended("A"));
    vi.spyOn(auth, "api").mockReturnValue({
      listSessions,
      getSession,
      terminateSession: async () => ended("A"),
    } as never);
    const store = useSessionsStore();
    store.current = detail("B");
    const load = store.fetchList();
    await store.terminate("A");
    const b = { ...detail("B"), name: "unaffected" };
    const rows = [b, ended("A")];
    fresh.resolve(rows);
    await flushPromises();
    old.resolve([b, { ...detail("A"), status: "running" }]);
    expect(await load).toEqual([b, { ...detail("A"), status: "running" }]);
    expect(store.current?.id).toBe("B");
    expect(store.list).toEqual(rows);
    expect(listSessions).toHaveBeenCalledTimes(2);
    expect(getSession).toHaveBeenCalledExactlyOnceWith("A");
  });

  it("trusts detail and list reads started after the termination", async () => {
    const fresh = {
      ...ended("A"),
      name: "fresh authorized read",
      capabilities: { ...ended("A").capabilities, can_view: false },
    };
    vi.spyOn(auth, "api").mockReturnValue({
      getSession: async () => fresh,
      listSessions: async () => [fresh],
      terminateSession: async () => ended("A"),
    } as never);
    const store = useSessionsStore();
    await store.terminate("A");
    expect(await store.fetchSession("A")).toEqual(fresh);
    expect(await store.fetchList()).toEqual([fresh]);
    expect(store.current).toEqual(fresh);
    expect(store.list).toEqual([fresh]);
  });

  it("two terminations each refresh once and the newest server list wins", async () => {
    const held = Array.from({ length: 4 }, () => deferred<SessionSummary[]>());
    const listSessions = vi.fn();
    for (const load of held) listSessions.mockReturnValueOnce(load.promise);
    vi.spyOn(auth, "api").mockReturnValue({
      listSessions,
      getSession: async (id: string) => ended(id),
      terminateSession: async (id: string) => ended(id),
    } as never);
    const store = useSessionsStore();
    const first = store.fetchList();
    const second = store.fetchList();
    await store.terminate("A");
    await store.terminate("B");
    const freshA = {
      ...ended("A"),
      name: "fresh authorized read",
      capabilities: { ...ended("A").capabilities, can_view: false },
    };
    const rows = [freshA, ended("B"), detail("C")];
    held[3].resolve(rows);
    await flushPromises();
    held[2].resolve([ended("A"), detail("B")]);
    held[1].resolve([detail("B")]);
    held[0].resolve([detail("A"), detail("B")]);
    await Promise.all([first, second]);
    await flushPromises();
    expect(store.list).toEqual(rows);
    expect(listSessions).toHaveBeenCalledTimes(4);
  });

  it("a superseded detail and A's fresh termination read cannot replace workspace C", async () => {
    const old = deferred<SessionDetail>();
    const refresh = deferred<SessionDetail>();
    const getSession = vi
      .fn()
      .mockReturnValueOnce(old.promise)
      .mockResolvedValueOnce(detail("C"))
      .mockReturnValueOnce(refresh.promise);
    vi.spyOn(auth, "api").mockReturnValue({
      getSession,
      terminateSession: async () => ended("A"),
    } as never);
    const store = useSessionsStore();
    const first = store.fetchSession("A");
    await store.fetchSession("C");
    await store.terminate("A");
    refresh.resolve(ended("A"));
    old.resolve(detail("A"));
    expect(await first).toEqual(detail("A"));
    await flushPromises();
    expect(store.current?.id).toBe("C");
    expect(getSession.mock.calls).toEqual([["A"], ["C"], ["A"]]);
  });

  it("reset isolates accepted mutation refreshes and old replies from new same-id reads", async () => {
    const old = deferred<SessionDetail>();
    const refresh = deferred<SessionDetail>();
    const listRefresh = deferred<SessionSummary[]>();
    vi.spyOn(auth, "api").mockReturnValue({
      getSession: vi
        .fn()
        .mockReturnValueOnce(old.promise)
        .mockReturnValueOnce(refresh.promise)
        .mockResolvedValue(detail("A")),
      listSessions: vi
        .fn()
        .mockResolvedValueOnce([detail("A")])
        .mockReturnValueOnce(listRefresh.promise)
        .mockResolvedValue([detail("A")]),
      terminateSession: async () => ended("A"),
    } as never);
    const store = useSessionsStore();
    const first = store.fetchSession("A");
    await store.fetchList();
    await store.terminate("A");
    store.reset();
    await store.fetchSession("A");
    await store.fetchList();
    refresh.resolve(ended("A"));
    listRefresh.resolve([ended("A")]);
    old.resolve({ ...detail("A"), name: "old identity reply" });
    expect(await first).toEqual({ ...detail("A"), name: "old identity reply" });
    await flushPromises();
    expect(store.current).toEqual(detail("A"));
    expect(store.list).toEqual([detail("A")]);
  });

  it("a refused termination leaves pending successful reads intact without refetching", async () => {
    const listing = deferred<SessionSummary[]>();
    const fetching = deferred<SessionDetail>();
    const listSessions = vi.fn(() => listing.promise);
    const getSession = vi.fn(() => fetching.promise);
    vi.spyOn(auth, "api").mockReturnValue({
      listSessions,
      getSession,
      terminateSession: async () => {
        throw new Error("refused");
      },
    } as never);
    const store = useSessionsStore();
    const list = store.fetchList();
    const fetch = store.fetchSession("A");
    await expect(store.terminate("A")).rejects.toThrow("refused");
    listing.resolve([detail("A"), detail("B")]);
    fetching.resolve(detail("A"));
    await Promise.all([list, fetch]);
    expect(store.list).toEqual([detail("A"), detail("B")]);
    expect(store.current).toEqual(detail("A"));
    expect(listSessions).toHaveBeenCalledTimes(1);
    expect(getSession).toHaveBeenCalledTimes(1);
  });

  it("preserves filters and does not insert rows absent from the refreshed server list", async () => {
    const old = deferred<SessionSummary[]>();
    const listSessions = vi
      .fn()
      .mockReturnValueOnce(old.promise)
      .mockResolvedValue([detail("B")]);
    vi.spyOn(auth, "api").mockReturnValue({
      listSessions,
      getSession: async () => ended("A"),
      terminateSession: async () => ended("A"),
    } as never);
    const store = useSessionsStore();
    const params = { status: "running", node_id: "node" };
    const load = store.fetchList(params);
    params.status = "terminated";
    await store.terminate("A");
    old.resolve([detail("B")]);
    expect(await load).toEqual([detail("B")]);
    await flushPromises();
    expect(store.list).toEqual([detail("B")]);
    expect(listSessions.mock.calls).toEqual([
      [{ status: "running", node_id: "node" }],
      [{ status: "running", node_id: "node" }],
    ]);
  });
});

describe("Repair 3 refresh ownership and failures", () => {
  it("failed refreshes preserve the accepted current/list and do not retry", async () => {
    const old = deferred<SessionDetail>();
    const getSession = vi
      .fn()
      .mockResolvedValueOnce(detail("A"))
      .mockReturnValueOnce(old.promise)
      .mockRejectedValue(new Error("refresh unavailable"));
    const listSessions = vi
      .fn()
      .mockResolvedValueOnce([detail("A"), detail("B")])
      .mockRejectedValue(new Error("refresh unavailable"));
    vi.spyOn(auth, "api").mockReturnValue({
      getSession,
      listSessions,
      terminateSession: async () => terminated("A"),
    } as never);
    const store = useSessionsStore();
    await store.fetchSession("A");
    await store.fetchList();
    const load = store.fetchSession("A");
    await store.terminate("A");
    await flushPromises();
    old.resolve({ ...detail("A"), status: "running" });
    await load;
    expect(store.current).toEqual(terminated("A"));
    expect(store.list).toEqual([terminated("A"), detail("B")]);
    expect(getSession).toHaveBeenCalledTimes(3);
    expect(listSessions).toHaveBeenCalledTimes(2);
  });

  it("navigation to C supersedes a held A refresh", async () => {
    const refresh = deferred<SessionDetail>();
    vi.spyOn(auth, "api").mockReturnValue({
      getSession: vi
        .fn()
        .mockResolvedValueOnce(detail("A"))
        .mockReturnValueOnce(refresh.promise)
        .mockResolvedValueOnce(detail("C")),
      terminateSession: async () => terminated("A"),
    } as never);
    const store = useSessionsStore();
    await store.fetchSession("A");
    await store.terminate("A");
    await store.fetchSession("C");
    refresh.resolve(terminated("A"));
    await flushPromises();
    expect(store.current).toEqual(detail("C"));
  });

  it("an A refresh does not supersede a pending create", async () => {
    const created = deferred<SessionDetail>();
    const refresh = deferred<SessionDetail>();
    vi.spyOn(auth, "api").mockReturnValue({
      getSession: vi
        .fn()
        .mockResolvedValueOnce(detail("A"))
        .mockReturnValueOnce(refresh.promise),
      createSession: () => created.promise,
      terminateSession: async () => terminated("A"),
    } as never);
    const store = useSessionsStore();
    await store.fetchSession("A");
    const creating = store.create({} as CreateSessionInput);
    await store.terminate("A");
    created.resolve(detail("new"));
    await creating;
    refresh.resolve(terminated("A"));
    await flushPromises();
    expect(store.current).toEqual(detail("new"));
  });

  it("refreshes the latest list params when an older request is pending after the latest fails", async () => {
    const old = deferred<SessionSummary[]>();
    const listSessions = vi
      .fn()
      .mockReturnValueOnce(old.promise)
      .mockRejectedValueOnce(new Error("latest failed"))
      .mockResolvedValueOnce([detail("B")]);
    vi.spyOn(auth, "api").mockReturnValue({
      listSessions,
      getSession: async () => terminated("A"),
      terminateSession: async () => terminated("A"),
    } as never);
    const store = useSessionsStore();
    const first = store.fetchList({ node_id: "old" });
    await expect(
      store.fetchList({ node_id: "latest", status: "running" }),
    ).rejects.toThrow("latest failed");
    await store.terminate("A");
    old.resolve([detail("A")]);
    await first;
    await flushPromises();
    expect(store.list).toEqual([detail("B")]);
    expect(listSessions.mock.calls[2]).toEqual([
      { node_id: "latest", status: "running" },
    ]);
  });

  it("a newer list after termination wins over the held refresh and preserves its own filters", async () => {
    const refresh = deferred<SessionSummary[]>();
    const listSessions = vi
      .fn()
      .mockResolvedValueOnce([detail("A")])
      .mockReturnValueOnce(refresh.promise)
      .mockResolvedValueOnce([detail("C")]);
    vi.spyOn(auth, "api").mockReturnValue({
      listSessions,
      getSession: async () => terminated("A"),
      terminateSession: async () => terminated("A"),
    } as never);
    const store = useSessionsStore();
    await store.fetchList({ node_id: "old" });
    await store.terminate("A");
    await store.fetchList({ node_id: "new", status: "running" });
    refresh.resolve([terminated("A")]);
    await flushPromises();
    expect(store.list).toEqual([detail("C")]);
    expect(listSessions.mock.calls).toEqual([
      [{ node_id: "old" }],
      [{ node_id: "old" }],
      [{ node_id: "new", status: "running" }],
    ]);
  });

  it("reset removes old list eligibility and stale termination issues no reads", async () => {
    const end = deferred<SessionDetail>();
    const getSession = vi.fn().mockResolvedValue(terminated("A"));
    const listSessions = vi.fn().mockResolvedValue([detail("A")]);
    const terminateSession = vi
      .fn()
      .mockReturnValueOnce(end.promise)
      .mockResolvedValue(terminated("A"));
    vi.spyOn(auth, "api").mockReturnValue({
      getSession,
      listSessions,
      terminateSession,
    } as never);
    const store = useSessionsStore();
    await store.fetchList();
    const ending = store.terminate("A");
    store.reset();
    end.resolve(terminated("A"));
    await ending;
    expect(getSession).not.toHaveBeenCalled();
    await store.terminate("A");
    await flushPromises();
    expect(getSession).toHaveBeenCalledExactlyOnceWith("A");
    expect(listSessions).toHaveBeenCalledTimes(1);
    expect(store.current).toBeNull();
    expect(store.list).toEqual([]);
  });
});
