import { createPinia, setActivePinia } from "pinia";
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import type { SessionDetail } from "../api/dto";
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
