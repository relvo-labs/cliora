<script setup lang="ts">
// A confirmation. Now a thin layer over UiDialog, which is where the focus
// containment, Escape and focus return live.
//
// Two things changed beyond the styling:
//
//   * The danger button uses `--danger-*`. Its previous colours measured
//     4.09:1 for white on `--status-error` — and this is the Terminate
//     confirmation, so it was the least legible button in the app on the most
//     consequential action.
//   * `message` is still accepted for the simple cases, but there is a slot
//     too. A Terminate confirmation has to name the session it will stop
//     (Graphite §5), and a `message: string` prop can only concatenate that
//     name into a sentence where it reads as prose.
//
// Focus starts on Cancel for a destructive confirmation: the confirm button is
// first in the DOM, and a stray Enter on a focused confirm button is exactly
// the accident a confirmation exists to prevent.

import UiButton from "../ui/UiButton.vue";
import UiDialog from "../ui/UiDialog.vue";

const props = withDefaults(
  defineProps<{
    open: boolean;
    title: string;
    message?: string;
    confirmLabel?: string;
    cancelLabel?: string;
    danger?: boolean;
    busy?: boolean;
  }>(),
  { confirmLabel: "確認", cancelLabel: "取消" },
);

const emit = defineEmits<{ confirm: []; cancel: [] }>();
</script>

<template>
  <UiDialog
    :open="open"
    :title="title"
    :busy="busy"
    :focus-cancel="danger"
    @cancel="emit('cancel')"
  >
    <p v-if="message" class="message">{{ message }}</p>
    <slot />
    <template #actions>
      <!-- data-dialog-initial: focus lands here rather than on the confirm
           button, which is what stops a stray Enter from performing a
           destructive action the moment the dialog appears. -->
      <UiButton data-dialog-initial variant="secondary" @click="emit('cancel')">
        {{ cancelLabel }}
      </UiButton>
      <UiButton
        :variant="danger ? 'danger' : 'primary'"
        :busy="busy"
        @click="emit('confirm')"
      >
        {{ props.confirmLabel }}
      </UiButton>
    </template>
  </UiDialog>
</template>

<style scoped>
.message {
  margin: 0;
}
</style>
