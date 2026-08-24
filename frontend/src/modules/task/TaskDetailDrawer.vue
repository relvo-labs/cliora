<script setup lang="ts">
/**
 * The Drawer shell (PX-38, plan/26/07 §2). **A shell, not a layout.**
 *
 * What this owns is the container and the way in and out of it: dialog semantics, the
 * focus trap and its restoration, Escape, the backdrop, and the link to the full page.
 * What it deliberately does not own is the order of the sections inside — that is
 * `PX-39`, and until then the existing card detail renders unchanged so that the
 * container can be judged on its own.
 *
 * **Not a modal** (kintra's rule, adopted word for word in plan/26/07 §1). A modal makes
 * the board behind it inert, and not interrupting the board is the entire reason this
 * exists. The backdrop dims and closes on click; it does not block scrolling behind it.
 *
 * **The full page stays** (`/projects/:id/tasks/:taskId`, on the phase's do-not-touch
 * list). "Open in a new tab" is the only degradation path left after D117 removed the
 * version flag, so it is a real link with a real `href` — not a click handler — because
 * middle-click and "copy link address" are the two things people actually do with it.
 */
import { computed, nextTick, onBeforeUnmount, ref, watch } from "vue";
import { RouterLink } from "vue-router";

const props = defineProps<{
  projectId: string;
  taskId: string | null;
  /** Shown in the header before the card loads, so the Drawer does not open blank. */
  title?: string | null;
  cardRef?: string | null;
}>();
const emit = defineEmits<{ (event: "close"): void }>();

const panel = ref<HTMLElement | null>(null);
/** Where focus was before the Drawer opened. Restored on close, because a reader who
 *  pressed Escape expects to be back on the card they pressed it from — not at the top
 *  of the document with the board scrolled away under them. */
const restoreTo = ref<HTMLElement | null>(null);

const open = computed(() => props.taskId !== null);
const heading = computed(() => props.cardRef ?? "任務");

const FOCUSABLE = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(",");

function focusable(): HTMLElement[] {
  if (!panel.value) return [];
  // No visibility filter. `offsetParent` is the usual one and it is always null under
  // jsdom, so the trap would be untestable and would silently degrade to "the element
  // that already has focus". Sections in this Drawer are collapsed with `v-if`, so what
  // is not rendered is not in the list to begin with; a future `v-show` section is the
  // case to revisit this for, and it will fail this component's test when it arrives.
  return Array.from(panel.value.querySelectorAll<HTMLElement>(FOCUSABLE));
}

/** The trap. Tab from the last element wraps to the first and Shift+Tab the other way,
 *  so a keyboard reader cannot walk out of the Drawer into a board they cannot see. */
function onKeydown(event: KeyboardEvent): void {
  if (event.key === "Escape") {
    event.stopPropagation();
    emit("close");
    return;
  }
  if (event.key !== "Tab") return;
  const elements = focusable();
  if (elements.length === 0) return;
  const first = elements[0];
  const last = elements[elements.length - 1];
  const active = document.activeElement;
  if (event.shiftKey && (active === first || active === panel.value)) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && active === last) {
    event.preventDefault();
    first.focus();
  }
}

watch(
  open,
  async (isOpen, wasOpen) => {
    if (isOpen && !wasOpen) {
      restoreTo.value =
        document.activeElement instanceof HTMLElement
          ? document.activeElement
          : null;
      await nextTick();
      // The panel itself, not its first control: the reader has just arrived and the
      // heading is what they need read out, not the first button they could press.
      panel.value?.focus();
    } else if (!isOpen && wasOpen) {
      restoreTo.value?.focus();
      restoreTo.value = null;
    }
  },
  { immediate: true },
);

onBeforeUnmount(() => {
  restoreTo.value = null;
});
</script>

<template>
  <div v-if="open" class="drawer-root">
    <!-- Dims and closes; does not trap the pointer. The board keeps scrolling. -->
    <div class="backdrop" data-drawer-backdrop @click="emit('close')"></div>
    <section
      ref="panel"
      class="panel"
      role="dialog"
      aria-modal="false"
      :aria-label="`任務 ${heading}`"
      tabindex="-1"
      data-task-drawer
      @keydown="onKeydown"
    >
      <header class="head" data-drawer-head>
        <div class="identity">
          <div class="ref-row">
            <span class="ref">{{ heading }}</span>
            <!-- The attention badge sits with the identity, which is where the plan's
                 mock puts it: a reader opening a card already knows *which* card, and what
                 they need next is why it needed them. -->
            <slot name="badge" />
          </div>
          <h2 v-if="title">{{ title }}</h2>
        </div>
        <div class="controls">
          <RouterLink
            v-if="taskId"
            class="ghost"
            target="_blank"
            rel="noopener"
            :to="{ name: 'task-detail', params: { id: projectId, taskId } }"
            data-drawer-newtab
          >
            開新分頁
          </RouterLink>
          <button
            type="button"
            class="ghost"
            aria-label="關閉任務面板"
            data-drawer-close
            @click="emit('close')"
          >
            ✕
          </button>
        </div>
      </header>
      <div class="body" data-drawer-body>
        <slot />
      </div>
    </section>
  </div>
</template>

<style scoped>
.drawer-root {
  position: fixed;
  inset: 0;
  z-index: 40;
  display: flex;
  justify-content: flex-end;
  pointer-events: none;
}
.backdrop {
  position: absolute;
  inset: 0;
  pointer-events: auto;
  background: color-mix(in srgb, var(--text-primary) 24%, transparent);
}
.panel {
  position: relative;
  pointer-events: auto;
  display: flex;
  flex-direction: column;
  width: min(920px, 100vw);
  /* 720–920px by viewport (plan/26/07 §2). `min()` rather than a media query: the
   * breakpoint is the content's, not a device's. */
  min-width: min(720px, 100vw);
  height: 100%;
  background: var(--surface-canvas);
  border-left: 1px solid var(--border-default);
  box-shadow: -8px 0 24px
    color-mix(in srgb, var(--text-primary) 12%, transparent);
}
.panel:focus-visible {
  outline: 2px solid var(--border-focus);
  outline-offset: -2px;
}
.head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-4);
  border-bottom: 1px solid var(--border-default);
  background: var(--surface-elevated);
}
.identity {
  min-width: 0;
}
.ref-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
.ref {
  display: block;
  font-family: var(--font-mono);
  font-size: var(--font-xs);
  color: var(--text-muted);
}
.identity h2 {
  margin: 2px 0 0;
  font-size: var(--font-md);
  line-height: 1.35;
}
.controls {
  display: flex;
  flex: none;
  gap: var(--space-2);
}
.controls .ghost {
  padding: 4px 10px;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  background: var(--surface-elevated);
  color: var(--text-secondary);
  font-size: var(--font-xs);
  text-decoration: none;
  cursor: pointer;
}
.controls .ghost:hover {
  border-color: var(--action-primary);
  color: var(--text-primary);
}
.body {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-4);
}
/* Mobile is a full-screen overlay rather than a narrower drawer (plan/26/07 §2, and
 * `PX-46` refines what is inside it). */
@media (max-width: 760px) {
  .panel {
    width: 100vw;
    min-width: 0;
    border-left: none;
  }
  /* **The header stays.** It already does — `.panel` is a flex column and `.body` is the
   * only thing that scrolls — but `flex: none` is stated rather than inherited, because
   * the failure mode is silent: one long card reference wraps, the head grows, and on a
   * phone the close button walks off the top of a scrolling panel. `PX-46` names a fixed
   * header as a requirement, so it gets a line that says so.
   *
   * `padding-bottom: 0` hands the last strip of the panel to the composer, which is
   * sticky inside `.body` (`ConversationPanel`) — its own padding replaces this one. */
  .head {
    flex: none;
    position: sticky;
    top: 0;
    z-index: 2;
    padding: var(--space-3);
  }
  .body {
    padding: var(--space-3) var(--space-3) 0;
  }
}
</style>
