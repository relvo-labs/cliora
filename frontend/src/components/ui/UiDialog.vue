<script setup lang="ts">
// A modal with the three behaviours the previous dialog did not have.
//
// `ConfirmDialog` had `role="dialog"` and `aria-modal="true"` and stopped
// there, which looks complete and is not:
//
//   * `aria-modal` changes what a screen reader's virtual cursor can reach. It
//     does not touch the Tab order, so Tab walked out of the dialog and into
//     the page behind it.
//   * There was no Escape. The only dismissal was a backdrop click, which a
//     keyboard user cannot perform.
//   * There was no focus return. Closing left focus on <body>, so the next Tab
//     started again from the top of the document.
//
// All three come from useFocusTrap, which the file drawer shares — the drawer
// is also a thing that traps focus and must give it back.

import { computed, ref, useId, watch } from "vue";

import { useFocusTrap } from "../../composables/useFocusTrap";

const props = withDefaults(
  defineProps<{
    open: boolean;
    title: string;
    /** Widths that fit content; not a percentage of an unknown viewport. */
    width?: "narrow" | "wide";
    /**
     * Blocks dismissal while a request is in flight, so a half-applied action
     * cannot be walked away from. Escape and the backdrop both stop working.
     */
    busy?: boolean;
    /**
     * Focus Cancel rather than the first control on open. For a destructive
     * confirmation the default is wrong: the first control is usually the
     * confirm button, and a stray Enter would then perform the action.
     */
    focusCancel?: boolean;
  }>(),
  { width: "narrow" },
);

const emit = defineEmits<{ cancel: [] }>();

const panel = ref<HTMLElement>();
const titleId = useId();

function requestClose(): void {
  if (props.busy) return;
  emit("cancel");
}

// The element to focus first, found by marker attribute rather than passed in
// as a ref through a scoped slot. The caller writes `data-dialog-initial` on
// the control it wants; threading a ref setter through the slot meant every
// caller unwrapping a component instance to reach its root element, which is
// exactly the kind of plumbing that gets copied wrongly.
const initial = computed(() =>
  props.focusCancel
    ? (panel.value?.querySelector<HTMLElement>("[data-dialog-initial]") ??
      undefined)
    : undefined,
);

useFocusTrap(
  panel,
  computed(() => props.open),
  { onEscape: requestClose, initial },
);

// While a modal is open the page behind it must not scroll: scrolling the
// backdrop moves content the user cannot interact with, and on the workspace it
// would fight the layout that owns the viewport height.
watch(
  () => props.open,
  (open) => {
    document.body.style.overflow = open ? "hidden" : "";
  },
);
</script>

<template>
  <!-- @click.self, so a click that started inside the panel and ended on the
       backdrop (a drag across a text selection) does not close it. -->
  <div v-if="open" class="backdrop" @click.self="requestClose">
    <div
      ref="panel"
      class="panel"
      :data-width="width"
      role="dialog"
      aria-modal="true"
      :aria-labelledby="titleId"
    >
      <h2 :id="titleId">{{ title }}</h2>
      <!-- A slot rather than a message string: a Terminate confirmation has to
           show the session's name, and it has to be marked up as a name rather
           than concatenated into a sentence where it can be mistaken for prose
           (Graphite §5). -->
      <div class="body"><slot /></div>
      <div class="actions"><slot name="actions" /></div>
    </div>
  </div>
</template>

<style scoped>
.backdrop {
  position: fixed;
  inset: 0;
  z-index: 30;
  display: grid;
  place-items: center;
  padding: 16px;
  background: var(--surface-scrim);
}
.panel {
  width: 100%;
  /* 100% of the backdrop, not of the viewport. The backdrop is already
     `position: fixed; inset: 0` with 16px of padding, so this resolves to
     exactly "the viewport less the padding" without naming a viewport unit —
     and plan/09 D1 keeps viewport height in one place, the app shell. A tall
     dialog therefore scrolls inside itself rather than off the screen. */
  max-height: 100%;
  overflow: auto;
  padding: 24px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-dialog);
  background: var(--surface-raised);
  box-shadow: var(--shadow-overlay);
}
.panel[data-width="narrow"] {
  max-width: 440px;
}
.panel[data-width="wide"] {
  max-width: 640px;
}
h2 {
  margin: 0 0 10px;
  font-size: 17px;
  color: var(--text-primary);
}
.body {
  color: var(--text-secondary);
  font-size: 13px;
  line-height: 1.6;
}
.actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 22px;
}

@media (prefers-reduced-motion: no-preference) {
  .panel {
    animation: appear var(--motion-base) ease;
  }
}
@keyframes appear {
  from {
    opacity: 0;
    transform: translateY(6px);
  }
}
</style>
