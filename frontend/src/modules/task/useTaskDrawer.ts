// The Drawer's one piece of state lives in the URL (PX-38, plan/26/07 §4, D111).
//
// **`router.replace`, never `push`.** Opening a card is not a navigation the reader
// asked for; it is a detail on top of the board they are already reading. With `push`,
// scanning eight cards puts eight entries in the history and "back" walks the reader
// through their own scanning rather than out of the page. With `replace`, the sequence
// D111 asks for falls out for free: back closes the Drawer, back again restores the
// view, back again leaves the project.
//
// **Only the `task` key is touched.** Closing must leave `view`, the filter and the tab
// exactly as they were — the whole point of a Drawer is that the thing behind it
// survives.

import { computed, type ComputedRef } from "vue";
import { useRoute, useRouter } from "vue-router";

export interface TaskDrawer {
  /** The task the URL currently names, or null. */
  taskId: ComputedRef<string | null>;
  /** Which field the Drawer should focus once it has loaded, or null.
   *
   *  In the URL alongside `task=` rather than in a store, for the same reason `task=` is:
   *  a link to "this card, on the thing that is missing" is a sentence people send each
   *  other, and a reload has to land in the same place. It is **consumed once** — the
   *  Drawer clears it after focusing, so a later reload of the same URL does not yank
   *  focus away from whatever the reader was doing. */
  focus: ComputedRef<string | null>;
  open: (taskId: string, focus?: string) => Promise<void>;
  clearFocus: () => Promise<void>;
  close: () => Promise<void>;
}

export function useTaskDrawer(): TaskDrawer {
  const route = useRoute();
  const router = useRouter();

  const taskId = computed(() => {
    const value = route.query.task;
    // `?task=a&task=b` arrives as an array. Nobody writes that by hand; a stale link
    // and a double-append bug both can, and picking the first is stable where throwing
    // would take down the board behind the Drawer.
    const first = Array.isArray(value) ? value[0] : value;
    return typeof first === "string" && first.length > 0 ? first : null;
  });

  const focus = computed(() => {
    const value = route.query.focus;
    const first = Array.isArray(value) ? value[0] : value;
    return typeof first === "string" && first.length > 0 ? first : null;
  });

  async function open(next: string, target?: string): Promise<void> {
    // **Not short-circuited on the same id when a focus target is given.** Re-opening the
    // card that is already open in order to point at a field is a real request — it is
    // what "fill it in" does when the Drawer happens to be open already.
    if (taskId.value === next && !target) return;
    const query: Record<string, unknown> = { ...route.query, task: next };
    if (target) query.focus = target;
    else delete query.focus;
    await router.replace({ query: query as never });
  }

  async function clearFocus(): Promise<void> {
    if (focus.value === null) return;
    const { focus: _used, ...rest } = route.query;
    await router.replace({ query: rest });
  }

  async function close(): Promise<void> {
    if (taskId.value === null) return;
    // `focus` goes with it: it describes a card that is no longer open.
    const { task: _closed, focus: _target, ...rest } = route.query;
    await router.replace({ query: rest });
  }

  return { taskId, focus, open, clearFocus, close };
}
