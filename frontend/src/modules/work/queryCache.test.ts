import { effectScope, nextTick } from "vue";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  COUNTS_POLL_MS,
  CountsPoller,
  QueryCache,
  countsDiffer,
  keyHasPrefix,
  keys,
  serialiseKey,
} from "./queryCache";

describe("serialiseKey: property order cannot change the answer", () => {
  it("treats the same question asked two ways as one entry", () => {
    // **The most load-bearing function in the file.** Without this, a board and its
    // toolbar asking the same query with the object literal written differently get two
    // cache entries — two requests, two answers, and a column count that disagrees with
    // the column.
    expect(
      serialiseKey(["work-items", "p1", { group: "lifecycle", limit: 50 }]),
    ).toBe(
      serialiseKey(["work-items", "p1", { limit: 50, group: "lifecycle" }]),
    );
  });

  it("normalises an explicit undefined to an absent key", () => {
    expect(serialiseKey(["k", { a: 1, b: undefined }])).toBe(
      serialiseKey(["k", { a: 1 }]),
    );
  });

  it("keeps different questions apart", () => {
    expect(serialiseKey(["work-items", "p1", {}])).not.toBe(
      serialiseKey(["work-items", "p2", {}]),
    );
  });

  it("does not confuse an array with an object", () => {
    expect(serialiseKey(["k", ["a"] as never])).not.toBe(
      serialiseKey(["k", { 0: "a" }]),
    );
  });
});

describe("keyHasPrefix", () => {
  it("matches a leading segment and rejects a longer prefix", () => {
    const key = keys.workItems("p1", { group: "lifecycle" });
    expect(keyHasPrefix(key, ["work-items"])).toBe(true);
    expect(keyHasPrefix(key, ["work-items", "p1"])).toBe(true);
    expect(keyHasPrefix(key, ["work-items", "p2"])).toBe(false);
    expect(keyHasPrefix(["work-items"], ["work-items", "p1"])).toBe(false);
  });
});

describe("QueryCache", () => {
  let cache: QueryCache;
  let clock: number;

  beforeEach(() => {
    clock = 1_000;
    cache = new QueryCache({ staleAfterMs: 100, now: () => clock });
  });

  it("serves a fresh entry without calling the loader again", async () => {
    const loader = vi.fn().mockResolvedValue("first");
    expect(await cache.fetch(["k"], loader)).toBe("first");
    expect(await cache.fetch(["k"], loader)).toBe("first");
    expect(loader).toHaveBeenCalledTimes(1);
  });

  it("refetches once the entry is stale", async () => {
    const loader = vi.fn().mockResolvedValue("v");
    await cache.fetch(["k"], loader);
    clock += 101;
    await cache.fetch(["k"], loader);
    expect(loader).toHaveBeenCalledTimes(2);
  });

  it("gives two concurrent callers the same promise, not two requests", async () => {
    // Mounting a board and its toolbar in the same tick is otherwise two identical
    // queries — and at the counts endpoint's polling rate that doubles the hottest
    // request in the phase.
    let release: (value: string) => void = () => {};
    const loader = vi.fn(
      () => new Promise<string>((resolve) => (release = resolve)),
    );
    const first = cache.fetch(["k"], loader);
    const second = cache.fetch(["k"], loader);
    expect(loader).toHaveBeenCalledTimes(1);
    release("shared");
    expect(await first).toBe("shared");
    expect(await second).toBe("shared");
  });

  it("keeps the previous data when a refresh fails", async () => {
    // A failed refresh must not blank a board that was on screen a second ago. The
    // component decides whether to show stale data with a warning or the error.
    const loader = vi
      .fn()
      .mockResolvedValueOnce("good")
      .mockRejectedValueOnce(new Error("network"));
    await cache.fetch(["k"], loader);
    clock += 101;
    await expect(cache.fetch(["k"], loader)).rejects.toThrow("network");
    const entry = cache.peek<string>(["k"]);
    expect(entry?.data).toBe("good");
    expect(entry?.error).toBeInstanceOf(Error);
  });

  it("invalidates by prefix and reports how many entries went", async () => {
    // The count is returned because a mutation that invalidated nothing is usually a key
    // mismatch, and that is otherwise completely silent.
    await cache.fetch(
      keys.workItems("p1", { group: "lifecycle" }),
      async () => 1,
    );
    await cache.fetch(keys.workItems("p1", { group: "owner" }), async () => 2);
    await cache.fetch(
      keys.workItems("p2", { group: "lifecycle" }),
      async () => 3,
    );
    expect(cache.invalidate(keys.project("p1"))).toBe(2);
    expect(cache.peek(keys.workItems("p2", { group: "lifecycle" }))?.data).toBe(
      3,
    );
  });

  it("rolls back before the caller sees the failure", async () => {
    const board = { stage: "backlog" };
    await expect(
      cache.mutate(
        async () => {
          throw new Error("409");
        },
        {
          apply: () => (board.stage = "ready"),
          rollback: () => (board.stage = "backlog"),
        },
      ),
    ).rejects.toThrow("409");
    // Already back by the time the rejection surfaced: a card that stays in its new lane
    // after a refusal is a card the user believes moved.
    expect(board.stage).toBe("backlog");
  });

  it("invalidates only what the mutation names", async () => {
    await cache.fetch(keys.workCounts("p1", {}), async () => ({ total: 1 }));
    await cache.fetch(keys.task("t1"), async () => ({ id: "t1" }));
    await cache.mutate(async () => "ok", {
      apply: () => {},
      rollback: () => {},
      invalidate: [keys.task("t1")],
    });
    expect(cache.peek(keys.task("t1"))).toBeUndefined();
    expect(cache.peek(keys.workCounts("p1", {}))?.data).toEqual({ total: 1 });
  });

  it("exposes a reactive handle that follows invalidation", async () => {
    const scope = effectScope();
    await scope.run(async () => {
      const handle = cache.query(["k"], async () => "value");
      await handle.load();
      expect(handle.data.value).toBe("value");
      cache.invalidate(["k"]);
      await nextTick();
      expect(handle.data.value).toBeNull();
    });
    scope.stop();
  });

  it("records the error on a handle without throwing out of load()", async () => {
    const scope = effectScope();
    await scope.run(async () => {
      const handle = cache.query(["k"], async () => {
        throw new Error("boom");
      });
      await handle.load();
      expect(handle.error.value).toBeInstanceOf(Error);
      expect(handle.loading.value).toBe(false);
    });
    scope.stop();
  });
});

describe("CountsPoller", () => {
  function poller(hidden = { value: false }) {
    const scheduled: Array<() => void> = [];
    const cancelled: number[] = [];
    const instance = new CountsPoller({
      intervalMs: 20,
      schedule: (callback) => {
        scheduled.push(callback);
        return scheduled.length;
      },
      cancel: (handle) => cancelled.push(handle),
      isHidden: () => hidden.value,
      onVisibilityChange: () => () => {},
    });
    return { instance, scheduled, cancelled };
  }

  it("polls at twenty seconds by default (D95)", () => {
    expect(COUNTS_POLL_MS).toBe(20_000);
  });

  it("starts on the first subscriber and stops after the last leaves", () => {
    // Three components each owning a timer is three times the load on the hottest
    // endpoint in the phase, which is why this is reference-counted rather than
    // per-component.
    const { instance, scheduled, cancelled } = poller();
    const first = instance.subscribe(() => {});
    const second = instance.subscribe(() => {});
    expect(scheduled).toHaveLength(1);
    expect(instance.subscriberCount).toBe(2);
    first();
    expect(instance.running).toBe(true);
    second();
    expect(instance.running).toBe(false);
    expect(cancelled).toEqual([1]);
  });

  it("does nothing while the tab is hidden", async () => {
    // A person with thirty open tabs should not be this endpoint's largest source.
    const hidden = { value: true };
    const { instance } = poller(hidden);
    const refresh = vi.fn();
    instance.subscribe(refresh);
    await instance.tick();
    expect(refresh).not.toHaveBeenCalled();
    hidden.value = false;
    await instance.tick();
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("fires every subscriber on a tick", async () => {
    const { instance } = poller();
    const a = vi.fn();
    const b = vi.fn();
    instance.subscribe(a);
    instance.subscribe(b);
    await instance.tick();
    expect(a).toHaveBeenCalledTimes(1);
    expect(b).toHaveBeenCalledTimes(1);
  });
});

describe("countsDiffer: the delta that decides whether items are refetched", () => {
  it("is false for the same counts written differently", () => {
    expect(
      countsDiffer(
        { by_lifecycle: { ready: 2, done: 1 }, total: 3 },
        { total: 3, by_lifecycle: { done: 1, ready: 2 } },
      ),
    ).toBe(false);
  });

  it("is true when any cell moves", () => {
    expect(
      countsDiffer(
        { by_lifecycle: { ready: 2 } },
        { by_lifecycle: { ready: 3 } },
      ),
    ).toBe(true);
  });

  it("treats a first load as a change", () => {
    expect(countsDiffer(null, { total: 0 })).toBe(true);
  });
});
