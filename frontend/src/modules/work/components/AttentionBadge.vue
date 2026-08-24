<script setup lang="ts">
/**
 * The one card-level answer to "why does this need me" (PX-18, plan/26/06 §3.2).
 *
 * **The server chose the level; this draws it.** There is no ranking here and no
 * fallback that guesses a level from other fields — `derive_attention` is the single
 * definition (plan/26/03 §2), and a second one in the browser is how the board and the
 * Drawer start disagreeing.
 *
 * **Four cues, where the accessibility rule asks for two** (research/style.md §22): the
 * label is always text, a glyph sits beside it, the two levels where a person is
 * actively being waited on are a solid fill against the rest's left-barred tint, and
 * colour comes fourth.
 *
 * **The words are `--text-primary`, not the attention colour**, on every tinted variant.
 * `--attention-warning` is amber and amber on white is about 2.9:1 — legible as a 3px
 * bar and a glyph, not as an 11px sentence. The colour still carries meaning; it just
 * does not carry the reading. The solid variant keeps `--text-inverse` on the fill,
 * which is the treatment `plan/19` D24 already shipped for level 1.
 *
 * `count` is the *total* number of signals on the card. Anything past the primary is
 * shown as "＋N" and expanded in the Drawer (D107) — putting all eight on a card is how
 * a board becomes a wall of warnings nobody reads.
 */
import { computed } from "vue";

import { ATTENTION, isAttentionLevel } from "../attention";

const props = withDefaults(
  defineProps<{
    primary: string;
    count?: number;
    density?: "comfortable" | "compact";
  }>(),
  { count: 1, density: "comfortable" },
);

const level = computed(() =>
  isAttentionLevel(props.primary) ? ATTENTION[props.primary] : null,
);
const extra = computed(() => Math.max(0, props.count - 1));
/** The accessible name says everything the badge means, including the "＋N" that the
 *  glyph beside it renders as decoration. */
const description = computed(() =>
  level.value === null
    ? ""
    : extra.value > 0
      ? `${level.value.label}，另有 ${extra.value} 項`
      : level.value.label,
);
</script>

<template>
  <span
    v-if="level"
    class="attention"
    :class="[`v-${level.variant}`, `t-${level.tone}`, `d-${density}`]"
    role="status"
    :aria-label="description"
    :data-attention="primary"
  >
    <span class="glyph" aria-hidden="true">{{ level.glyph }}</span>
    <span class="label">{{
      density === "compact" ? level.short : level.label
    }}</span>
    <span v-if="extra > 0" class="extra" aria-hidden="true">＋{{ extra }}</span>
  </span>
</template>

<style scoped>
.attention {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-height: 22px;
  padding: 3px var(--space-2);
  border-radius: var(--radius-sm);
  font-size: var(--font-xs);
  font-weight: 700;
  line-height: 1.35;
  overflow: hidden;
}
/* The shape cue: a filled strip for the two levels somebody is waiting on, a left rule
 * on a quiet tint for the six that report a condition. */
.v-solid {
  background: currentColor;
}
.v-solid .glyph,
.v-solid .label,
.v-solid .extra {
  color: var(--text-inverse);
}
.v-outline {
  border-left: 3px solid currentColor;
  background: color-mix(in srgb, currentColor 10%, var(--surface-elevated));
}
.v-outline .label,
.v-outline .extra {
  color: var(--text-primary);
}
.d-compact {
  min-height: 18px;
  padding: 1px var(--space-2);
}
.glyph {
  flex: none;
  font-size: var(--font-sm);
  line-height: 1;
}
.label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.extra {
  flex: none;
  margin-left: auto;
  font-variant-numeric: tabular-nums;
}
.t-attention-human {
  color: var(--attention-human);
}
.t-attention-approval {
  color: var(--attention-approval);
}
.t-attention-blocked {
  color: var(--attention-blocked);
}
.t-attention-failed {
  color: var(--attention-failed);
}
.t-attention-warning {
  color: var(--attention-warning);
}
</style>
