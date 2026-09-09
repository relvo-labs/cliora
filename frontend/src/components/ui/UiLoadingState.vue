<script setup lang="ts">
// A region that is loading.
//
// The rule this exists to keep: **while there is no data, do not show zero.**
// A metric card that renders `0` during its first fetch is not neutral — it is
// a claim, and "0 nodes online" is a claim an operator will act on. So the
// placeholder is a shape, never a number.
//
// `aria-busy` goes on the region rather than announcing "loading" as text: a
// dashboard with six loading cards would otherwise say it six times.

withDefaults(
  defineProps<{
    /** Skeleton lines. Match the real content's shape so nothing jumps. */
    lines?: number;
    /** Announced once, for a region whose purpose is not obvious. */
    label?: string;
  }>(),
  { lines: 3 },
);
</script>

<template>
  <div class="loading" aria-busy="true" :aria-label="label">
    <span v-for="n in lines" :key="n" class="line" :data-n="n" />
  </div>
</template>

<style scoped>
.loading {
  display: grid;
  gap: 8px;
  padding: 12px 0;
}
.line {
  height: 12px;
  border-radius: var(--radius-control);
  background: var(--surface-raised);
}
/* Uneven widths, so it reads as text-shaped rather than as a table. */
.line[data-n="1"] {
  width: 62%;
}
.line[data-n="2"] {
  width: 88%;
}
.line[data-n="3"] {
  width: 74%;
}
.line[data-n="4"] {
  width: 80%;
}

/* A pulse only where motion is welcome. Under reduced-motion the shapes are
   static, which still reads as "not ready" without animating. */
@media (prefers-reduced-motion: no-preference) {
  .line {
    animation: pulse 1.4s ease-in-out infinite;
  }
  .line[data-n="2"] {
    animation-delay: 0.15s;
  }
  .line[data-n="3"] {
    animation-delay: 0.3s;
  }
}
@keyframes pulse {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.55;
  }
}
</style>
