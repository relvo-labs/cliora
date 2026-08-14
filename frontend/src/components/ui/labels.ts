import type { RunStatus, TaskStage } from "../../api/dto";

export const taskStages: readonly TaskStage[] = [
  "backlog",
  "blocked",
  "ready",
  "implementing",
  "verify",
  "done",
];

export const runStatuses: readonly RunStatus[] = [
  "queued",
  "claimed",
  "running",
  "waiting_for_input",
  "succeeded",
  "failed",
  "lost",
  "cancelled",
];

export const stageLabels: Record<TaskStage, string> = {
  backlog: "待辦",
  blocked: "阻塞",
  ready: "就緒",
  implementing: "進行中",
  verify: "驗證中",
  done: "完成",
};

export const runLabels: Record<RunStatus, string> = {
  queued: "排隊中",
  claimed: "已認領",
  running: "執行中",
  waiting_for_input: "等待你的回覆",
  succeeded: "已成功",
  failed: "失敗",
  lost: "已失聯",
  cancelled: "已取消",
};

export const riskLabels: Record<string, string> = {
  low: "低風險",
  medium: "中風險",
  high: "高風險",
};

export const deliveryLabels: Record<string, string> = {
  none: "不交付",
  artifact: "產物",
  branch: "分支",
  pull_request: "PR",
  existing_pr: "既有 PR",
};

export const SOURCE_MACHINE = "machine_verified";
export const SOURCE_PLATFORM = "platform_observed";
export const SOURCE_AGENT = "agent_reported";

// Which store named a verification command (V2.4, ADR 0033 §3b).
//
// **A second axis, not a third level.** `source` answers who observed a fact; `origin`
// answers who chose to run it. Both origins render in the *same* solid style, because
// their credibility is equal — declaring a check on a card takes `task.approve`, which
// a run token never holds, so neither store was chosen by the agent being verified.
// Drawing the card one paler would assert on screen something that is not true in the
// data, which is the opposite of what this badge exists for.
export const ORIGIN_PROJECT = "project";
export const ORIGIN_CARD = "card";

export const originLabels: Record<string, string> = {
  [ORIGIN_PROJECT]: "專案設定",
  [ORIGIN_CARD]: "卡片宣告",
};

// The qualifier that has to be **words on the page**, never a tooltip.
//
// A limitation you have to hover to discover is a limitation nobody reads, and this
// sentence is the only place the three-level grading is ever encountered by a person.
export const UNVERIFIED_NOTE = "未經平台驗證";

/** Whether a fact was observed by the platform's own execution.
 *
 *  Exported so that **no other module compares against the wire value**. The styling
 *  question "may this exit code be rendered as an observed fact" is a presentation
 *  decision about the grading, and the grading lives here — a component that spelled
 *  `=== "machine_verified"` itself would be a second place to update when a level is
 *  added or renamed, which is what `staticGuards` exists to prevent.
 */
export function isMachineVerified(source: string): boolean {
  return source === SOURCE_MACHINE;
}

export const sourceLabels: Record<string, string> = {
  [SOURCE_MACHINE]: "機器驗證",
  [SOURCE_PLATFORM]: "平台觀測",
  [SOURCE_AGENT]: "Agent 自述",
};

export function labelFor(
  labels: Record<string, string>,
  value: string,
): string {
  return labels[value] ?? value;
}
