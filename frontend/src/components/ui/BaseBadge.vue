<script setup lang="ts">
withDefaults(
  defineProps<{
    variant: "solid" | "outline" | "quiet";
    tone?: string;
    pulse?: boolean;
  }>(),
  { tone: "neutral", pulse: false },
);
</script>

<template>
  <span class="badge" :class="[`v-${variant}`, `t-${tone}`]">
    <span v-if="pulse" class="pulse" aria-hidden="true"></span>
    <span class="label"><slot /></span>
  </span>
</template>

<style scoped>
.badge {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  max-width: 100%;
  min-height: 20px;
  padding: 1px 7px;
  border: 1px solid transparent;
  border-radius: 999px;
  font-size: var(--font-xs);
  font-weight: 600;
  line-height: 1.35;
  white-space: nowrap;
  color: var(--text-muted);
}
.v-solid {
  background: currentColor;
}
.v-solid .label {
  color: var(--text-inverse);
}
.v-outline {
  border-color: currentColor;
  background: transparent;
}
.v-quiet {
  color: var(--text-muted);
  background: var(--surface-canvas);
}
.pulse {
  width: 6px;
  height: 6px;
  flex: none;
  border-radius: 50%;
  background: currentColor;
  animation: pulse 1.35s ease-in-out infinite;
}
.v-solid .pulse {
  background: var(--text-inverse);
}
.t-stage-backlog {
  color: var(--stage-backlog);
}
.t-stage-blocked {
  color: var(--stage-blocked);
}
.t-stage-ready {
  color: var(--stage-ready);
}
.t-stage-implementing {
  color: var(--stage-implementing);
}
.t-stage-verify {
  color: var(--stage-verify);
}
.t-stage-done {
  color: var(--stage-done);
}
.t-run-queued,
.t-run-claimed {
  color: var(--run-queued);
}
.t-run-running {
  color: var(--run-running);
}
.t-run-waiting-for-input {
  color: var(--run-waiting);
}
.t-run-succeeded {
  color: var(--run-succeeded);
}
.t-run-failed {
  color: var(--run-failed);
}
.t-run-lost {
  color: var(--run-lost);
}
.t-run-cancelled {
  color: var(--status-offline);
}
.t-risk-low {
  color: var(--risk-low);
}
.t-risk-medium {
  color: var(--risk-medium);
}
.t-risk-high {
  color: var(--risk-high);
}
.t-source-machine {
  color: var(--source-machine);
}
.t-source-platform {
  color: var(--source-platform);
}
.t-source-agent {
  color: var(--source-agent);
}
.t-delivery-artifact {
  color: var(--source-platform);
}
.t-delivery-branch {
  color: var(--stage-ready);
}
.t-delivery-pull-request,
.t-delivery-existing-pr {
  color: var(--stage-implementing);
}
.t-status-online {
  color: var(--status-online);
}
.t-status-busy {
  color: var(--status-busy);
}
.t-status-offline {
  color: var(--status-offline);
}
@keyframes pulse {
  50% {
    opacity: 0.28;
    transform: scale(0.72);
  }
}
@media (prefers-reduced-motion: reduce) {
  .pulse {
    animation: none;
  }
}
</style>
