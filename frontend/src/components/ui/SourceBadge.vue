<script setup lang="ts">
// Where a fact came from, and — for a machine fact — who decided to check it.
//
// Three things here are decisions rather than styling (ADR 0033 §3b):
//
//  * **Both origins use the same solid style.** Their credibility is equal: declaring a
//    check on a card requires `task.approve`, which a run token never holds, so neither
//    store was chosen by the agent being verified. A paler card badge would assert on
//    screen something the data does not say.
//  * **`origin` is a second badge, never a shade.** The reviewer's next question after
//    "a machine ran it" is "who set the standard", and a colour cannot answer that.
//  * **"未經平台驗證" is text, not a tooltip.** It is the only place a person ever meets
//    the three-level grading, and a qualifier behind a hover is a qualifier nobody reads.
import { computed } from "vue";
import BaseBadge from "./BaseBadge.vue";
import {
  labelFor,
  originLabels,
  SOURCE_AGENT,
  SOURCE_MACHINE,
  SOURCE_PLATFORM,
  sourceLabels,
  UNVERIFIED_NOTE,
} from "./labels";

const props = defineProps<{ source: string; origin?: string | null }>();
const presentation = computed(() => {
  if (props.source === SOURCE_MACHINE) {
    return { variant: "solid" as const, tone: "source-machine" };
  }
  if (props.source === SOURCE_PLATFORM) {
    return { variant: "outline" as const, tone: "source-platform" };
  }
  if (props.source === SOURCE_AGENT) {
    return { variant: "quiet" as const, tone: "source-agent" };
  }
  return { variant: "quiet" as const, tone: "neutral" };
});
const showsOrigin = computed(
  () =>
    props.source === SOURCE_MACHINE &&
    !!props.origin &&
    props.origin in originLabels,
);
</script>

<template>
  <span class="source-badge">
    <BaseBadge :variant="presentation.variant" :tone="presentation.tone">
      {{ labelFor(sourceLabels, source) }}
    </BaseBadge>
    <BaseBadge v-if="showsOrigin" variant="outline" tone="neutral">
      {{ labelFor(originLabels, origin ?? "") }}
    </BaseBadge>
    <span v-if="source === SOURCE_AGENT" class="unverified">{{
      UNVERIFIED_NOTE
    }}</span>
  </span>
</template>

<style scoped>
.source-badge {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
}

.unverified {
  font-size: var(--font-xs);
  color: var(--text-muted);
}
</style>
