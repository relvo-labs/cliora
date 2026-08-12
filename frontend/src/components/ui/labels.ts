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
