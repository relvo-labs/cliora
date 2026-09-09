<script setup lang="ts">
// Label, control, hint, error — wired together.
//
// The label is always rendered. A placeholder is not a label: it disappears the
// moment the user types, so the field loses its name exactly when the user is
// most likely to need it, and it is not reliably announced. Required is marked
// in words as well as with an asterisk, because "*" alone is a convention the
// field cannot explain.
//
// The error lives below the field and is joined to it with `aria-describedby`,
// so a screen reader reaches it as part of the field rather than as loose text
// somewhere after it.

import { computed, useId } from "vue";

const props = defineProps<{
  label: string;
  required?: boolean;
  /** Steady guidance. Always visible; not a substitute for the label. */
  hint?: string;
  /** Present means invalid: it sets aria-invalid and colours the border. */
  error?: string;
  /** Rendered as text next to the label, not as an opacity change. */
  disabledReason?: string;
}>();

const id = useId();
const hintId = `${id}-hint`;
const errorId = `${id}-error`;

// Order matters: the error is read first, because it is what changed.
const describedBy = computed(() => {
  const parts: string[] = [];
  if (props.error) parts.push(errorId);
  if (props.hint) parts.push(hintId);
  return parts.length ? parts.join(" ") : undefined;
});
</script>

<template>
  <div class="field" :class="{ invalid: !!error }">
    <label :for="id">
      <span class="text">{{ label }}</span>
      <!-- Words, not only punctuation: "*" is a convention, "必填" is a fact. -->
      <span v-if="required" class="req">必填</span>
      <span v-if="disabledReason" class="why">{{ disabledReason }}</span>
    </label>
    <!-- The control is a slot so this works for input, select and textarea
         alike. The caller binds the ids it is given rather than this component
         reaching into a child it cannot see. -->
    <slot
      :id="id"
      :described-by="describedBy"
      :invalid="!!error"
      :required="!!required"
    />
    <p v-if="hint" :id="hintId" class="hint">{{ hint }}</p>
    <!-- role="alert" so a validation failure is announced when it appears; the
         hint is not an alert, it was always there. -->
    <p v-if="error" :id="errorId" class="error" role="alert">{{ error }}</p>
  </div>
</template>

<style scoped>
.field {
  display: grid;
  gap: 6px;
}
label {
  display: flex;
  align-items: baseline;
  gap: 8px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary);
}
.req {
  font-weight: 500;
  font-size: 11px;
  color: var(--status-error-fg);
}
.why {
  font-weight: 400;
  font-size: 11px;
  color: var(--text-secondary);
}
.hint {
  margin: 0;
  font-size: 11px;
  color: var(--text-secondary);
}
.error {
  margin: 0;
  font-size: 11px;
  color: var(--status-error-fg);
}

/* Applied to whatever the slot rendered, so every field looks the same without
   each caller restating it. */
.field :deep(input),
.field :deep(select),
.field :deep(textarea) {
  width: 100%;
  min-height: var(--density-control);
  padding: 0 10px;
  border: 1px solid var(--border-control);
  border-radius: var(--radius-control);
  background: var(--surface-default);
  color: var(--text-primary);
  font-size: 13px;
}
.field :deep(textarea) {
  padding: 8px 10px;
  min-height: calc(var(--density-control) * 2);
}
.field.invalid :deep(input),
.field.invalid :deep(select),
.field.invalid :deep(textarea) {
  border-color: var(--status-error-fg);
}
.field :deep(input:disabled),
.field :deep(select:disabled),
.field :deep(textarea:disabled) {
  color: var(--text-disabled);
  cursor: not-allowed;
}
.field :deep(input::placeholder),
.field :deep(textarea::placeholder) {
  color: var(--text-disabled);
}
</style>
