<script setup lang="ts">
defineProps<{
  open: boolean;
  title: string;
  message: string;
  confirmLabel?: string;
  danger?: boolean;
  busy?: boolean;
}>();
const emit = defineEmits<{ confirm: []; cancel: [] }>();
</script>

<template>
  <div v-if="open" class="backdrop" @click.self="emit('cancel')">
    <div class="dialog" role="dialog" aria-modal="true" :aria-label="title">
      <h2>{{ title }}</h2>
      <p>{{ message }}</p>
      <div class="actions">
        <button type="button" class="ghost" @click="emit('cancel')">
          Cancel
        </button>
        <button
          type="button"
          :class="danger ? 'danger' : 'primary'"
          :disabled="busy"
          @click="emit('confirm')"
        >
          {{ confirmLabel ?? "Confirm" }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.backdrop {
  position: fixed;
  inset: 0;
  z-index: 10;
  display: grid;
  place-items: center;
  background: rgb(15 20 25 / 45%);
}
.dialog {
  width: min(440px, 92vw);
  padding: 24px;
  border-radius: var(--radius-lg);
  background: var(--surface-elevated);
  box-shadow: 0 20px 60px rgb(15 20 25 / 25%);
}
.dialog h2 {
  margin: 0 0 8px;
  font-size: 18px;
}
.dialog p {
  margin: 0 0 20px;
  color: var(--text-secondary);
  font-size: 14px;
  line-height: 1.5;
}
.actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}
.actions button {
  padding: 8px 16px;
  border-radius: var(--radius-sm);
  border: 1px solid transparent;
  font-weight: 600;
}
.ghost {
  border-color: var(--border-default);
  background: var(--surface-default);
  color: var(--text-secondary);
}
.primary {
  background: var(--action-primary);
  color: var(--text-inverse);
}
.danger {
  background: var(--status-error);
  color: var(--text-inverse);
}
.actions button:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
</style>
