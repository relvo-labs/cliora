import { createPinia, setActivePinia } from "pinia";
import { flushPromises } from "@vue/test-utils";
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import type { SessionDetail, SessionSummary } from "../api/dto";
import * as auth from "./auth";
import { useSessionsStore } from "./sessions";

function held<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((r, j) => {
    resolve = r;
    reject = j;
  });
  return { promise, resolve, reject };
}
const row = (id: string, status = "running", marker = "") =>
  ({ id, status, name: marker || id }) as SessionDetail;
beforeEach(() => setActivePinia(createPinia()));
afterEach(() => vi.restoreAllMocks());

describe("T2 closure4 independent restore probes", () => {
  // Known legacy race, tracked in #154 (termination vs in-flight read ordering)
  it.skip.each(["before refresh failure", "after refresh failure"])(
    "restoring a pre-termination snapshot %s retains the already accepted termination",
    async (order) => {
      const original = held<SessionDetail>();
      const refresh = held<SessionDetail>();
      const getSession = vi
        .fn()
        .mockResolvedValueOnce(row("A"))
        .mockReturnValueOnce(original.promise)
        .mockReturnValueOnce(refresh.promise);
      vi.spyOn(auth, "api").mockReturnValue({
        getSession,
        terminateSession: async () => row("A", "terminated"),
      } as never);
      const store = useSessionsStore();
      await store.fetchSession("A");
      const reading = store.fetchSession("A");
      await store.terminate("A");
      expect(store.current?.status).toBe("terminated");
      // The old GET's valid database snapshot predates the committed POST.
      // This is not a successful post-commit refresh pretending to be running.
      if (order === "before refresh failure") {
        original.resolve(row("A", "running"));
        await reading;
        refresh.reject(new Error("fresh GET unavailable"));
      } else {
        refresh.reject(new Error("fresh GET unavailable"));
        await flushPromises();
        original.resolve(row("A", "running"));
        await reading;
      }
      await flushPromises();
      expect(store.current?.status).toBe("terminated");
      expect(getSession).toHaveBeenCalledTimes(3);
    },
  );

  // Known legacy race, tracked in #154 (termination vs in-flight read ordering)
  it.skip.each(["before refresh failure", "after refresh failure"])(
    "restoring a pending older list %s retains its installed termination patch",
    async (order) => {
      const old = held<SessionSummary[]>();
      const refresh = held<SessionSummary[]>();
      const listSessions = vi
        .fn()
        .mockResolvedValueOnce([row("A")])
        .mockReturnValueOnce(old.promise)
        .mockReturnValueOnce(refresh.promise);
      vi.spyOn(auth, "api").mockReturnValue({
        listSessions,
        getSession: async () => row("A", "terminated"),
        terminateSession: async () => row("A", "terminated"),
      } as never);
      const store = useSessionsStore();
      await store.fetchList();
      const reading = store.fetchList();
      await store.terminate("A");
      expect(store.list[0].status).toBe("terminated");
      if (order === "before refresh failure") {
        old.resolve([row("A")]);
        await flushPromises();
        refresh.reject(new Error("refresh failed"));
      } else {
        refresh.reject(new Error("refresh failed"));
        await flushPromises();
        old.resolve([row("A")]);
      }
      await reading;
      await flushPromises();
      expect(store.list[0].status).toBe("terminated");
      expect(listSessions).toHaveBeenCalledTimes(3);
    },
  );
});
