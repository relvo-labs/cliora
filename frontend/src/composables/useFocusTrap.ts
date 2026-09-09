// Focus containment, Escape, and focus return — for the Dialog and the file
// drawer, which share it.
//
// This exists because plan/28 removed `naive-ui` (ADR 0027 §6). The shared
// design foundation assumed these behaviours would come from "existing UI
// component capabilities", but the library it named had never been used, so
// "retaining" it would have meant introducing it. Two of the four behaviours it
// listed already existed and were correct (WorkspaceTabs' roving tabindex,
// FileTree's keyboard handling); these are the other two.
//
// What `ConfirmDialog` had before, and what each part here fixes:
//
//   * `aria-modal="true"` and nothing else. That attribute changes what a
//     screen reader's virtual cursor can reach; it does not change the Tab
//     order at all, so Tab walked straight out of the dialog and into the page
//     behind it.
//   * No Escape. The only way to dismiss was clicking the backdrop, which a
//     keyboard user cannot do.
//   * No focus return. Closing dropped focus to <body>, so the next Tab
//     restarted from the top of the document.

import { onScopeDispose, watch, type Ref } from "vue";

// Not `[tabindex]:not([tabindex="-1"])` alone: a dialog's first control is
// often a button, and a programmatically-focusable container (tabindex="-1")
// must not become a tab stop. `:not([inert] *)` keeps a hidden subtree out.
const FOCUSABLE = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled]):not([type='hidden'])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(",");

function focusable(container: HTMLElement): HTMLElement[] {
  return Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
    // offsetParent is null for a `display: none` subtree. A dialog can hide a
    // field behind a disclosure, and a hidden field must not swallow the Tab
    // that was meant to wrap around to the first visible one.
    (el) => el.offsetParent !== null || el === document.activeElement,
  );
}

export interface FocusTrapOptions {
  /** Escape, or a click outside. Both are "the user asked to leave". */
  onEscape?: () => void;
  /**
   * Where focus goes on open. Defaults to the first focusable element, which is
   * right for a form and wrong for a destructive confirmation — there the
   * caller points this at Cancel so a stray Enter does not confirm.
   */
  initial?: Ref<HTMLElement | undefined>;
}

/**
 * Traps focus inside `container` while `active` is true.
 *
 * Returns nothing: everything it does is a side effect on the DOM, and giving
 * it a handle would invite callers to move focus themselves halfway through.
 */
export function useFocusTrap(
  container: Ref<HTMLElement | undefined>,
  active: Ref<boolean>,
  options: FocusTrapOptions = {},
): void {
  // The element to hand focus back to. Captured at open rather than at close:
  // by close time the trigger may have been re-rendered or removed, and
  // `document.activeElement` is by then the dialog's own button.
  let returnTo: HTMLElement | undefined;

  function onKeydown(event: KeyboardEvent): void {
    const root = container.value;
    if (!root) return;

    if (event.key === "Escape") {
      // stopPropagation as well as preventDefault: nested traps (a confirmation
      // opened from a drawer) must close one layer, not both.
      event.preventDefault();
      event.stopPropagation();
      options.onEscape?.();
      return;
    }

    if (event.key !== "Tab") return;

    const items = focusable(root);
    if (items.length === 0) {
      // Nothing to focus, so keep the Tab rather than let it escape to the page
      // behind. A dialog with no controls is a bug, but leaking focus out of it
      // is a worse one.
      event.preventDefault();
      return;
    }

    const first = items[0];
    const last = items[items.length - 1];
    const activeEl = document.activeElement as HTMLElement | null;

    // Focus can be outside the container even while the trap is on: the user
    // clicked the page behind, or a re-render replaced the focused node. Pull
    // it back rather than doing nothing.
    if (!activeEl || !root.contains(activeEl)) {
      event.preventDefault();
      (event.shiftKey ? last : first).focus();
      return;
    }

    if (event.shiftKey && activeEl === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && activeEl === last) {
      event.preventDefault();
      first.focus();
    }
  }

  watch(
    active,
    (isActive, wasActive) => {
      if (isActive && !wasActive) {
        returnTo = (document.activeElement as HTMLElement | null) ?? undefined;
        // Wait a tick: `active` usually flips in the same change that mounts the
        // container, so the DOM does not exist yet on this line.
        requestAnimationFrame(() => {
          const root = container.value;
          if (!root || !active.value) return;
          const target = options.initial?.value ?? focusable(root)[0] ?? root;
          target.focus();
        });
        // Capture phase, so this sees Escape before a child that also handles
        // it (a search field clearing itself, say).
        document.addEventListener("keydown", onKeydown, true);
      } else if (!isActive && wasActive) {
        document.removeEventListener("keydown", onKeydown, true);
        // Only if the trigger is still in the document: focusing a detached
        // node silently does nothing and leaves focus on <body>, which is the
        // bug this is here to fix.
        if (returnTo && document.contains(returnTo)) returnTo.focus();
        returnTo = undefined;
      }
    },
    { immediate: true },
  );

  onScopeDispose(() => {
    document.removeEventListener("keydown", onKeydown, true);
  });
}
