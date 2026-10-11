import { createPinia, setActivePinia } from "pinia";
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
    vi.spyOn(auth, "api").mockReturnValue({
      getSession: async (id: string) => ({ id, status: "running" }),
      terminateSession: () => end.promise,
    } as never);
    const store = useSessionsStore();
    await store.fetchSession("A");
    const ending = store.terminate("A");
    await store.fetchSession("B");
    await store.fetchSession("A");
    end.resolve({ id: "A", status: "terminated" } as SessionDetail);
    await ending;
    expect(store.current?.id).toBe("A");
    expect(store.current?.status).toBe("terminated");
  });
});

describe("Repair 1 store continuation ownership", () => {
  it("a pre-termination detail cannot undo a successful mutation", async () => {
    const fetch = deferred<SessionDetail>();
    vi.spyOn(auth, "api").mockReturnValue({
      getSession: () => fetch.promise,
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
      listSessions: () => list.promise,
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
