<script setup lang="ts">
// The one button. Four variants, and the variant is what carries the meaning —
// `danger` is not "primary but red", it is an action that must not sit in the
// everyday primary position (Graphite §5).
//
// Two rules are enforced here rather than left to each caller:
//
//   * A disabled button keeps a readable label and states its reason. Opacity
//     is not used to signal disabled, because opacity makes the reason
//     unreadable along with the label. `--text-disabled` is measured at >= 3:1
//     on all three surfaces for exactly this.
//   * A busy button says so to assistive technology (`aria-busy`) and stays
//     the same size, so the layout does not jump while a request is in flight.

import { computed } from "vue";

const props = withDefaults(
  defineProps<{
    variant?: "primary" | "secondary" | "quiet" | "danger";
    type?: "button" | "submit";
    disabled?: boolean;
    busy?: boolean;
    /**
     * Why the button is disabled. Required whenever `disabled` is set — a
     * control the user cannot use has to say why, or the only way to find out
     * is to guess. Surfaced as `title` here; a caller with room should also say
     * it in visible text.
     */
    disabledReason?: string;
    full?: boolean;
  }>(),
  { variant: "secondary", type: "button" },
);

const emit = defineEmits<{ click: [MouseEvent] }>();

// Busy implies disabled: a second click while the first request is in flight is
// never what the user meant.
const inactive = computed(() => props.disabled || props.busy);
</script>

<template>
  <button
    :type="type"
    :class="['btn', variant, { full }]"
    :disabled="inactive"
    :aria-busy="busy ? 'true' : undefined"
    :title="disabled ? disabledReason : undefined"
    @click="emit('click', $event)"
  >
    <slot name="icon" />
    <span class="label"><slot /></span>
  </button>
</template>

<style scoped>
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  /* The visual height is the control density; the hit area is topped up to the
     touch floor below, so a compact desktop button is still a 44px target. */
  min-height: var(--density-control);
  padding: 0 14px;
  border: 1px solid transparent;
  border-radius: var(--radius-control);
  font-size: 13px;
  font-weight: 500;
  white-space: nowrap;
  position: relative;
}
.btn.full {
  width: 100%;
}
/* Touch target. A pseudo-element rather than padding, so the button's visual
   box stays at the density height while the tappable box reaches 44px
   (the shared foundation allows exactly this for compact desktop controls). */
.btn::after {
  content: "";
  position: absolute;
  inset: 50% 0 auto;
  min-height: var(--density-touch);
  transform: translateY(-50%);
  height: 100%;
}

.primary {
  /* accent-strong, not accent-primary: in two of the five themes
     accent-primary cannot carry a label at 4.5:1. accent-primary is left for
     fills that carry no text. */
  background: var(--accent-strong);
  border-color: var(--accent-strong);
  color: var(--text-on-accent);
  font-weight: 600;
}
.primary:hover:not(:disabled) {
  background: var(--accent-hover);
  border-color: var(--accent-hover);
}

.secondary {
  background: var(--surface-raised);
  /* border-control, not border-subtle: this is a necessary control boundary.
     border-subtle measures 1.21-1.61:1 against a panel in all five themes. */
  border-color: var(--border-control);
  color: var(--text-primary);
}
.secondary:hover:not(:disabled) {
  background: var(--surface-default);
  border-color: var(--accent-strong);
}

.quiet {
  background: transparent;
  color: var(--accent-strong);
}
.quiet:hover:not(:disabled) {
  background: var(--accent-subtle);
}

.danger {
  background: var(--danger-bg);
  border-color: var(--danger-bg);
  color: var(--danger-fg);
  font-weight: 600;
}
.danger:hover:not(:disabled) {
  background: var(--danger-hover);
  border-color: var(--danger-hover);
}

/* No opacity. The label stays legible and the title carries the reason. */
.btn:disabled {
  cursor: not-allowed;
  background: var(--surface-raised);
  border-color: var(--border-control);
  color: var(--text-disabled);
}
.btn[aria-busy="true"] {
  cursor: progress;
}
</style>
