<script setup lang="ts">
import { computed } from "vue";
import BaseBadge from "./BaseBadge.vue";
import { labelFor, riskLabels } from "./labels";

const props = defineProps<{ risk: string }>();
const known = computed(() => props.risk in riskLabels);
</script>

<template>
  <BaseBadge
    :variant="known ? 'outline' : 'quiet'"
    :tone="known ? `risk-${risk}` : 'neutral'"
  >
    {{ labelFor(riskLabels, risk) }}
  </BaseBadge>
</template>
