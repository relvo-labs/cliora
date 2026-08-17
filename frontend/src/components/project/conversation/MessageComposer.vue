<script setup lang="ts">
// Two actions, and they must not be confusable (`CV-10`, ADR 0037 §4).
//
// "留言" writes a comment. "回覆並繼續" answers the open question and starts a new
// agent turn. Three things keep them apart, and each is asserted by a test:
//
//  * different accessible names, with the primary one containing 繼續;
//  * the primary action is **absent** when no question is open, not disabled — a
//    permanently greyed button reads as broken;
//  * one line of copy under the buttons saying what the second one does.
//
// The draft survives every failure. That is the one thing in this panel a person
// cannot recover from on their own.
import { computed, ref, watch } from "vue";

const props = defineProps<{
  taskId: string;
  hasOpenQuestion: boolean;
  busy: boolean;
}>();

const emit = defineEmits<{
  comment: [string];
  answer: [string];
}>();

const draft = ref("");
const storageKey = computed(() => `cliora.draft.${props.taskId}`);

// Restored per card, so switching cards does not carry a half-written reply along.
watch(
  storageKey,
  (key) => {
    draft.value = readDraft(key);
  },
  { immediate: true },
);

watch(draft, (value) => {
  if (value) localStorage.setItem(storageKey.value, value);
  else localStorage.removeItem(storageKey.value);
});

function readDraft(key: string): string {
  try {
    return localStorage.getItem(key) ?? "";
  } catch {
    // A browser with storage disabled loses the draft on reload, which is worse than
    // keeping it and better than failing to render the composer.
    return "";
  }
}

function send(kind: "comment" | "answer"): void {
  const text = draft.value.trim();
  if (!text || props.busy) return;
  // **The draft is not cleared here.** The parent clears it after a success; a failure
  // leaves the text exactly where the person left it.
  if (kind === "answer") emit("answer", text);
  else emit("comment", text);
}

/** Called by the parent once the write has actually landed. */
function clear(): void {
  draft.value = "";
}

defineExpose({ clear, draft });
</script>

<template>
  <div class="composer">
    <textarea
      v-model="draft"
      rows="3"
      :placeholder="hasOpenQuestion ? '輸入你的回覆…' : '在卡片上留言…'"
      aria-label="訊息內容"
    ></textarea>
    <div class="actions">
      <button class="ghost" :disabled="busy" @click="send('comment')">
        留言
      </button>
      <button
        v-if="hasOpenQuestion"
        class="primary"
        :disabled="busy"
        @click="send('answer')"
      >
        ↩ 回覆並繼續
      </button>
    </div>
    <p v-if="hasOpenQuestion" class="hint muted">
      「回覆並繼續」會建立一個新的 Agent 回合；「留言」只留下訊息，不會喚起
      Agent。
    </p>
  </div>
</template>

<style scoped>
.composer {
  display: grid;
  gap: var(--space-2);
}

textarea {
  width: 100%;
  font: inherit;
  padding: var(--space-2);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
}

.actions {
  display: flex;
  gap: var(--space-2);
  justify-content: flex-end;
}

.hint {
  margin: 0;
  font-size: var(--font-sm);
}

.muted {
  color: var(--text-muted);
}
</style>
