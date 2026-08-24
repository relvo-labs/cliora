// My Work's six sections, as data (PX-49, plan/26/08 §3).
//
// **This is the differentiating page, not "Jira's my tasks".** The question it answers is
// *which things are waiting for a human, and that human is me* — a question only Cliora
// has to answer, because only Cliora has a fleet of agents standing still until somebody
// replies.
//
// The filters are the same allowlist the board uses, and they are sent to the same
// compiler through `/api/me/work-items`. Nothing here re-derives attention: the levels
// arrive already chosen (ADR 0040 §3).

import { ACTION_TASK_APPROVE, type WorkItemCard } from "../../api/dto";

export interface SectionSpec {
  key: string;
  title: string;
  /** One sentence saying what the section is, shown under the title. Written to be
   *  narrower than the ideal where the data forces it — see `waiting`. */
  caption: string;
  /** The filter, in the read model's own shape. */
  filter: Record<string, unknown>;
  /** True when the section cannot be answered without the node registry (D92). Those
   *  sections show "temporarily unavailable" rather than an empty list. */
  needsRuntime?: boolean;
  /** The action the caller must hold for the section to mean anything. */
  requires?: string;
}

export function sectionsFor(userId: string): SectionSpec[] {
  return [
    {
      key: "waiting",
      title: "等你回覆",
      // **The caption is deliberately narrower than the section's intent.**
      // `task_questions` has no `addressed_to_user_id`, so "a question aimed at me" is
      // not a question this system can be asked (plan/26/08 §3). The predicate is
      // ownership, and the caption says ownership rather than promising the other thing.
      caption: "你負責的卡片裡，有 Agent 停在那裡等一句話",
      filter: {
        and: [
          { field: "attention", op: "eq", value: "waiting_for_your_input" },
          { field: "owner", op: "eq", value: userId },
        ],
      },
    },
    {
      key: "approval",
      title: "等你核准",
      caption: "已經進入審查，等一個人做正式決定",
      filter: { field: "attention", op: "eq", value: "pending_human_approval" },
      // The constant, not the string: `dto.ts` is where the action vocabulary lives
      // and `test_all_actions_match_the_frontend_constants` pins it to the server.
      requires: ACTION_TASK_APPROVE,
    },
    {
      key: "failed",
      title: "你負責的失敗執行",
      caption: "沒有結論；重試可能就好了，但要有人看一眼",
      filter: {
        and: [
          { field: "attention", op: "eq", value: "run_failed" },
          { field: "owner", op: "eq", value: userId },
        ],
      },
    },
    {
      key: "assigned",
      title: "你負責的進行中工作",
      caption: "已就緒、進行中或審查中的卡片",
      filter: {
        and: [
          { field: "owner", op: "eq", value: userId },
          {
            field: "lifecycle",
            op: "in",
            value: ["ready", "in_progress", "review"],
          },
        ],
      },
    },
    {
      key: "no-runner",
      title: "沒有符合條件的 Agent",
      caption: "設定問題，人可以修；卡片沒有在退化",
      filter: {
        and: [
          { field: "attention", op: "eq", value: "no_eligible_runner" },
          { field: "owner", op: "eq", value: userId },
        ],
      },
      // The one section that is unanswerable without the registry.
      needsRuntime: true,
    },
    {
      key: "delivered",
      title: "最近完成的交付",
      caption: "近七天完成的卡片",
      filter: {
        and: [
          { field: "lifecycle", op: "eq", value: "done" },
          { field: "updated_at", op: "gt", value: sevenDaysAgo() },
        ],
      },
    },
  ];
}

export function sevenDaysAgo(now: number = Date.now()): string {
  return new Date(now - 7 * 24 * 60 * 60 * 1000).toISOString();
}

/** `base64url(json)`, matching what the server decodes.
 *
 *  In the URL as well as in the request, because "look at this filter" is a real thing
 *  people say to each other (D103). One encoder for both.
 */
export function encodeFilter(filter: Record<string, unknown>): string {
  const json = JSON.stringify(filter);
  const bytes = new TextEncoder().encode(json);
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary)
    .replaceAll("+", "-")
    .replaceAll("/", "_")
    .replace(/=+$/, "");
}

export interface SectionResult {
  spec: SectionSpec;
  items: WorkItemCard[];
  count: number;
  /** Set when the section could not be answered rather than answered with nothing.
   *
   *  **"None" and "we do not know" have different consequences on this screen**: the
   *  first sends a person to do something else, the second sends them to reload. A
   *  component test asserts the difference. */
  unavailable: string | null;
}
