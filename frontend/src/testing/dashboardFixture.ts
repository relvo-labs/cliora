// A dashboard summary fixture, shared by the store and view suites (P4-08).
//
// Lives outside the test files because both need the same nine-state matrix, and two
// hand-maintained copies of a nested wire shape drift the first time the DTO changes.

import type {
  DashboardActivityItem,
  DashboardBlockStatus,
  DashboardNodeCounts,
  DashboardSummary,
  UnhealthyNode,
} from "../api/dto";

export const FETCHED_AT = "2026-07-25T11:59:50Z";

export interface FixtureOptions {
  nodes?: Partial<DashboardNodeCounts>;
  // Block names to mark degraded (data becomes null, as the server does) or stale.
  degraded?: string[];
  stale?: string[];
  perRuntime?: Record<string, number>;
  activity?: DashboardActivityItem[];
  actorsHidden?: boolean;
  unhealthy?: UnhealthyNode[];
  unhealthyTotal?: number;
  // Measurement name → {average, nodes}. A measurement absent from this map reports
  // `nodes: 0`, which is the "nothing has reported" case the UI must not show as 0%.
  measurements?: Record<string, { average: number; nodes: number }>;
  generatedAt?: string;
}

export function summaryFixture(options: FixtureOptions = {}): DashboardSummary {
  const at = options.generatedAt ?? FETCHED_AT;
  const status = (name: string): DashboardBlockStatus =>
    options.degraded?.includes(name)
      ? "degraded"
      : options.stale?.includes(name)
        ? "stale"
        : "ok";
  // The server sets `data: null` and an `error_code` for a degraded block; the fixture
  // must too, or a test would pass against a shape the server never produces.
  const wrap = <T>(name: string, data: T) => ({
    status: status(name),
    generated_at: at,
    data: options.degraded?.includes(name) ? null : data,
    error_code: options.degraded?.includes(name) ? "BLOCK_UNAVAILABLE" : null,
  });

  const measurement = (name: string) => {
    const found = options.measurements?.[name];
    return found
      ? { average: found.average, maximum: found.average, nodes: found.nodes }
      : { average: null, maximum: null, nodes: 0 };
  };

  return {
    generated_at: at,
    blocks: {
      nodes: wrap("nodes", {
        online: 2,
        degraded: 0,
        offline: 1,
        disabled: 0,
        total: 3,
        ...options.nodes,
      }),
      sessions: wrap("sessions", {
        starting: 1,
        running: 3,
        disconnected: 0,
        terminating: 0,
        total_active: 4,
        per_runtime: options.perRuntime ?? { claude: 3, codex: 1 },
      }),
      runtimes: wrap("runtimes", {
        runtimes: {
          claude: { available: 2, unavailable: 0, unknown: 1, checked_at: at },
          codex: { available: 1, unavailable: 1, unknown: 1, checked_at: at },
        },
        eligible_nodes: 3,
      }),
      resources: wrap("resources", {
        measurements: {
          cpu_usage: measurement("cpu_usage"),
          memory_usage: measurement("memory_usage"),
          disk_usage: measurement("disk_usage"),
          load_average: measurement("load_average"),
        },
        sampled_nodes: options.measurements ? 2 : 0,
        latest_sample_at: options.measurements ? at : null,
        window_seconds: 300,
      }),
      recent_activity: wrap("recent_activity", {
        items: options.activity ?? [
          {
            id: "a-1",
            action: "node.remove",
            created_at: at,
            actor_id: options.actorsHidden ? null : "u-1",
            actor_name: options.actorsHidden ? null : "Alice",
            node_id: "n-1",
            node_name: "build-01",
          },
        ],
        limit: 20,
        ...(options.actorsHidden ? { actors_hidden: true } : {}),
      }),
      unhealthy_nodes: wrap("unhealthy_nodes", {
        items: options.unhealthy ?? [],
        total: options.unhealthyTotal ?? options.unhealthy?.length ?? 0,
        limit: 10,
      }),
      // V2.4. Non-zero values rather than a zeroed shape: a fixture of zeros passes
      // every rendering test while telling nobody whether the numbers reach the page.
      delivery: wrap("delivery", {
        window_days: 30,
        tasks_created: 12,
        tasks_with_a_run: 9,
        tasks_done: 7,
        tasks_done_with_a_report: 6,
        forced_done: 1,
        runs_finished: 14,
        run_failures: { RUN_IDLE_TIMEOUT: 2, RUN_SOURCE_UNAVAILABLE: 1 },
        avg_waiting_seconds: 412.5,
        checks_by_origin: { project: 18, card: 4 },
      }),
    },
  };
}

export function unhealthyNode(
  overrides: Partial<UnhealthyNode> = {},
): UnhealthyNode {
  return {
    id: "n-9",
    name: "broken-01",
    status: "offline",
    reasons: ["offline_but_enabled"],
    last_seen_at: "2026-07-25T10:00:00Z",
    ...overrides,
  };
}
