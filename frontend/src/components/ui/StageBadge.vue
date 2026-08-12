<script setup lang="ts">
import { computed } from "vue";
import type { TaskStage } from "../../api/dto";
import BaseBadge from "./BaseBadge.vue";
import { labelFor, stageLabels } from "./labels";

const props = defineProps<{ stage: TaskStage }>();
const known = computed(() => props.stage in stageLabels);
</script>

<template>
  <BaseBadge
    :variant="known ? 'solid' : 'quiet'"
    :tone="known ? `stage-${stage}` : 'neutral'"
  >
    {{ labelFor(stageLabels, stage) }}
  </BaseBadge>
</template>
