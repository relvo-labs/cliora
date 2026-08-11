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
  "session.context_projection": "任務情境投影",
  // V2.1, the task layer. `task.updated` and `task.stage_changed` are separate for
  // the reader's sake, not the writer's: someone scanning a project's history is
  // asking what moved, and a title edit is not that.
  "epic.created": "建立 Epic",
  "user_story.created": "建立 User Story",
  "task.created": "建立任務",
  "task.updated": "更新任務",
  "task.stage_changed": "任務換車道",
  "task.gate_approved": "審查關卡核准",
  "requirement.created": "提出需求",
  "requirement.spec_added": "新增規格版本",
  "requirement.approved": "核准規格",
  "requirement.proposal_accepted": "接受任務提案",
  // V2.2, the agent runner. `run.dispatched` is a person's action; the claim and the
  // finish are the runner's and the system's, and they arrive with the queue service.
  "run.dispatched": "派給 Agent",
  "task.message_posted": "卡片留言",
};

/** The raw kind is the fallback, so a kind added on the server stays readable
 *  until a label is written for it — the same policy `actionLabel` uses. */
export function kindLabel(kind: string): string {
  return LABELS[kind] ?? kind;
}

/** Every kind the server can send. Kept here so a drift test can compare it with
 *  `ALL_KINDS` in `backend/app/services/activity.py`. */
export const ACTIVITY_KINDS = Object.keys(LABELS);
