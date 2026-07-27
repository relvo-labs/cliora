import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../api/client";
import type { AuditItem, AuditPage } from "../api/dto";
import {
  auditInflight,
  defaultFilter,
  filterFromQuery,
  filterToQuery,
  toWireQuery,
  useAuditStore,
  type AuditFilter,
} from "./audit";
import * as auth from "./auth";

const NOW = new Date("2026-07-25T12:00:00.000Z");

function item(overrides: Partial<AuditItem> = {}): AuditItem {
  return {
    id: crypto.randomUUID(),
    action: "user.login",
    created_at: "2026-07-25T11:59:00Z",
    actor: {
      id: crypto.randomUUID(),
      username: "admin",
      display_name: "Admin",
    },
    node: null,
    session_id: null,
    request_id: "01K0RID",
    metadata: {},
    ...overrides,
  };
}

function page(items: AuditItem[], next: string | null = null): AuditPage {
  return { items, next_cursor: next };
}

// Stub the shared client so the store is tested without a network layer.
function stubApi(listAudit: ReturnType<typeof vi.fn>): void {
  vi.spyOn(auth, "api").mockReturnValue({
    listAudit,
  } as unknown as ReturnType<typeof auth.api>);
}

describe("audit filter serialization", () => {
  it("round-trips through the query string so a view can be shared", () => {
    const filter: AuditFilter = {
      ...defaultFilter(),
      actions: ["user.login", "node.remove"],
      userId: "u-1",
      nodeId: "n-1",
      sessionId: "s-1",
      range: "7d",
    };
    expect(filterFromQuery(filterToQuery(filter))).toEqual(filter);
  });

  it("keeps custom bounds only for the custom range", () => {
    const custom = filterToQuery({
      ...defaultFilter(),
      range: "custom",
      from: "2026-07-01T00:00",
      to: "2026-07-02T00:00",
    });
    expect(custom).toMatchObject({ from: "2026-07-01T00:00" });

    // A preset range recomputes its window at query time, so persisting stale
    // absolute bounds alongside it would contradict the preset.
    const preset = filterToQuery({
      ...defaultFilter(),
      range: "24h",
      from: "2026-07-01T00:00",
    });
    expect(preset.from).toBeUndefined();
  });

  it("falls back to the default range for a hand-edited value", () => {
    expect(filterFromQuery({ range: "all-time" }).range).toBe(
      defaultFilter().range,
    );
  });

  it("tolerates a repeated query parameter", () => {
    expect(filterFromQuery({ user_id: ["a", "b"] }).userId).toBe("a");
  });
});

describe("audit wire query", () => {
  it("resolves a preset range into absolute bounds at query time", () => {
    const query = toWireQuery({ ...defaultFilter(), range: "1h" }, NOW);
    expect(query.to).toBe("2026-07-25T12:00:00.000Z");
    expect(query.from).toBe("2026-07-25T11:00:00.000Z");
  });

  it("omits blank filters rather than sending empty strings", () => {
    const query = toWireQuery(
      { ...defaultFilter(), userId: "   ", nodeId: "" },
      NOW,
    );
    expect(query.user_id).toBeUndefined();
    expect(query.node_id).toBeUndefined();
  });

  it("trims an id pasted with surrounding whitespace", () => {
    expect(
      toWireQuery({ ...defaultFilter(), nodeId: "  n-1 " }, NOW).node_id,
    ).toBe("n-1");
  });

  it("sends repeated actions as a list, matching the server's union", () => {
    expect(
      toWireQuery({ ...defaultFilter(), actions: ["a", "b"] }, NOW).action,
    ).toEqual(["a", "b"]);
  });
});

describe("useAuditStore", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("loads the first page and reports success", async () => {
    const listAudit = vi.fn().mockResolvedValue(page([item(), item()]));
    stubApi(listAudit);
    const store = useAuditStore();

    await store.search(NOW);

    expect(store.state).toBe("success");
    expect(store.loadedCount).toBe(2);
    expect(store.hasMore).toBe(false);
    expect(auditInflight()).toBe(false);
  });

  it("reports empty rather than success for a filter that matches nothing", () => {
    // "No records" has its own UI state with a "widen the filter" hint; folding it
    // into success would render an empty table with no explanation.
    stubApi(vi.fn().mockResolvedValue(page([])));
    const store = useAuditStore();
    return store.search(NOW).then(() => {
      expect(store.state).toBe("empty");
    });
  });

  it("appends the next page and advances the cursor", async () => {
    const first = page([item()], "cursor-1");
    const second = page([item()], null);
    const listAudit = vi
      .fn()
      .mockResolvedValueOnce(first)
      .mockResolvedValueOnce(second);
    stubApi(listAudit);
    const store = useAuditStore();

    await store.search(NOW);
    expect(store.hasMore).toBe(true);
    await store.loadMore(NOW);

    expect(store.loadedCount).toBe(2);
    expect(store.hasMore).toBe(false);
    expect(listAudit.mock.calls[1][0].cursor).toBe("cursor-1");
  });

  it("does not request another page once the window is exhausted", async () => {
    const listAudit = vi.fn().mockResolvedValue(page([item()], null));
    stubApi(listAudit);
    const store = useAuditStore();

    await store.search(NOW);
    await store.loadMore(NOW);

    expect(listAudit).toHaveBeenCalledTimes(1);
  });

  it("replaces rather than appends when the filter changes", async () => {
    // Appending would mix the answers to two different questions in one table.
    const listAudit = vi
      .fn()
      .mockResolvedValueOnce(page([item({ action: "user.login" })], "c"))
      .mockResolvedValueOnce(page([item({ action: "node.remove" })]));
    stubApi(listAudit);
    const store = useAuditStore();

    await store.search(NOW);
    store.setFilter({ ...defaultFilter(), actions: ["node.remove"] });
    await store.search(NOW);

    expect(store.items.map((row) => row.action)).toEqual(["node.remove"]);
    expect(store.hasMore).toBe(false);
  });

  it("drops a response whose filter is no longer current", async () => {
    // A slow first query must not overwrite the results of a later, faster one.
    let release: (value: AuditPage) => void = () => {};
    const slow = new Promise<AuditPage>((resolve) => {
      release = resolve;
    });
    const listAudit = vi
      .fn()
      .mockReturnValueOnce(slow)
      .mockResolvedValueOnce(page([item({ action: "node.remove" })]));
    stubApi(listAudit);
    const store = useAuditStore();

    const pending = store.search(NOW);
    store.setFilter({ ...defaultFilter(), actions: ["node.remove"] });
    await store.search(NOW);
    release(page([item({ action: "user.login" })]));
    await pending;

    expect(store.items.map((row) => row.action)).toEqual(["node.remove"]);
  });

  it("maps a 403 to the forbidden state with the server's request id", async () => {
    stubApi(
      vi.fn().mockRejectedValue(new ApiError("FORBIDDEN", "no", 403, "rid-9")),
    );
    const store = useAuditStore();

    await store.search(NOW);

    expect(store.state).toBe("forbidden");
    expect(store.requestId).toBe("rid-9");
  });

  it("surfaces a 422 as an error carrying the server's message", async () => {
    stubApi(
      vi
        .fn()
        .mockRejectedValue(
          new ApiError(
            "INVALID_QUERY",
            "time range must not exceed 90 days",
            422,
          ),
        ),
    );
    const store = useAuditStore();

    await store.search(NOW);

    expect(store.state).toBe("error");
    expect(store.message).toContain("90 days");
  });

  it("keeps the loaded rows and reports partial when a further page fails", async () => {
    // Discarding what is on screen would punish the user for a transient failure
    // on page three.
    const listAudit = vi
      .fn()
      .mockResolvedValueOnce(page([item()], "cursor-1"))
      .mockRejectedValueOnce(new ApiError("INTERNAL_ERROR", "boom", 500));
    stubApi(listAudit);
    const store = useAuditStore();

    await store.search(NOW);
    await store.loadMore(NOW);

    expect(store.state).toBe("partial");
    expect(store.loadedCount).toBe(1);
    expect(store.loadingMore).toBe(false);
  });

  it("aborts the in-flight request and clears rows on reset", async () => {
    const abortReason = Object.assign(new Error("aborted"), {
      name: "AbortError",
    });
    stubApi(vi.fn().mockRejectedValue(abortReason));
    const store = useAuditStore();

    const pending = store.search(NOW);
    store.reset();
    await pending;

    expect(store.items).toEqual([]);
    expect(store.state).toBe("idle");
    expect(auditInflight()).toBe(false);
  });

  it("leaves no state behind for an aborted request", async () => {
    const abortReason = Object.assign(new Error("aborted"), {
      name: "AbortError",
    });
    stubApi(vi.fn().mockRejectedValue(abortReason));
    const store = useAuditStore();

    await store.search(NOW);

    // Still "loading": an abort is not a failure, so it must not paint an error.
    expect(store.state).toBe("loading");
    expect(store.message).toBe("");
  });
});
