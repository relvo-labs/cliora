<script setup lang="ts">
// Where toasts appear. Mounted once, in the shell.
//
// `role="status"` with `aria-live="polite"` rather than `alert`: a
// confirmation should wait for a pause in whatever the screen reader is
// currently saying, not interrupt it. Nothing here can be an error — see
// useToast for why the type has no error member.

import { X } from "lucide-vue-next";

import { useToast } from "../../composables/useToast";
import UiIconButton from "./UiIconButton.vue";

const { toasts, dismiss } = useToast();
</script>

<template>
  <!-- The live region exists even when empty, so a toast added later is
       announced. A region created at the same moment as its content is often
       missed entirely. -->
  <div class="host" role="status" aria-live="polite">
    <div
      v-for="toast in toasts"
      :key="toast.id"
      class="toast"
      :data-kind="toast.kind"
    >
      <span class="message">{{ toast.message }}</span>
      <!-- Dismissable by hand as well as by timer: someone who reads slowly
           should not have to wait for it to come back. -->
      <UiIconButton label="關閉通知" @click="dismiss(toast.id)">
        <X />
      </UiIconButton>
    </div>
  </div>
</template>

<style scoped>
.host {
  position: fixed;
  bottom: 20px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 20;
  display: grid;
  gap: 8px;
  /* No pointer events on the container, so an empty host cannot swallow clicks
     meant for the page underneath it. */
  pointer-events: none;
}
.toast {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 8px 8px 14px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-control);
  /* One of the few places a shadow is allowed: this genuinely floats above the
     content (style.md §7, Graphite §5). */
  background: var(--surface-raised);
  box-shadow: var(--shadow-overlay);
  color: var(--text-primary);
  font-size: 13px;
  pointer-events: auto;
}
.toast[data-kind="success"] {
  border-color: var(--status-success-border);
}
.toast[data-kind="info"] {
  border-color: var(--status-info-border);
}
.message {
  overflow-wrap: anywhere;
}

@media (prefers-reduced-motion: no-preference) {
  .toast {
    animation: rise var(--motion-base) ease;
  }
}
@keyframes rise {
  from {
    opacity: 0;
    transform: translateY(8px);
  }
}
</style>
