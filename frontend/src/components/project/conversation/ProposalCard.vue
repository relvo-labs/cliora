<script setup lang="ts">
// An agent's specification proposal, and the two human actions on it (`CV-11`).
//
// Two rules, both of them refusals:
//
//  * **the buttons are not rendered without `task.approve`** — not disabled. A greyed
//    control invites somebody to hunt for the permission; an absent one says the
//    decision is not theirs to make.
//  * **only the newest proposal may be accepted.** An older one says it was superseded,
//    so nobody accepts a draft two rounds out of date.
//
// Accepting writes a `decision` message carrying the person's identity and the time —
// which is what makes "an agent's output is not an approval" visible on the card and
// not only true in the database.
import { ref } from "vue";

import { formatInstant } from "../../../utils/time";
import BaseBadge from "../../ui/BaseBadge.vue";

const props = defineProps<{
  body: string;
  runnerName: string | null;
  createdAt: string;
  canDecide: boolean;
  superseded: boolean;
}>();

const emit = defineEmits<{ accept: []; changes: [string] }>();

const expanded = ref(false);
const askingForChanges = ref(false);
const reason = ref("");

const PREVIEW_LINES = 15;

function preview(): string {
  const lines = props.body.split("\n");
  return expanded.value || lines.length <= PREVIEW_LINES
    ? props.body
    : lines.slice(0, PREVIEW_LINES).join("\n");
}

function submitChanges(): void {
  const text = reason.value.trim();
  // A required reason: "changes requested" with no reason is a round trip that
  // teaches the agent nothing.
  if (!text) return;
  emit("changes", text);
  reason.value = "";
  askingForChanges.value = false;
}
</script>

<template>
  <article class="proposal" :class="{ superseded }">
    <header>
      <span class="who">🤖 {{ runnerName ?? "Agent" }} 提出規格</span>
      <BaseBadge variant="outline" tone="neutral">提案</BaseBadge>
      <BaseBadge v-if="superseded" variant="outline" tone="neutral">
        已被較新的提案取代
      </BaseBadge>
      <small class="muted">{{ formatInstant(createdAt) }}</small>
    </header>

    <pre class="body">{{ preview() }}</pre>
    <button
      v-if="body.split('\n').length > PREVIEW_LINES"
      class="ghost"
      @click="expanded = !expanded"
    >
      {{ expanded ? "收合" : "展開全文" }}
    </button>

    <footer v-if="!superseded">
      <template v-if="canDecide">
        <template v-if="!askingForChanges">
          <button class="primary" @click="emit('accept')">接受</button>
          <button class="ghost" @click="askingForChanges = true">
            要求修改
          </button>
        </template>
        <template v-else>
          <textarea
            v-model="reason"
            rows="2"
            placeholder="要改什麼？"
            aria-label="要求修改的理由"
          ></textarea>
          <button class="primary" @click="submitChanges">送出</button>
          <button class="ghost" @click="askingForChanges = false">取消</button>
        </template>
      </template>
      <span v-else class="muted">等待有核准權限的人檢視。</span>
    </footer>
  </article>
</template>

<style scoped>
.proposal {
  border: 1px solid var(--border-default);
  border-left: 3px solid var(--stage-verify);
  border-radius: var(--radius-md);
  padding: var(--space-3);
  display: grid;
  gap: var(--space-2);
}

.proposal.superseded {
  opacity: 0.7;
}

header {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
}

.who {
  font-weight: 600;
}

.body {
  margin: 0;
  white-space: pre-wrap;
  font: inherit;
}

footer {
  display: flex;
  gap: var(--space-2);
  align-items: flex-start;
  flex-wrap: wrap;
}

textarea {
  flex: 1 1 16rem;
  font: inherit;
  padding: var(--space-2);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
}

.muted {
  color: var(--text-muted);
}
</style>
