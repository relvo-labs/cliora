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
  // 這台機器的系統終端機變成（或不再是）可經 sudo 取得 root。變更發生在機器上，
  // 平台是唯一會把它記下來的地方（ADR 0023）。
  "node.posture_changed": "Node 提權姿態變更",
  "credential.revoke": "撤銷憑證",
  "credential.rotate": "輪替憑證",
  "session.create": "建立 Session",
  "session.attach": "連接 Session",
  "session.takeover": "接管 Terminal",
  "session.terminate": "終止 Session",
  "session.failed": "Session 失敗",
  "file.sensitive_read_denied": "敏感檔讀取被拒",
  "authz.denied": "授權被拒",
  // 埠轉發（ADR 0022）。整合層與隧道層分開記，因為它們回答的是不同的問題：
  // 「誰決定本組織使用這個服務、用誰的帳號」與「誰把哪台機器的哪個 port 對外」。
  "integration.enable": "啟用埠轉發整合",
  "integration.disable": "停用埠轉發整合",
  "integration.credential_set": "設定服務商憑證",
  "integration.node_settings_updated": "變更 Node 埠轉發設定",
  "tunnel.create": "建立埠轉發",
  "tunnel.close": "關閉埠轉發",
  // 單獨一個動作而不是 tunnel.create 的一個欄位：「誰同意這個 port 對任何拿到網址的人開放」
  // 是事後會被問到的問題，而藏在別的動作裡的欄位無法被篩選。
  "tunnel.public_acknowledged": "確認開放無保護預覽",
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
      "node.posture_changed",
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
    title: "埠轉發整合 / Port forwarding",
    actions: [
      "integration.enable",
      "integration.disable",
      "integration.credential_set",
      "integration.node_settings_updated",
      "tunnel.create",
      "tunnel.close",
      "tunnel.public_acknowledged",
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
