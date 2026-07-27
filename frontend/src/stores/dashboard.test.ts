import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../api/client";
import type { DashboardSummary } from "../api/dto";
import * as auth from "./auth";
import {
  AUTO_REFRESH_MS,
  dashboardInflight,
  dashboardTimerRunning,
  useDashboardStore,
} from "./dashboard";
import { summaryFixture } from "../testing/dashboardFixture";

function stubApi(getDashboardSummary: ReturnType<typeof vi.fn>): void {
  vi.spyOn(auth, "api").mockReturnValue({
    getDashboardSummary,
  } as unknown as ReturnType<typeof auth.api>);
}

describe("useDashboardStore", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.useFakeTimers();
  });

  afterEach(() => {
    useDashboardStore().detach();
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it("loads the summary and reports success", async () => {
    stubApi(vi.fn().mockResolvedValue(summaryFixture()));
    const store = useDashboardStore();

    await store.load();

    expect(store.state).toBe("success");
    expect(store.summary?.blocks.nodes.data?.online).toBe(2);
    expect(dashboardInflight()).toBe(false);
  });

  it("does not poll unless the user asks", () => {
    // A page that refreshes itself looks live even while a block is stale — the exact
    // impression the freshness contract exists to prevent.
    const store = useDashboardStore();
    expect(store.autoRefresh).toBe(false);
    expect(dashboardTimerRunning()).toBe(false);
  });

  it("starts and stops the auto-refresh timer on request", async () => {
    const getSummary = vi.fn().mockResolvedValue(summaryFixture());
    stubApi(getSummary);
    const store = useDashboardStore();
    await store.load();
    expect(getSummary).toHaveBeenCalledTimes(1);

    store.setAutoRefresh(true);
    expect(dashboardTimerRunning()).toBe(true);
    await vi.advanceTimersByTimeAsync(AUTO_REFRESH_MS);
    expect(getSummary).toHaveBeenCalledTimes(2);

    store.setAutoRefresh(false);
    expect(dashboardTimerRunning()).toBe(false);
    await vi.advanceTimersByTimeAsync(AUTO_REFRESH_MS * 2);
    expect(getSummary).toHaveBeenCalledTimes(2);
  });

  it("enabling auto-refresh twice does not stack timers", async () => {
    // Two intervals would double the request rate invisibly.
    const getSummary = vi.fn().mockResolvedValue(summaryFixture());
    stubApi(getSummary);
    const store = useDashboardStore();
    await store.load();

    store.setAutoRefresh(true);
    store.setAutoRefresh(true);
    await vi.advanceTimersByTimeAsync(AUTO_REFRESH_MS);

    expect(getSummary).toHaveBeenCalledTimes(2);
  });

  it("shows a skeleton on the first load and not on a refresh", async () => {
    // Replacing rendered numbers with a skeleton every 30 s would manufacture activity.
    let release: (value: DashboardSummary) => void = () => {};
    const first = new Promise<DashboardSummary>((resolve) => {
      release = resolve;
    });
    const getSummary = vi
      .fn()
      .mockReturnValueOnce(first)
      .mockResolvedValue(summaryFixture());
    stubApi(getSummary);
    const store = useDashboardStore();

    const pending = store.load();
    expect(store.state).toBe("loading");
    release(summaryFixture());
    await pending;

    const refresh = store.load();
    expect(store.state).toBe("success");
    expect(store.refreshing).toBe(true);
    await refresh;
    expect(store.refreshing).toBe(false);
  });

  it("keeps the last good data when a refresh fails", async () => {
    // Discarding readable numbers because one poll failed is worse than showing them
    // with an explicit "could not refresh".
    const getSummary = vi
      .fn()
      .mockResolvedValueOnce(summaryFixture())
      .mockRejectedValueOnce(new ApiError("INTERNAL_ERROR", "boom", 500));
    stubApi(getSummary);
    const store = useDashboardStore();

    await store.load();
    await store.load();

    expect(store.state).toBe("success");
    expect(store.summary).not.toBeNull();
    expect(store.error).toBeInstanceOf(ApiError);
  });

  it("reports error only when there is nothing to show", async () => {
    stubApi(
      vi.fn().mockRejectedValue(new ApiError("INTERNAL_ERROR", "boom", 500)),
    );
    const store = useDashboardStore();

    await store.load();

    expect(store.state).toBe("error");
    expect(store.summary).toBeNull();
  });

  it("maps a 403 to forbidden", async () => {
    stubApi(vi.fn().mockRejectedValue(new ApiError("FORBIDDEN", "no", 403)));
    const store = useDashboardStore();
    await store.load();
    expect(store.state).toBe("forbidden");
  });

  it("leaves no error state behind for an aborted request", async () => {
    const aborted = Object.assign(new Error("aborted"), { name: "AbortError" });
    stubApi(vi.fn().mockRejectedValue(aborted));
    const store = useDashboardStore();

    await store.load();

    expect(store.state).toBe("loading");
    expect(store.error).toBeNull();
  });

  it("detach stops the timer but keeps the data and the preference", async () => {
    // Returning to the page should show the last known state, not a skeleton — and a
    // preference set during an incident should not need re-enabling per visit.
    stubApi(vi.fn().mockResolvedValue(summaryFixture()));
    const store = useDashboardStore();
    await store.load();
    store.setAutoRefresh(true);

    store.detach();

    expect(dashboardTimerRunning()).toBe(false);
    expect(store.summary).not.toBeNull();
    expect(store.autoRefresh).toBe(true);
  });

  describe("derived fleet states", () => {
    it("recognises an empty deployment", async () => {
      stubApi(
        vi.fn().mockResolvedValue(
          summaryFixture({
            nodes: {
              online: 0,
              degraded: 0,
              offline: 0,
              disabled: 0,
              total: 0,
            },
          }),
        ),
      );
      const store = useDashboardStore();
      await store.load();
      expect(store.isEmptyDeployment).toBe(true);
      expect(store.isFleetOffline).toBe(false);
    });

    it("distinguishes an offline fleet from an empty one", async () => {
      // "Nothing installed" and "everything down" need different first steps.
      stubApi(
        vi.fn().mockResolvedValue(
          summaryFixture({
            nodes: {
              online: 0,
              degraded: 0,
              offline: 3,
              disabled: 0,
              total: 3,
            },
          }),
        ),
      );
      const store = useDashboardStore();
      await store.load();
      expect(store.isEmptyDeployment).toBe(false);
      expect(store.isFleetOffline).toBe(true);
    });

    it("does not call a fleet with a degraded node offline", async () => {
      // Degraded means still connected: the link is stale, not gone.
      stubApi(
        vi.fn().mockResolvedValue(
          summaryFixture({
            nodes: {
              online: 0,
              degraded: 1,
              offline: 2,
              disabled: 0,
              total: 3,
            },
          }),
        ),
      );
      const store = useDashboardStore();
      await store.load();
      expect(store.isFleetOffline).toBe(false);
    });

    it("lists degraded and stale blocks by name", async () => {
      stubApi(
        vi
          .fn()
          .mockResolvedValue(
            summaryFixture({ degraded: ["resources"], stale: ["nodes"] }),
          ),
      );
      const store = useDashboardStore();
      await store.load();
      expect(store.degradedBlocks).toEqual(["resources"]);
      expect(store.staleBlocks).toEqual(["nodes"]);
    });

    it("reports no derived states before the first load", () => {
      const store = useDashboardStore();
      expect(store.isEmptyDeployment).toBe(false);
      expect(store.isFleetOffline).toBe(false);
      expect(store.degradedBlocks).toEqual([]);
    });
  });
});
