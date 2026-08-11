<script setup lang="ts">
// The card's agent surface: dispatch, runs, conversation (AR-10/AR-11).
//
// Three pieces of copy here are the product rather than decoration:
//
//  * **the two waiting states read differently.** "The agent you named is offline" and
//    "no agent is eligible" lead a person to do different things — restart a machine
//    versus check the card — and a single "waiting" would collapse them. The server
//    computes which one it is, because deciding needs the eligibility query.
//  * **a question says it is waiting for *you*.** The platform never interrupts a
//    running agent, so a reply is only seen when the agent next polls; saying so stops
//    somebody waiting for something to happen.
//  * **the refusal is shown verbatim.** Dispatch's 409s are written to name the thing
//    to fix — a missing repository, a disabled agent — and swallowing them into
//    "could not dispatch" would throw that away.
import { computed, onMounted, ref } from "vue";
import { RouterLink } from "vue-router";

import { ApiError } from "../../api/client";
import { ACTION_RUN_DISPATCH, ACTION_TASK_UPDATE } from "../../api/dto";
import type {
  AgentRunner,
  TaskArtifact,
  TaskMessage,
  TaskRun,
} from "../../api/dto";
import { api, useAuthStore } from "../../stores/auth";
import { formatInstant } from "../../utils/time";

const props = defineProps<{
  projectId: string;
  taskId: string;
  stage: string;
}>();

const auth = useAuthStore();
const canDispatch = computed(() => auth.hasPermission(ACTION_RUN_DISPATCH));
const canWrite = computed(() => auth.hasPermission(ACTION_TASK_UPDATE));

const runs = ref<TaskRun[]>([]);
const messages = ref<TaskMessage[]>([]);
const artifacts = ref<TaskArtifact[]>([]);
const agents = ref<AgentRunner[]>([]);
const chosenAgent = ref("");
const draft = ref("");
const notice = ref<string | null>(null);
const error = ref<string | null>(null);
const available = ref(true);

const activeRun = computed(() =>
  runs.value.find((run) =>
    ["queued", "claimed", "running", "waiting_for_input"].includes(run.status),
  ),
);
const canDispatchNow = computed(
  () => canDispatch.value && props.stage === "ready" && !activeRun.value,
);

async function load(): Promise<void> {
  try {
    [runs.value, messages.value, artifacts.value, agents.value] =
      await Promise.all([
        api().listTaskRuns(props.taskId),
        api().listTaskMessages(props.taskId),
        api().listTaskArtifacts(props.taskId),
        api().listAgents(),
      ]);
    available.value = true;
  } catch (caught) {
    // A 404 means one of the two flags is off. That is not an error to show — the
    // whole panel simply does not apply to this deployment.
    if (caught instanceof ApiError && caught.status === 404) {
      available.value = false;
      return;
    }
    error.value =
      caught instanceof Error ? caught.message : "Could not load agent state.";
  }
}

onMounted(() => void load());

async function dispatch(): Promise<void> {
  error.value = null;
  notice.value = null;
  try {
    const result = await api().dispatchTask(props.taskId, {
      ...(chosenAgent.value ? { assigned_runner_id: chosenAgent.value } : {}),
    });
    // The three wordings the server's `waiting_reason` exists to distinguish.
    if (result.waiting_reason === "assigned_offline") {
      const named = agents.value.find((a) => a.id === chosenAgent.value);
      notice.value = `已排入佇列，等待指定的 Agent：${named?.name ?? "（未知）"}（目前離線）。`;
    } else if (result.waiting_reason === "no_eligible_runner") {
      notice.value =
        "已排入佇列，但目前沒有符合資格的 Agent。有 Agent 上線之後就會被領走。";
    } else {
      notice.value = "已排入佇列。";
    }
    await load();
  } catch (caught) {
    // Verbatim: these refusals are written to name the thing to fix.
    error.value =
      caught instanceof Error ? caught.message : "Could not dispatch the card.";
  }
}

async function post(kind: "message" | "answer"): Promise<void> {
  if (!draft.value.trim()) return;
  error.value = null;
  try {
    await api().postTaskMessage(props.taskId, { body: draft.value, kind });
    draft.value = "";
    messages.value = await api().listTaskMessages(props.taskId);
  } catch (caught) {
    error.value =
      caught instanceof Error ? caught.message : "Could not post the message.";
  }
}

const unanswered = computed(() => {
  const last = [...messages.value]
    .reverse()
    .find((m) => m.kind === "question" || m.kind === "answer");
  return last?.kind === "question";
});

function bytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${Math.round(value / 1024)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}
</script>

<template>
  <section v-if="available" class="agent-panel">
    <h2>Agent</h2>

    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="notice" class="notice">{{ notice }}</p>

    <!-- The card says it is waiting for a person, because nothing else will: the
         platform does not interrupt a running agent. -->
    <p v-if="unanswered" class="waiting">
      Agent 提了一個問題，<strong>正在等你的回覆</strong>。回覆之後 Agent
      會在下一次拉取時看到；24 小時無人回覆這張卡會退回「阻塞」。
    </p>

    <div v-if="canDispatchNow" class="dispatch">
      <select v-model="chosenAgent">
        <option value="">任一符合資格的 Agent</option>
        <option v-for="agent in agents" :key="agent.id" :value="agent.id">
          {{ agent.name }}{{ agent.online ? "" : "（離線）" }}
        </option>
      </select>
      <button class="primary" @click="dispatch()">派給 Agent</button>
    </div>
    <p v-else-if="activeRun" class="muted">
      這張卡有一次執行進行中（{{ activeRun.status }}）。
    </p>
    <p v-else-if="canDispatch" class="muted">
      只有在「就緒」車道的卡片可以派給 Agent。
    </p>

    <div v-if="runs.length" class="runs">
      <h3>執行紀錄</h3>
      <ul>
        <li v-for="run in runs" :key="run.id">
          <RouterLink
            :to="{
              name: 'run-detail',
              params: { id: projectId, runId: run.id },
            }"
          >
            #{{ run.seq }}
          </RouterLink>
          <span class="badge">{{ run.status }}</span>
          <span class="muted">
            第 {{ run.attempt }} 次 · {{ run.runner_name ?? "尚未被領走" }} ·
            {{ formatInstant(run.queued_at) }}
          </span>
        </li>
      </ul>
    </div>

    <div class="thread">
      <h3>訊息</h3>
      <ul v-if="messages.length">
        <!-- Three sources interleaved in one thread. That is the point of it: a person
             reading a card should not have to merge two streams mentally. -->
        <li
          v-for="message in messages"
          :key="message.id"
          :class="message.author_kind"
        >
          <span class="who">
            {{
              message.author_kind === "agent"
                ? "Agent"
                : message.author_kind === "system"
                  ? "系統"
                  : (message.author_name ?? "你")
            }}
          </span>
          <span v-if="message.kind === 'question'" class="badge">提問</span>
          <p>{{ message.body }}</p>
          <small class="muted">{{ formatInstant(message.created_at) }}</small>
        </li>
      </ul>
      <p v-else class="muted">還沒有訊息。</p>

      <div v-if="canWrite" class="compose">
        <textarea
          v-model="draft"
          rows="2"
          placeholder="在卡片上留言…"
        ></textarea>
        <button class="ghost" @click="post(unanswered ? 'answer' : 'message')">
          {{ unanswered ? "回覆" : "留言" }}
        </button>
      </div>
    </div>

    <div v-if="artifacts.length" class="artifacts">
      <h3>產物</h3>
      <ul>
        <li v-for="artifact in artifacts" :key="artifact.id">
          <!-- A link, never a render. The endpoint always answers `attachment`. -->
          <span v-if="artifact.deleted_at" class="deleted">
            {{ artifact.filename }}（已刪除：{{ artifact.delete_reason }}）
          </span>
          <a v-else :href="api().artifactDownloadUrl(artifact.id)" download>
            {{ artifact.filename }}
          </a>
          <span class="muted">{{ bytes(artifact.size) }}</span>
        </li>
      </ul>
    </div>
  </section>
</template>

<style scoped>
.agent-panel {
  display: grid;
  gap: 0.75rem;
  border: 1px solid var(--border-default, #d0d0d0);
  border-radius: 6px;
  padding: 0.75rem 1rem;
}
h2,
h3 {
  margin: 0;
}
h3 {
  font-size: 0.95rem;
}
.dispatch {
  display: flex;
  gap: 0.5rem;
}
.waiting,
.notice {
  background: #fff6e5;
  padding: 0.5rem 0.75rem;
  border-radius: 4px;
  margin: 0;
  font-size: 0.9rem;
}
.error {
  color: #b3261e;
  margin: 0;
}
ul {
  list-style: none;
  padding: 0;
  margin: 0;
  display: grid;
  gap: 0.4rem;
  font-size: 0.9rem;
}
.thread li {
  border-left: 3px solid transparent;
  padding-left: 0.5rem;
}
.thread li.agent {
  border-left-color: #6b8afd;
}
.thread li.system {
  border-left-color: #cfcfcf;
}
.thread li p {
  margin: 0.15rem 0;
  white-space: pre-wrap;
}
.who {
  font-weight: 600;
}
.badge {
  font-size: 0.75rem;
  border-radius: 999px;
  padding: 0.05rem 0.45rem;
  background: #eef1f5;
  margin-left: 0.35rem;
}
.compose {
  display: flex;
  gap: 0.5rem;
  margin-top: 0.5rem;
}
.compose textarea {
  flex: 1;
}
.deleted {
  opacity: 0.55;
}
.muted {
  opacity: 0.65;
}
</style>
