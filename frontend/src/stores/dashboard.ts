// Dashboard state (P4-08). Owns the summary, the request lifecycle, and the optional
// auto-refresh timer.
//
// The theme running through this store is **not manufacturing a sense of liveness**:
//
//   * polling is **off by default**. A number that refreshes itself every few seconds
//     looks live even when the block behind it is `stale`, and that is the specific
//     deception the freshness contract exists to prevent. The user turns it on.
//   * `generated_at` is whatever the server said. It is never replaced with "now" on a
//     cache hit, because a five-second-old figure claiming to be current is exactly the
//     failure the server-side contract is built to avoid.
//   * a block that failed keeps `data: null`. It is never back-filled with zeros — "we
//     could not read this" and "this is zero" are different facts and read differently.

import { defineStore } from "pinia";

import { ApiError, isAbortError } from "../api/client";
import type { DashboardSummary } from "../api/dto";
import { api } from "./auth";

export type DashboardState =
  | "idle"
  | "loading"
  | "success"
  | "forbidden"
  | "error";

// How often auto-refresh fires when the user enables it. Matched to the server's 5 s
// aggregate cache times six: polling faster than the cache only re-renders identical
// numbers, which is the "fake live" effect in another form.
export const AUTO_REFRESH_MS = 30_000;

interface DashboardStoreState {
  summary: DashboardSummary | null;
  state: DashboardState;
  error: unknown;
  // Survives navigation because it is a user preference, not request state: someone who
  // turned refresh on for an incident should not have to turn it on again per visit.
  autoRefresh: boolean;
  // Set only for a *refresh* over already-rendered data, so the view can show a subtle
  // indicator instead of replacing the page with a skeleton.
  refreshing: boolean;
}

// Plumbing, not data: kept out of the reactive state so it is never serialized.
let inflight: AbortController | null = null;
let timer: ReturnType<typeof setInterval> | null = null;

export const useDashboardStore = defineStore("dashboard", {
  state: (): DashboardStoreState => ({
    summary: null,
    state: "idle",
    error: null,
    autoRefresh: false,
    refreshing: false,
  }),
  getters: {
    // True when there is no node at all: the empty-deployment state, which is a
    // legitimate answer rather than an error.
    isEmptyDeployment: (state): boolean =>
      state.summary?.blocks.nodes.data?.total === 0,

    // Every node is offline or disabled. Distinct from `isEmptyDeployment`: "nothing
    // installed" and "everything down" need different first steps.
    isFleetOffline(state): boolean {
      const nodes = state.summary?.blocks.nodes.data;
      return Boolean(
        nodes && nodes.total > 0 && nodes.online === 0 && nodes.degraded === 0,
      );
    },

    // Any block the server could not compute. Drives the page-level `partial` notice —
    // the individual cards say so too, but a user scanning the page needs to be told
    // once that what they are looking at is incomplete.
    degradedBlocks: (state): string[] =>
      state.summary
        ? Object.entries(state.summary.blocks)
            .filter(([, block]) => block.status === "degraded")
            .map(([name]) => name)
        : [],

    staleBlocks: (state): string[] =>
      state.summary
        ? Object.entries(state.summary.blocks)
            .filter(([, block]) => block.status === "stale")
            .map(([name]) => name)
        : [],
  },
  actions: {
    async load(): Promise<void> {
      inflight?.abort();
      const controller = new AbortController();
      inflight = controller;
      // A first load shows a skeleton; a refresh keeps the numbers on screen. Replacing
      // rendered data with a skeleton every 30 s would be its own kind of flicker.
      if (this.summary === null) {
        this.state = "loading";
      } else {
        this.refreshing = true;
      }
      try {
        const summary = await api().getDashboardSummary({
          signal: controller.signal,
        });
        this.summary = summary;
        this.state = "success";
        this.error = null;
      } catch (caught) {
        if (isAbortError(caught)) {
          return;
        }
        this.error = caught;
        // A failed refresh keeps the last good data on screen and reports the failure —
        // throwing away readable numbers because one poll failed is worse than showing
        // them with an explicit "could not refresh".
        if (this.summary === null) {
          this.state =
            caught instanceof ApiError && caught.status === 403
              ? "forbidden"
              : "error";
        }
      } finally {
        this.refreshing = false;
        if (inflight === controller) {
          inflight = null;
        }
      }
    },

    setAutoRefresh(enabled: boolean): void {
      this.autoRefresh = enabled;
      this.stopTimer();
      if (enabled) {
        timer = setInterval(() => {
          void this.load();
        }, AUTO_REFRESH_MS);
      }
    },

    stopTimer(): void {
      if (timer !== null) {
        clearInterval(timer);
        timer = null;
      }
    },

    // Called on unmount: stops the timer and aborts in flight work, but **keeps** the
    // summary and the autoRefresh preference so returning to the page shows the last
    // known state immediately rather than a skeleton.
    detach(): void {
      inflight?.abort();
      inflight = null;
      this.stopTimer();
      this.refreshing = false;
    },
  },
});

// Test seams.
export function dashboardInflight(): boolean {
  return inflight !== null;
}

export function dashboardTimerRunning(): boolean {
  return timer !== null;
}
