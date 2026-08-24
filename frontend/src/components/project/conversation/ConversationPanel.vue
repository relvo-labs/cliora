<script setup lang="ts">
// The card's conversation as the main work surface (`CV-10`, `CV-11`).
//
// Built to be moved: `beta.1` puts this component, unchanged, into the Task Drawer's
// main column (`plan/25` `PX-41`). So it owns the thread and nothing around it — no
// dispatch, no runs, no artifacts.
//
// Three properties are worth stating because each replaces a guess the previous panel
// made:
//
//  * **waiting state comes from the server.** `question_state` and the questions list,
//    never "is the last message a question".
//  * **raw run logs never appear here.** A log is a diagnostic with a retention period;
//    a message is product data that never expires. `GATE-CV-NO-LOG-IN-THREAD` asserts
//    this component imports no log API.
//  * **`agent_seen` says what it does not mean.** Two ticks borrowed from chat apps are
//    half wrong here, so the tooltip says the wrong half out loud.
import { computed, onMounted, ref } from "vue";

import { ACTION_TASK_APPROVE, ACTION_TASK_UPDATE } from "../../../api/dto";
import type { TaskMessage } from "../../../api/dto";
import { api, useAuthStore } from "../../../stores/auth";
import { formatInstant } from "../../../utils/time";
import BaseBadge from "../../ui/BaseBadge.vue";
import MessageComposer from "./MessageComposer.vue";
import ProposalCard from "./ProposalCard.vue";
import QuestionCard from "./QuestionCard.vue";
import {
  describe,
  newIdempotencyKey,
  useConversation,
} from "./useConversation";

const props = defineProps<{ taskId: string }>();

const auth = useAuthStore();
const canWrite = computed(() => auth.hasPermission(ACTION_TASK_UPDATE));
const canDecide = computed(() => auth.hasPermission(ACTION_TASK_APPROVE));

const thread = useConversation(() => props.taskId);
const composer = ref<InstanceType<typeof MessageComposer> | null>(null);
const busy = ref(false);
const notice = ref<string | null>(null);
const failure = ref<string | null>(null);

const openQuestion = computed(
  () => thread.questions.value.find((item) => item.state === "open") ?? null,
);

/** Only the newest proposal may be acted on; older ones say they were superseded. */
const newestProposalSeq = computed(() => {
  const proposals = thread.messages.value.filter((m) => m.kind === "proposal");
  return proposals.length
    ? proposals[proposals.length - 1].conversation_seq
    : null;
});

function questionStateFor(message: TaskMessage) {
  if (message.question_state) return message.question_state;
  const match = thread.questions.value.find(
    (item) => item.asked_message_id === message.id,
  );
  return match?.state ?? "open";
}

function answeredAtFor(message: TaskMessage): string | null {
  const match = thread.questions.value.find(
    (item) => item.asked_message_id === message.id,
  );
  return match?.answered_at ?? null;
}

function speaker(message: TaskMessage): string {
  if (message.author_kind === "agent")
    return message.author_runner_name ?? "Agent";
  if (message.author_kind === "system") return "系統";
  return message.author_name ?? "你";
}

async function postComment(text: string): Promise<void> {
  await write(() =>
    api().postTaskMessage(props.taskId, {
      body: text,
      kind: "comment",
      idempotency_key: newIdempotencyKey(),
    }),
  );
}

async function postAnswer(text: string): Promise<void> {
  const question = openQuestion.value;
  if (!question) return;
  await write(async () => {
    const result = await api().answerTaskQuestion(props.taskId, question.id, {
      body: text,
      resume: true,
      idempotency_key: newIdempotencyKey(),
    });
    // Four outcomes, four different sentences. "Refused" is the one that must not read
    // as failure: the answer *was* written, and only the next round was stopped.
    notice.value =
      result.mode === "new_turn"
        ? "已回覆，並排入新的一輪。"
        : result.mode === "live_run"
          ? "已回覆。正在執行的 Agent 會在下一次輪詢時讀到。"
          : result.mode === "refused"
            ? "已回覆，但這張卡目前無法繼續執行——原因寫在卡片上。"
            : "已回覆。";
  });
}

async function write(action: () => Promise<unknown>): Promise<void> {
  busy.value = true;
  failure.value = null;
  notice.value = null;
  try {
    await action();
    // Cleared **only** after the write landed. A failure leaves the text where the
    // person left it.
    composer.value?.clear();
    await thread.refresh();
  } catch (caught) {
    failure.value = describe(caught, "訊息沒有送出。你打的字還在。");
  } finally {
    busy.value = false;
  }
}

async function decide(text: string): Promise<void> {
  await write(() =>
    api().postTaskMessage(props.taskId, {
      body: text,
      kind: "decision",
      idempotency_key: newIdempotencyKey(),
    }),
  );
}

onMounted(thread.load);
</script>

<template>
  <section class="conversation">
    <header class="head">
      <h3>對話</h3>
      <BaseBadge
        v-if="openQuestion"
        variant="solid"
        tone="run-waiting-for-input"
      >
        ⚠ 等待你的回覆
      </BaseBadge>
    </header>

    <p v-if="thread.error.value" class="error">{{ thread.error.value }}</p>

    <button
      v-if="thread.hasOlder.value"
      class="ghost older"
      :disabled="thread.loading.value"
      @click="thread.loadOlder"
    >
      載入更早的訊息
    </button>

    <ol v-if="thread.messages.value.length" class="thread">
      <li
        v-for="message in thread.messages.value"
        :id="`message-${message.id}`"
        :key="message.id"
        :class="[message.author_kind, message.kind]"
      >
        <QuestionCard
          v-if="message.kind === 'question' && message.author_kind === 'agent'"
          :body="message.body"
          :state="questionStateFor(message)"
          :asked-at="message.created_at"
          :runner-name="message.author_runner_name"
          :answered-at="answeredAtFor(message)"
          :can-reply="canWrite"
          @reply="composer?.$el?.scrollIntoView?.({ block: 'nearest' })"
        />

        <ProposalCard
          v-else-if="message.kind === 'proposal'"
          :body="message.body"
          :runner-name="message.author_runner_name"
          :created-at="message.created_at"
          :can-decide="canDecide"
          :superseded="message.conversation_seq !== newestProposalSeq"
          @accept="decide('接受這份規格提案。')"
          @changes="(reason: string) => decide(`要求修改：${reason}`)"
        />

        <div v-else class="bubble">
          <span class="who">{{ speaker(message) }}</span>
          <BaseBadge
            v-if="message.kind === 'decision'"
            variant="outline"
            tone="neutral"
          >
            決策
          </BaseBadge>
          <p v-if="message.reply_to_message_id" class="quoted muted">
            回覆先前的訊息
          </p>
          <p class="body">{{ message.body }}</p>
          <small class="muted">
            {{ formatInstant(message.created_at) }} · #{{
              message.conversation_seq
            }}
          </small>
        </div>
      </li>
    </ol>
    <p v-else-if="!thread.loading.value" class="muted">還沒有訊息。</p>

    <p v-if="notice" class="notice">{{ notice }}</p>
    <p v-if="failure" class="error">{{ failure }}</p>

    <MessageComposer
      v-if="canWrite"
      ref="composer"
      class="composer"
      :task-id="taskId"
      :has-open-question="openQuestion !== null"
      :busy="busy"
      @comment="postComment"
      @answer="postAnswer"
    />
  </section>
</template>

<style scoped>
.conversation {
  display: grid;
  gap: var(--space-3);
}

.head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.thread {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: var(--space-3);
}

/* Three actors, told apart by placement and label as well as colour. */
.thread > li.user .bubble {
  justify-self: end;
  max-width: 80%;
}

.thread > li.agent .bubble {
  justify-self: start;
  max-width: 80%;
}

.thread > li.system .bubble {
  justify-self: center;
  font-size: var(--font-sm);
  color: var(--text-muted);
}

.bubble {
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  padding: var(--space-2) var(--space-3);
  display: grid;
  gap: var(--space-1);
}

.who {
  font-weight: 600;
}

.body {
  margin: 0;
  white-space: pre-wrap;
}

.quoted {
  margin: 0;
  font-size: var(--font-sm);
}

.muted {
  color: var(--text-muted);
}

.error {
  color: var(--status-error);
}

/* PX-46: on a phone the composer stays put while the thread scrolls under it.
 *
 * The conversation is the reason somebody opens a card on a phone — an agent is stopped
 * waiting for a sentence — and a reply box that scrolls off the bottom of a forty-message
 * thread is a reply box that does not get used. Sticky rather than fixed: fixed would
 * escape the Drawer and sit over the board behind it.
 *
 * The background is opaque and the top border is not decorative: without them the messages
 * scroll visibly *through* the composer. */
@media (max-width: 760px) {
  .composer {
    position: sticky;
    bottom: 0;
    z-index: 1;
    margin: 0 calc(-1 * var(--space-3));
    padding: var(--space-3);
    border-top: 1px solid var(--border-default);
    background: var(--surface-canvas);
  }
}
</style>
