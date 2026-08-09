// Labels for the project activity timeline's closed `kind` vocabulary (ADR 0027).
//
// **A separate vocabulary from the audit actions**, and this file exists because
// conflating them is easy and silent: the timeline writes `workspace.bound` where
// the audit trail writes `project.workspace_bind`, so passing a kind to
// `auditActions.actionLabel` falls through to its "show the raw key" branch and the
// screen reads `workspace.bound` instead of a sentence. Nothing fails; it just
// looks unfinished.
//
// The two differ on purpose (`backend/app/services/activity.py`). The audit trail
// splits archive from update, because "who archived that project" is a question
// asked on its own across the fleet. The timeline keeps one `project.updated`,
// because a reader there is scanning one project in order and would otherwise have
// to merge two streams mentally.

const LABELS: Record<string, string> = {
  "project.created": "建立專案",
  "project.updated": "更新專案",
  "workspace.bound": "綁定 Workspace",
  "workspace.unbound": "解綁 Workspace",
  "session.started": "Session 開始",
  "session.ended": "Session 結束",
};

/** The raw kind is the fallback, so a kind added on the server stays readable
 *  until a label is written for it — the same policy `actionLabel` uses. */
export function kindLabel(kind: string): string {
  return LABELS[kind] ?? kind;
}

/** Every kind the server can send. Kept here so a drift test can compare it with
 *  `ALL_KINDS` in `backend/app/services/activity.py`. */
export const ACTIVITY_KINDS = Object.keys(LABELS);
