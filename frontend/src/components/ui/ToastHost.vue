<script setup lang="ts">
import { useToast } from "./useToast";
const toast = useToast();
</script>

<template>
  <div class="toasts" aria-live="assertive">
    <article
      v-for="item in toast.messages.value"
      :key="item.id"
      class="toast"
      :class="`k-${item.kind}`"
      role="alert"
    >
      <div>
        <strong>{{ item.title }}</strong>
        <p v-if="item.message">{{ item.message }}</p>
      </div>
      <button
        :aria-label="`關閉：${item.title}`"
        @click="toast.dismiss(item.id)"
      >
        ×
      </button>
    </article>
  </div>
</template>

<style scoped>
.toasts {
  position: fixed;
  right: var(--space-4);
  bottom: var(--space-4);
  z-index: 1000;
  display: grid;
  width: min(380px, calc(100vw - 32px));
  gap: var(--space-2);
  pointer-events: none;
}
.toast {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  border: 1px solid var(--border-default);
  border-left: 3px solid var(--text-muted);
  border-radius: var(--radius-md);
  background: var(--surface-elevated);
  box-shadow: 0 8px 24px
    color-mix(in srgb, var(--text-primary) 14%, transparent);
  pointer-events: auto;
}
.k-success {
  border-left-color: var(--status-online);
}
.k-warning {
  border-left-color: var(--status-busy);
}
.k-error {
  border-left-color: var(--status-error);
}
.k-info {
  border-left-color: var(--border-focus);
}
p {
  margin: var(--space-1) 0 0;
  color: var(--text-secondary);
  font-size: var(--font-sm);
  line-height: 1.45;
}
button {
  padding: 0 var(--space-1);
  border: 0;
  color: var(--text-muted);
  background: transparent;
  font-size: var(--font-lg);
}
</style>
