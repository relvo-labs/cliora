<script setup lang="ts">
import { computed } from "vue";
import BaseBadge from "./BaseBadge.vue";
import { deliveryLabels, labelFor } from "./labels";

const props = defineProps<{ delivery: string }>();
const known = computed(() => props.delivery in deliveryLabels);
const quiet = computed(() => !known.value || props.delivery === "none");
</script>

<template>
  <BaseBadge
    :variant="quiet ? 'quiet' : 'outline'"
    :tone="known ? `delivery-${delivery.replaceAll('_', '-')}` : 'neutral'"
  >
    {{ labelFor(deliveryLabels, delivery) }}
  </BaseBadge>
</template>
