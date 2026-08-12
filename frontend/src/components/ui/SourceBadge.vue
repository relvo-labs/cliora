<script setup lang="ts">
import { computed } from "vue";
import BaseBadge from "./BaseBadge.vue";
import {
  labelFor,
  SOURCE_AGENT,
  SOURCE_MACHINE,
  SOURCE_PLATFORM,
  sourceLabels,
} from "./labels";

const props = defineProps<{ source: string }>();
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
</script>

<template>
  <BaseBadge :variant="presentation.variant" :tone="presentation.tone">
    {{ labelFor(sourceLabels, source) }}
  </BaseBadge>
</template>
