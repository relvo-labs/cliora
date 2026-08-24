<script setup lang="ts">
/**
 * Editing the title and description in place (PX-40, plan/26/07 §5).
 *
 * **Explicit save, with a dirty indicator — never autosave.** The two must not be mixed:
 * a field that sometimes saves itself and sometimes waits for a button is a field nobody
 * trusts, and the one that waits is the one carrying prose somebody is still writing.
 *
 * **A 409 keeps the draft, word for word.** That is the whole point of this component:
 * the alternative is a person losing a paragraph because somebody else changed the
 * card's risk. The recovery offers reload *or* compare, and `details.current` already
 * carries the server's version so neither needs a second GET.
 */
import { computed, ref, watch } from "vue";

import { ApiError } from "../../../api/client";
import type { Task } from "../../../api/dto";
import UiButton from "../../../components/ui/UiButton.vue";
import { api } from "../../../stores/auth";

const props = defineProps<{ task: Task; canEdit: boolean }>();
const emit = defineEmits<{ (event: "saved"): void }>();

const title = ref(props.task.title);
const description = ref(props.task.description ?? "");
const saving = ref(false);
const conflict = ref<Task | null>(null);
const fieldError = ref<string | null>(null);

watch(
  () => props.task.id,
  () => {
    title.value = props.task.title;
    description.value = props.task.description ?? "";
    conflict.value = null;
    fieldError.value = null;
  },
);

const dirty = computed(
  () =>
    title.value !== props.task.title ||
    description.value !== (props.task.description ?? ""),
);

async function save(): Promise<void> {
  if (!dirty.value) return;
  saving.value = true;
  fieldError.value = null;
  try {
    await api().updateTask(props.task.id, {
      version: props.task.version,
      title: title.value,
      description: description.value,
    });
    conflict.value = null;
    emit("saved");
  } catch (error) {
    if (error instanceof ApiError && error.code === "TASK_VERSION_CONFLICT") {
      // **The draft is untouched.** `details.current` is the server's card, so "compare"
      // needs no follow-up request (`services/tasks.py` puts it there for exactly this).
      conflict.value = (error.details?.current as Task) ?? null;
      return;
    }
    // Beside the field, not only in a toast: a toast is gone before somebody has finished
    // reading the sentence they were typing.
    fieldError.value = error instanceof ApiError ? error.message : "儲存失敗。";
  } finally {
    saving.value = false;
  }
}

function takeServerVersion(): void {
  if (!conflict.value) return;
  title.value = conflict.value.title;
  description.value = conflict.value.description ?? "";
  conflict.value = null;
  emit("saved");
}
</script>

<template>
  <section class="inline-edit">
    <label>
      標題
      <input
        v-model="title"
        :disabled="!canEdit"
        maxlength="200"
        data-title-input
      />
    </label>
    <label>
      描述
      <textarea
        v-model="description"
        :disabled="!canEdit"
        rows="5"
        data-description-input
      />
    </label>
    <p v-if="fieldError" class="field-error" role="alert" data-field-error>
      {{ fieldError }}
    </p>

    <div v-if="canEdit" class="actions">
      <!-- The dirty indicator is a word, not a colour. -->
      <span v-if="dirty" class="dirty" data-dirty>未儲存</span>
      <UiButton
        size="sm"
        variant="primary"
        :disabled="!dirty || saving"
        data-save
        @click="save"
      >
        儲存
      </UiButton>
    </div>

    <div v-if="conflict" class="conflict" role="alert" data-conflict>
      <p>
        這張卡剛被別人改過。<strong>你輸入的內容沒有動</strong>—— 現在的版本是
        {{ conflict.version }}。
      </p>
      <div class="conflict-actions">
        <UiButton
          size="sm"
          variant="secondary"
          data-conflict-reload
          @click="takeServerVersion"
        >
          改用伺服器的版本
        </UiButton>
        <UiButton
          size="sm"
          variant="ghost"
          data-conflict-keep
          @click="conflict = null"
        >
          保留我的草稿
        </UiButton>
      </div>
      <details data-conflict-compare>
        <summary>比對</summary>
        <dl>
          <dt>伺服器的標題</dt>
          <dd>{{ conflict.title }}</dd>
          <dt>我的標題</dt>
          <dd>{{ title }}</dd>
        </dl>
      </details>
    </div>
  </section>
</template>

<style scoped>
.inline-edit {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}
.inline-edit label {
  display: grid;
  gap: var(--space-1);
  color: var(--text-muted);
  font-size: var(--font-xs);
}
.inline-edit input,
.inline-edit textarea {
  padding: 6px 8px;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  background: var(--surface-elevated);
  color: var(--text-primary);
  font-size: var(--font-sm);
  font-family: inherit;
}
.actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
.dirty {
  color: var(--attention-warning);
  font-size: var(--font-xs);
  font-weight: 600;
}
.field-error {
  margin: 0;
  color: var(--attention-failed);
  font-size: var(--font-xs);
}
.conflict {
  border: 1px solid var(--attention-warning);
  border-radius: var(--radius-sm);
  padding: var(--space-3);
  background: color-mix(
    in srgb,
    var(--attention-warning) 8%,
    var(--surface-elevated)
  );
  font-size: var(--font-sm);
}
.conflict p {
  margin: 0 0 var(--space-2);
}
.conflict-actions {
  display: flex;
  gap: var(--space-2);
  margin-bottom: var(--space-2);
}
.conflict dl {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: var(--space-1) var(--space-3);
  margin: var(--space-2) 0 0;
  font-size: var(--font-xs);
}
.conflict dt {
  color: var(--text-muted);
}
.conflict dd {
  margin: 0;
}
</style>
