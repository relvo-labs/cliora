<script setup lang="ts">
// An agent's question, in the three states it can be in (`CV-10`).
//
// **The state comes from the server, never from "is this the last message".** That
// guess is what V2.5's panel did, and it is wrong in both directions: a question
// followed by an unrelated comment looked answered, and a card whose agent had ended
// looked as though somebody was still working on it.
//
// The action differs by state, and the `expired` case is the one worth reading: the
// card is back in `blocked`, and a continuation needs it not to be — so the offer is
// "dispatch again", not "reply and continue". That edge is recorded in
// `plan/23/09-open-measurements.md` rather than papered over here.
import { computed } from "vue";

import type { QuestionState } from "../../../api/dto";
import { formatInstant } from "../../../utils/time";
import BaseBadge from "../../ui/BaseBadge.vue";

const props = defineProps<{
  body: string;
  state: QuestionState;
  askedAt: string;
  runnerName: string | null;
  answeredAt: string | null;
  canReply: boolean;
}>();

const emit = defineEmits<{ reply: []; jump: [] }>();

const asker = computed(() => props.runnerName ?? "Agent");
const tone = computed(() =>
  props.state === "open" ? "run-waiting-for-input" : "neutral",
);
</script>

<template>
  <article class="question" :class="state">
    <header>
      <span class="who">🤖 {{ asker }}</span>
      <!-- Never colour alone: a badge carries an icon and words as well. -->
      <BaseBadge variant="outline" :tone="tone">
        {{
          state === "open"
            ? "⚠ 等待你的回覆"
            : state === "answered"
              ? "✓ 已回覆"
              : state === "expired"
                ? "⏰ 逾時未回覆"
                : "已取消"
        }}
      </BaseBadge>
      <small class="muted">{{ formatInstant(askedAt) }}</small>
    </header>

    <p class="body">{{ body }}</p>

    <footer>
      <button
        v-if="state === 'open' && canReply"
        class="primary"
        @click="emit('reply')"
      >
        回覆並繼續
      </button>
      <button
        v-else-if="state === 'answered'"
        class="ghost"
        @click="emit('jump')"
      >
        跳至回覆<span v-if="answeredAt"
          >（{{ formatInstant(answeredAt) }}）</span
        >
      </button>
      <span v-else-if="state === 'expired'" class="muted">
        這張卡已退回「阻塞」。回覆之後可以重新派工。
      </span>
    </footer>
  </article>
</template>

<style scoped>
.question {
  border: 1px solid var(--border-default);
  border-left: 3px solid var(--run-queued);
  border-radius: var(--radius-md);
  padding: var(--space-3);
  display: grid;
  gap: var(--space-2);
}

/* **Shape, not colour.** The waiting colour belongs to `BaseBadge` and the board card:
   `staticGuards.test.ts` reserves `--run-waiting` for them so that no component invents
   its own version of the level (`plan/19` D24). The badge above carries the colour and
   the words; this carries the weight. */
.question.open {
  border-left-width: 5px;
}

.question header {
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
}

.muted {
  color: var(--text-muted);
}
</style>
