<script setup lang="ts">
/**
 * The Drawer with the card in it (PX-39…PX-46, PX-62).
 *
 * **Conversation is second, and the execution settings are last and collapsed.** That is
 * the whole difference from `TaskDetailView`, and it comes from what people actually do:
 * *scan the board → open the detail → answer the agent → carry on scanning*. The Drawer
 * exists so the middle two steps do not interrupt the outer two, and putting the
 * conversation below four read-only panels would reintroduce the interruption in scroll
 * form.
 *
 * The panels below the conversation are the existing components, unchanged: `PX-42` and
 * `PX-43` were about *where* run, dependency, artifact and verification information
 * appears, not about rewriting it. `RelatedKnowledgePanel` is `alpha.3`'s, re-hosted
 * (PX-62) — three props, all ids.
 *
 * **403 does not leak the title** (plan/26/07 §4). The header falls back to the card
 * reference the board already showed, and the body says only that the card cannot be
 * opened. **404 leaves the board alone**: a deleted card closes nothing, so the reader
 * keeps their filter, their scroll and their place.
 */
import { computed, ref, watch } from "vue";

import { ApiError } from "../../api/client";
import {
  ACTION_SESSION_CREATE,
  ACTION_TASK_APPROVE,
  ACTION_TASK_UPDATE,
  type ProcessDefinition,
  type Task,
  type TaskAttention,
  type WorkItemCard,
} from "../../api/dto";
import TaskAgentPanel from "../../components/project/TaskAgentPanel.vue";
import TaskCompletion from "../../components/project/TaskCompletion.vue";
import TaskDetail from "../../components/project/TaskDetail.vue";
import ConversationPanel from "../../components/project/conversation/ConversationPanel.vue";
import RelatedKnowledgePanel from "../knowledge/components/RelatedKnowledgePanel.vue";
import AttentionBadge from "../work/components/AttentionBadge.vue";
import TaskDetailDrawer from "./TaskDetailDrawer.vue";
import InlineTitleEdit from "./components/InlineTitleEdit.vue";
import TaskPropertySidebar from "./components/TaskPropertySidebar.vue";
import { api, useAuthStore } from "../../stores/auth";

const props = defineProps<{
  projectId: string;
  taskId: string | null;
  /** What the board already knows, so the header is filled before the fetch answers and
   *  stays filled when the fetch is refused. */
  cardRef?: string | null;
  /** The read model's card, when the caller has one. Lets the sidebar decide whether an
   *  execution setting is the reason this card is stuck without a second request. */
  card?: WorkItemCard | null;
  /** A readiness key to scroll to and focus once the card has loaded (PX-30).
   *
   *  Set by the Ready-transition dialog's "fill it in", which is the only caller: a list
   *  of missing items somebody has to translate into "so where do I type that" is a list
   *  that gets pressed past. */
  focusReadiness?: string | null;
}>();
const emit = defineEmits<{
  (event: "close"): void;
  (event: "changed"): void;
  /** Fired once the focus target has been used, so the caller can drop it from the URL —
   *  otherwise a reload yanks focus away from whatever the reader is doing. */
  (event: "focused"): void;
}>();

const auth = useAuthStore();
const task = ref<Task | null>(null);
const process = ref<ProcessDefinition | null>(null);
/** This card's full attention signal set. See `TaskPropertySidebar` for why the *set* and
 *  not the primary: a card can be several things at once, and the one that wins the badge
 *  is not necessarily the one somebody needs to act on. */
const attention = ref<TaskAttention | null>(null);
const state = ref<
  "idle" | "loading" | "ready" | "forbidden" | "missing" | "error"
>("idle");
const requestId = ref<string | undefined>(undefined);

async function load(): Promise<void> {
  const id = props.taskId;
  if (id === null) {
    state.value = "idle";
    task.value = null;
    return;
  }
  state.value = "loading";
  task.value = null;
  attention.value = null;
  requestId.value = undefined;
  try {
    const [nextTask, nextProcess, nextAttention] = await Promise.all([
      api().getTask(id),
      api().getProcess(props.projectId),
      // **Not allowed to fail the Drawer.** A card's properties and its conversation are
      // the reason somebody opened this; the signal set only decides whether one section
      // starts expanded. Null falls back to the board's primary.
      api()
        .getTaskAttention(id)
        .catch(() => null),
    ]);
    // The reader may have closed the Drawer or opened another card while this was in
    // flight. Without the guard the older response wins and shows the wrong card.
    if (props.taskId !== id) return;
    task.value = nextTask;
    process.value = nextProcess;
    attention.value = nextAttention;
    state.value = "ready";
  } catch (error) {
    if (props.taskId !== id) return;
    requestId.value = error instanceof ApiError ? error.requestId : undefined;
    const status = error instanceof ApiError ? error.status : 0;
    state.value =
      status === 403 ? "forbidden" : status === 404 ? "missing" : "error";
  }
}

watch(() => props.taskId, load, { immediate: true });

async function reload(): Promise<void> {
  await load();
  emit("changed");
}

/** Whether the conversation should take the focus on open (PX-41).
 *
 *  When an agent is stopped waiting for a sentence, the sentence is the only thing on this
 *  screen that matters — and **a reader must not have to expand a run log to find out what
 *  was asked**. So the conversation scrolls itself into view and takes focus.
 */
const conversationFirst = computed(
  () =>
    // From the read model's attention, not re-derived here. `TaskDTO` carries no open
    // question count, and adding one would be a second answer to a question
    // `derive_attention` already answers (ADR 0040 §3).
    props.card?.primary_attention === "waiting_for_your_input" ||
    (props.card?.open_question_count ?? 0) > 0,
);
const conversationAnchor = ref<HTMLElement | null>(null);

watch([conversationFirst, state], async ([wanted, current]) => {
  if (!wanted || current !== "ready") return;
  await new Promise((resolve) => window.setTimeout(resolve, 0));
  conversationAnchor.value?.scrollIntoView({
    block: "start",
    behavior: "auto",
  });
});

// --- "fill it in" (PX-30) ---------------------------------------------------------
//
// The readiness checklist lives inside `TaskDetail`, several components down, and it is
// rendered by `v-for` — so the target is found by attribute rather than by a ref chain
// threaded through three components for one interaction. `scrollIntoView` **then** focus:
// focusing alone scrolls in most browsers but centres nothing, and the checklist is the
// last section on a long panel.
const panelRoot = ref<HTMLElement | null>(null);

watch([() => props.focusReadiness, state], async ([key, current]) => {
  if (!key || current !== "ready") return;
  // Two frames: one for `TaskDetail` to render the list, one for the layout to settle.
  await new Promise((resolve) => window.setTimeout(resolve, 0));
  await new Promise((resolve) => window.setTimeout(resolve, 0));
  const row = panelRoot.value?.querySelector<HTMLElement>(
    `[data-readiness="${CSS.escape(key)}"]`,
  );
  if (!row) {
    // The item exists on the server and not on screen — a project switched it off, or the
    // reader cannot edit. Say nothing and clear the target: silently doing nothing is
    // better than focusing something else, and a stuck `?focus=` would fire again on
    // every reload.
    emit("focused");
    return;
  }
  row.scrollIntoView({ block: "center", behavior: "auto" });
  const control = row.querySelector<HTMLElement>("input, button, textarea");
  (control ?? row).focus();
  emit("focused");
});
</script>

<template>
  <TaskDetailDrawer
    :project-id="projectId"
    :task-id="taskId"
    :card-ref="task?.card_ref ?? cardRef ?? null"
    :title="task?.title ?? null"
    @close="emit('close')"
  >
    <template v-if="card?.primary_attention" #badge>
      <AttentionBadge
        density="compact"
        :primary="card.primary_attention"
        :count="card.attention_count ?? 1"
      />
    </template>
    <p v-if="state === 'loading'" class="drawer-state" role="status">
      載入任務…
    </p>
    <p
      v-else-if="state === 'forbidden'"
      class="drawer-state"
      role="alert"
      data-drawer-forbidden
    >
      你沒有權限查看這張卡片。
    </p>
    <p
      v-else-if="state === 'missing'"
      class="drawer-state"
      role="alert"
      data-drawer-missing
    >
      這張卡片已不存在，可能已被刪除。
    </p>
    <p v-else-if="state === 'error'" class="drawer-state" role="alert">
      無法載入任務。<span v-if="requestId">Request ID: {{ requestId }}</span>
    </p>

    <div v-else-if="task && process" ref="panelRoot" class="layout">
      <div class="main">
        <!-- 1. Description, editable in place. -->
        <InlineTitleEdit
          :task="task"
          :can-edit="auth.hasPermission(ACTION_TASK_UPDATE)"
          @saved="reload"
        />

        <!-- 2. The conversation. **Second, not last** — this is the reordering the whole
             ticket is about. -->
        <section ref="conversationAnchor" data-conversation-anchor>
          <p
            v-if="conversationFirst"
            class="waiting-note"
            role="status"
            data-waiting-note
          >
            有一個 Agent 停在這裡等一句話。回覆並繼續會建立一個新的 Agent turn。
          </p>
          <ConversationPanel :task-id="task.id" />
        </section>

        <!-- 3. Run, dependencies and activity (PX-42): the existing panel, re-hosted.
             Raw logs open through a deep link and never mix into the thread. -->
        <TaskAgentPanel
          :project-id="projectId"
          :task-id="task.id"
          :stage="task.stage"
        />

        <!-- 4. Artifacts, delivery, verification and gates (PX-43). Every human decision
             here carries its actor and its time, which is what makes "an agent's output is
             not an approval" visible rather than merely true. -->
        <TaskCompletion :task="task" />

        <!-- 5. Related knowledge (PX-62). `alpha.3`'s component, three props, all ids. -->
        <RelatedKnowledgePanel
          :project-id="projectId"
          :task-id="task.id"
          :task-title="task.title"
          :can-manage="auth.hasPermission('project.manage')"
        />

        <!-- 6. Readiness, gates and the rest of the card's own detail. -->
        <TaskDetail
          :task="task"
          :process="process"
          :client="api()"
          :can-approve="auth.hasPermission(ACTION_TASK_APPROVE)"
          :can-edit="auth.hasPermission(ACTION_TASK_UPDATE)"
          :can-start-session="auth.hasPermission(ACTION_SESSION_CREATE)"
          @changed="reload"
        />
      </div>

      <TaskPropertySidebar
        :task="task"
        :card="card ?? null"
        :attention="attention"
      />
    </div>
  </TaskDetailDrawer>
</template>

<style scoped>
.drawer-state {
  margin: 0;
  padding: var(--space-5) 0;
  color: var(--text-secondary);
  font-size: var(--font-sm);
  text-align: center;
}
.layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 260px;
  gap: var(--space-4);
  align-items: start;
}
.main {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  min-width: 0;
}
.waiting-note {
  margin: 0 0 var(--space-2);
  border-left: 3px solid var(--attention-human);
  padding-left: var(--space-3);
  color: var(--text-primary);
  font-size: var(--font-sm);
  font-weight: 600;
}
/* Mobile is one column with the sidebar underneath (PX-46), and the composer stays where
 * it is because the conversation is the reason somebody opened this on a phone. */
@media (max-width: 760px) {
  .layout {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
