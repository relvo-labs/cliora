// Transient confirmations. Success and info only.
//
// The type has no "error" member, and that is the design rather than an
// omission:
//
//   type ToastKind = "success" | "info";
//
// A message that removes itself after a few seconds is a message the user may
// never have seen. For a confirmation that is fine — the thing already
// happened, and the effect is visible on the page. For a failure it is not:
// there is something the user has to decide, and a notice that leaves cannot be
// re-read. So upload failures, terminate failures and connection failures stay
// in the region they belong to (UiInlineNotice, ErrorNotice) and stay put.
//
// Encoding that in the type rather than in a comment is deliberate. A rule in a
// document gets discovered after the pattern has spread; a rule in the type
// fails to compile the first time.

import { readonly, ref } from "vue";

export type ToastKind = "success" | "info";

export interface Toast {
  id: number;
  kind: ToastKind;
  message: string;
}

const DISMISS_MS = 4000;

// Module scope, not per-component: a toast raised by a dialog has to outlive
// the dialog that raised it, which is the usual case ("created" is shown after
// the create form closes).
const toasts = ref<Toast[]>([]);
let nextId = 0;
const timers = new Map<number, number>();

function dismiss(id: number): void {
  toasts.value = toasts.value.filter((t) => t.id !== id);
  const timer = timers.get(id);
  if (timer !== undefined) {
    window.clearTimeout(timer);
    timers.delete(id);
  }
}

function push(kind: ToastKind, message: string): number {
  const id = (nextId += 1);
  toasts.value = [...toasts.value, { id, kind, message }];
  timers.set(
    id,
    window.setTimeout(() => dismiss(id), DISMISS_MS),
  );
  return id;
}

export function useToast() {
  return {
    toasts: readonly(toasts),
    success: (message: string) => push("success", message),
    info: (message: string) => push("info", message),
    dismiss,
  };
}
