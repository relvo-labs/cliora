// Moving a card: one mutation path, two entrances (PX-34, merged from upstream PX-35).
//
// **Drag and the keyboard are the same call.** They were two tickets upstream and that is
// exactly how a codebase ends up with two rollback implementations, one of which is
// subtly wrong. The Move dialog is not a fallback for the drag — it is the accessible
// path, and it is also the one the e2e suite can drive reliably.
//
// Three properties, and each has a test:
//
//   * **neighbour ids, never an index.** On a filtered board position 3 of the list is not
//     position 3 of the lane, and the bug that produces is a card landing where nobody
//     pointed. There is a payload assertion.
//   * **optimistic, and the rollback is not optional.** A card that stays in its new lane
//     after a refusal is a card the user believes moved.
//   * **the refusal says what happened.** "移動失敗" leaves a person with nothing to do;
//     `TASK_VERSION_CONFLICT`, `RANK_NEIGHBOR_STALE` and `TASK_DEPENDENCY_UNSATISFIED`
//     each send them somewhere different.

import { ref } from "vue";

import { ApiError } from "../../../api/client";
import type { WorkItemCard } from "../../../api/dto";
import { api } from "../../../stores/auth";
import { workCache } from "../queryCache";

export interface MoveRequest {
  card: WorkItemCard;
  /** The card that will sit immediately before it, or null for the top of the group. */
  previous: WorkItemCard | null;
  /** The card that will sit immediately after it, or null for the bottom. */
  next: WorkItemCard | null;
  /** Set when the move crosses groups. Sent in the **same** request as the rank, because
   *  two requests would leave a visible intermediate state where the card is in the new
   *  column at the old position. */
  lifecycleStage?: string | null;
}

export interface MoveOutcome {
  ok: boolean;
  /** A sentence a person can act on, or null on success. */
  reason: string | null;
  /** For a screen reader, in both directions. Announced before and after. */
  announcement: string;
}

export function explainMoveFailure(error: unknown): string {
  if (!(error instanceof ApiError)) return "移動失敗，請重試。";
  const details = error.details as
    | { blocking_refs?: string[]; previous_rank?: string; next_rank?: string }
    | undefined;
  switch (error.code) {
    case "TASK_VERSION_CONFLICT":
      return "這張卡剛被別人改過，已重新載入。";
    case "RANK_NEIGHBOR_STALE":
      // A different situation from a version conflict, and a different recovery: the
      // card is unchanged and the *order around it* moved.
      return "你放下的那兩張卡已經不相鄰了，順序已重新載入。";
    case "TASK_DEPENDENCY_UNSATISFIED":
      return `${(details?.blocking_refs ?? []).join("、")} 尚未完成。`;
    case "PROJECT_ARCHIVED":
      return "這個專案已封存，卡片不能再變更。";
    default:
      return error.message;
  }
}

export function useOptimisticMove(onInvalidate: () => void) {
  /** The card the browser has moved but the server has not confirmed. Held separately
   *  from the page so that a rollback is "forget this entry" rather than a refetch — the
   *  refetch happens too, but after the card is already back. */
  const pending = ref<Record<string, string>>({});
  const lastAnnouncement = ref("");

  async function move(request: MoveRequest): Promise<MoveOutcome> {
    const { card, previous, next, lifecycleStage } = request;
    const target = lifecycleStage ?? card.legacy_stage ?? "";
    const announcement = `${card.card_ref} 移動到 ${target || "同一欄"}${
      previous ? `，在 ${previous.card_ref} 之後` : "，最前面"
    }`;
    lastAnnouncement.value = announcement;

    try {
      await workCache.mutate(
        // **One request, and one endpoint.** The rank endpoint takes an optional stage, so
        // a cross-column drag is a single call whose rank the *server* computes from the
        // neighbours. A `rank` field on `PATCH` would have needed a midpoint calculated in
        // the browser, which is a second implementation of the one algebra
        // `RANK_NEIGHBOR_STALE` exists to protect.
        () =>
          api().rankTask(card.id, {
            version: card.version,
            previous_task_id: previous?.id ?? null,
            next_task_id: next?.id ?? null,
            ...(lifecycleStage ? { stage: lifecycleStage } : {}),
          }),
        {
          apply: () => {
            if (lifecycleStage) {
              pending.value = { ...pending.value, [card.id]: lifecycleStage };
            }
          },
          rollback: () => {
            const { [card.id]: _reverted, ...rest } = pending.value;
            pending.value = rest;
          },
        },
      );
      onInvalidate();
      return {
        ok: true,
        reason: null,
        announcement: `${announcement}，已完成`,
      };
    } catch (error) {
      onInvalidate();
      const reason = explainMoveFailure(error);
      return {
        ok: false,
        reason,
        announcement: `${card.card_ref} 沒有移動：${reason}`,
      };
    }
  }

  return { pending, lastAnnouncement, move };
}
