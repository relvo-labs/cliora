<script setup lang="ts">
// An icon-only button. `label` is required, not optional.
//
// That is the whole point of the component existing separately. The shared
// foundation asks for `aria-label` *and* a tooltip, and the two are not
// interchangeable: the tooltip is for a mouse, the `aria-label` is for a screen
// reader. Making the prop required means an unnamed icon button cannot be
// written by accident — which is how seven text glyphs ended up in the nav rail
// as readable text nodes that a screen reader would pronounce, with the
// pronunciation decided by whatever font matched.

import { computed } from "vue";

const props = withDefaults(
  defineProps<{
    /** Announced name. Also the tooltip, unless `tooltip` overrides it. */
    label: string;
    /** When the hover text should be longer than the announced name. */
    tooltip?: string;
    variant?: "quiet" | "secondary" | "danger" | "on-terminal";
    disabled?: boolean;
    disabledReason?: string;
    busy?: boolean;
    /** Pressed state for a toggle (a collapse control, a filter). */
    pressed?: boolean;
    /** Points at what this controls, for a disclosure. */
    controls?: string;
    /** Disclosure state, when this opens something. */
    expanded?: boolean;
  }>(),
  { variant: "quiet" },
);

const emit = defineEmits<{ click: [MouseEvent] }>();
const inactive = computed(() => props.disabled || props.busy);
</script>

<template>
  <button
    type="button"
    :class="['icon-btn', variant]"
    :aria-label="label"
    :title="disabled && disabledReason ? disabledReason : (tooltip ?? label)"
    :aria-pressed="pressed"
    :aria-expanded="expanded"
    :aria-controls="controls"
    :aria-busy="busy ? 'true' : undefined"
    :disabled="inactive"
    @click="emit('click', $event)"
  >
    <slot />
  </button>
</template>

<style scoped>
.icon-btn {
  display: inline-grid;
  place-items: center;
  /* The visual box is compact; the hit area below reaches the touch floor. */
  width: 32px;
  height: 32px;
  border: 1px solid transparent;
  border-radius: var(--radius-control);
  background: transparent;
  color: var(--text-secondary);
  position: relative;
}
.icon-btn::after {
  content: "";
  position: absolute;
  inset: 50% 50% auto auto;
  width: var(--density-touch);
  height: var(--density-touch);
  transform: translate(50%, -50%);
}
.icon-btn :deep(svg) {
  width: 18px;
  height: 18px;
}

.quiet:hover:not(:disabled) {
  background: var(--surface-raised);
  color: var(--text-primary);
}
.secondary {
  background: var(--surface-raised);
  border-color: var(--border-control);
  color: var(--text-primary);
}
.secondary:hover:not(:disabled) {
  border-color: var(--accent-strong);
}
.danger {
  color: var(--status-error-fg);
}
.danger:hover:not(:disabled) {
  background: var(--status-error-bg);
}
/* Sitting on the terminal surface, where neither the panel text colour nor the
   panel border is correct — in a light theme both would be near-black on a dark
   terminal. */
.on-terminal {
  color: var(--text-on-terminal-dim);
}
.on-terminal:hover:not(:disabled) {
  background: var(--surface-on-terminal);
  color: var(--text-on-terminal);
}

.icon-btn[aria-pressed="true"] {
  background: var(--accent-subtle);
  color: var(--accent-strong);
}
.icon-btn:disabled {
  cursor: not-allowed;
  color: var(--text-disabled);
}
</style>
