// Human-readable labels for the closed audit action vocabulary (P4-05).
//
// The raw key is always displayed alongside the label: the label is for scanning,
// the key is what an operator types into a filter, quotes in a ticket, or greps
// for in the server log. Showing only one of the two makes the other unusable.

import { AUDIT_ACTIONS } from "../api/dto";

const LABELS: Record<string, string> = {
  "user.login": "登入成功",
  "user.login_failed": "登入失敗",
  "user.logout": "登出",
  "enrollment.create": "建立安裝 Token",
  "enrollment.revoke": "撤銷安裝 Token",
  "enrollment.use": "使用安裝 Token",
  "node.register": "Node 註冊",
  "node.disable": "停用 Node",
  "node.enable": "啟用 Node",
  "node.remove": "移除 Node",
  "credential.revoke": "撤銷憑證",
  "credential.rotate": "輪替憑證",
  "session.create": "建立 Session",
  "session.attach": "連接 Session",
  "session.takeover": "接管 Terminal",
  "session.terminate": "終止 Session",
  "session.failed": "Session 失敗",
  "file.sensitive_read_denied": "敏感檔讀取被拒",
  "authz.denied": "授權被拒",
  "daemon.update_started": "觸發 Daemon 更新",
  "daemon.update_result": "Daemon 更新結果",
};

// An action with no label would render blank, so it falls back to its own key —
// a new action added on the server stays readable until a label is written.
export function actionLabel(action: string): string {
  return LABELS[action] ?? action;
}

// Grouped by the resource they concern, which is how the filter is scanned.
export const ACTION_GROUPS: { title: string; actions: string[] }[] = [
  {
    title: "帳號 / Account",
    actions: ["user.login", "user.login_failed", "user.logout"],
  },
  {
    title: "安裝 / Enrollment",
    actions: ["enrollment.create", "enrollment.revoke", "enrollment.use"],
  },
  {
    title: "Node",
    actions: [
      "node.register",
      "node.enable",
      "node.disable",
      "node.remove",
      "credential.revoke",
      "credential.rotate",
      "daemon.update_started",
      "daemon.update_result",
    ],
  },
  {
    title: "Session / Terminal",
    actions: [
      "session.create",
      "session.attach",
      "session.takeover",
      "session.terminate",
      "session.failed",
    ],
  },
  {
    title: "安全事件 / Security",
    actions: ["authz.denied", "file.sensitive_read_denied"],
  },
];

// Every action must appear in exactly one group: a missing one would be silently
// unfilterable in the UI even though the server accepts it.
export function ungroupedActions(): string[] {
  const grouped = new Set(ACTION_GROUPS.flatMap((group) => group.actions));
  return AUDIT_ACTIONS.filter((action) => !grouped.has(action));
}
