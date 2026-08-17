// The card's conversation, as one small composable (`CV-10`).
//
// Deliberately **not** general. `beta.1` brings a query layer with keys and
// invalidation (`research/03` D56); building one now, for a single panel, would be
// paying for it a release early and guessing its shape from one caller.
//
// Two behaviours here are the product rather than plumbing:
//
//  * **new messages are merged by sequence and appended, never re-sorted.** Re-sorting
//    moves the scroll position under somebody who is reading.
//  * **a failed send never clears the draft.** What a person typed is theirs; losing it
//    to a 500 is the one failure in this panel they cannot recover from.

import { ref } from "vue";

import { ApiError } from "../../../api/client";
import type { TaskMessage, TaskQuestion } from "../../../api/dto";
import { api } from "../../../stores/auth";

/** How many messages the panel opens with. Older ones load on scroll-back. */
export const PAGE_SIZE = 50;

export function useConversation(taskId: () => string) {
  const messages = ref<TaskMessage[]>([]);
  const questions = ref<TaskQuestion[]>([]);
  const loading = ref(false);
  const hasOlder = ref(false);
  const error = ref<string | null>(null);

  /** Merge by `conversation_seq`: idempotent, so a re-read of a range is harmless. */
  function merge(incoming: TaskMessage[]): void {
    const seen = new Map(
      messages.value.map((item) => [item.conversation_seq, item]),
    );
    for (const item of incoming) seen.set(item.conversation_seq, item);
    messages.value = [...seen.values()].sort(
      (left, right) => left.conversation_seq - right.conversation_seq,
    );
  }

  async function load(): Promise<void> {
    loading.value = true;
    error.value = null;
    try {
      const page = await api().listTaskMessages(taskId(), { limit: PAGE_SIZE });
      messages.value = page.items;
      hasOlder.value = page.has_more;
      questions.value = await api().listTaskQuestions(taskId());
    } catch (caught) {
      error.value = describe(caught, "讀不到這張卡的對話。");
    } finally {
      loading.value = false;
    }
  }

  async function loadOlder(): Promise<void> {
    const oldest = messages.value[0];
    if (!oldest) return;
    loading.value = true;
    try {
      const page = await api().listTaskMessages(taskId(), {
        beforeSeq: oldest.conversation_seq,
        limit: PAGE_SIZE,
      });
      hasOlder.value = page.has_more;
      merge(page.items);
    } catch (caught) {
      error.value = describe(caught, "讀不到更早的訊息。");
    } finally {
      loading.value = false;
    }
  }

  /** Refresh without disturbing what is already on screen. */
  async function refresh(): Promise<void> {
    const newest = messages.value[messages.value.length - 1];
    const page = await api().listTaskMessages(taskId(), {
      afterSeq: newest ? newest.conversation_seq : 0,
      limit: PAGE_SIZE,
    });
    merge(page.items);
    questions.value = await api().listTaskQuestions(taskId());
  }

  return {
    messages,
    questions,
    loading,
    hasOlder,
    error,
    load,
    loadOlder,
    refresh,
    merge,
  };
}

export function describe(caught: unknown, fallback: string): string {
  if (caught instanceof ApiError) return caught.message;
  return caught instanceof Error ? caught.message : fallback;
}

/**
 * One key per composition, not per request.
 *
 * A double-clicked send is the case this exists for: two requests, one key, one
 * message. A key generated per request would be a new key each time and protect
 * nothing (ADR 0036 §3).
 */
export function newIdempotencyKey(): string {
  return globalThis.crypto?.randomUUID
    ? globalThis.crypto.randomUUID()
    : `k-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}
