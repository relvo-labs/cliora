<script setup lang="ts">
// Three colours, ten words. What a reader has to tell apart at a glance is
// "this is a rule / this is an observation / this is something somebody said";
// the exact level is what the text is for, and ten colours would be ten shades
// nobody can distinguish.
import { computed } from "vue";

import { authorityLabel, authorityTier } from "../queries";

const props = defineProps<{ authority: string; version?: string }>();

const tier = computed(() => authorityTier(props.authority));
const label = computed(() => authorityLabel(props.authority));
</script>

<template>
  <span class="badge" :class="`badge--${tier}`" :data-authority="authority">
    <span class="badge__label">{{ label }}</span>
    <span v-if="version" class="badge__version">{{ version }}</span>
  </span>
</template>

<style scoped>
.badge {
  display: inline-flex;
  align-items: baseline;
  gap: var(--space-1);
  padding: 0 var(--space-2);
  border-radius: var(--radius-sm);
  font-size: var(--font-xs);
  white-space: nowrap;
}
.badge--high {
  background: var(--authority-high);
  color: var(--text-inverse);
}
.badge--mid {
  background: var(--authority-mid);
  color: var(--text-inverse);
}
.badge--low {
  background: var(--authority-low);
  color: var(--text-primary);
}
.badge--stale {
  background: var(--source-stale);
  color: var(--text-secondary);
  text-decoration: line-through;
}
.badge__version {
  font-family: var(--font-mono);
  opacity: 0.85;
}
</style>
