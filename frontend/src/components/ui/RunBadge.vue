<script setup lang="ts">
import { computed } from "vue";
import type { RunStatus } from "../../api/dto";
import BaseBadge from "./BaseBadge.vue";
import { labelFor, runLabels } from "./labels";

const props = defineProps<{ status: RunStatus; runnerName?: string | null }>();
const known = computed(() => props.status in runLabels);
const active = computed(() =>
  ["running", "waiting_for_input"].includes(props.status),
);
const label = computed(() => {
  const value = labelFor(runLabels, props.status);
  return props.status === "running" && props.runnerName
    ? `${value} · ${props.runnerName}`
    : value;
});
</script>

<template>
  <BaseBadge
    :variant="known ? 'solid' : 'quiet'"
    :tone="known ? `run-${status.replaceAll('_', '-')}` : 'neutral'"
    :pulse="known && active"
  >
    {{ label }}
  </BaseBadge>
</template>
