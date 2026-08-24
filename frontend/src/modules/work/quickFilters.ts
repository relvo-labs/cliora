// The seven chips (PX-31, plan/26/06 §2).
//
// A chip writes `f=` and **never** the saved view (D103). Two of the seven are special:
// `Blocked` and `No runner` map onto attention's runtime levels, and when the node
// registry cannot be consulted they are shown **disabled with a reason** rather than
// returning zero rows — zero rows reads as "fixed" (ADR 0040 §2).

export interface QuickFilter {
  key: string;
  label: string;
  filter: Record<string, unknown>;
  /** True when the chip's answer depends on the node registry. */
  needsRuntime?: boolean;
}

export const QUICK_FILTERS: QuickFilter[] = [
  {
    key: "waiting-for-me",
    label: "等我回覆",
    filter: { field: "attention", op: "eq", value: "waiting_for_your_input" },
  },
  {
    key: "agent-active",
    label: "Agent 執行中",
    filter: {
      field: "execution_status",
      op: "in",
      value: ["running", "claimed"],
    },
  },
  {
    key: "failed",
    label: "失敗",
    filter: {
      field: "attention",
      op: "in",
      value: ["run_failed", "verification_failed"],
    },
  },
  {
    key: "blocked",
    label: "被阻塞",
    filter: { field: "is_blocked", op: "eq", value: true },
  },
  {
    key: "high-risk",
    label: "高風險",
    filter: { field: "risk", op: "in", value: ["high", "critical"] },
  },
  {
    key: "unassigned",
    label: "未指派",
    filter: { field: "owner", op: "is_null", value: true },
  },
  {
    key: "no-runner",
    label: "無可用 Agent",
    filter: { field: "attention", op: "eq", value: "no_eligible_runner" },
    needsRuntime: true,
  },
];

export const RUNTIME_UNAVAILABLE = "節點連線資訊暫時不可用";
