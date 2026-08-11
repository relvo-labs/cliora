<script setup lang="ts">
// One run: what it did, where its code came from, and what it left behind (AR-11).
//
// Three properties of this page are decisions rather than layout:
//
//  * **the log is polled and rendered as text.** Polling, because Central aggregates
//    before writing so nothing lands faster than every couple of seconds — and a second
//    real-time channel beside the terminal relay is the one thing this phase must not
//    add. Text, because the event schema belongs to a third-party CLI: parsing it here
//    would make that schema part of this application and break on their next release.
//  * **the git summary is shown even when it is boring.** "Did this run touch a remote"
//    is what replaced blocking the agent from pushing (ADR 0031 §5), and a fact that is
//    only displayed when it looks interesting is a fact nobody trusts.
//  * **an artifact is a link, never a render.** `artifactDownloadUrl` points an anchor
//    at an endpoint that always answers `attachment`; there is no code path anywhere in
//    this app that puts artifact bytes into the DOM.
import { computed, onMounted, onUnmounted, ref } from "vue";

import { ApiError } from "../api/client";
import { ACTION_RUN_CANCEL } from "../api/dto";
import type { RunLogLine, TaskArtifact, TaskRun } from "../api/dto";
import AsyncState from "../components/common/AsyncState.vue";
import AppLayout from "../components/layout/AppLayout.vue";
import { useAsyncResource } from "../composables/useAsyncResource";
import { api, useAuthStore } from "../stores/auth";
import { formatBytes } from "../utils/bytes";
import { formatInstant } from "../utils/time";

const props = defineProps<{ id: string; runId: string }>();

const auth = useAuthStore();
const canCancel = computed(() => auth.hasPermission(ACTION_RUN_CANCEL));

const run = ref<TaskRun | null>(null);
const lines = ref<RunLogLine[]>([]);
const artifacts = ref<TaskArtifact[]>([]);
const actionError = ref<string | null>(null);
let timer: number | undefined;

const ACTIVE = new Set(["queued", "claimed", "running", "waiting_for_input"]);
const isActive = computed(() => !!run.value && ACTIVE.has(run.value.status));

const resource = useAsyncResource(async () => {
  run.value = await api().getRun(props.runId);
  artifacts.value = await api().listTaskArtifacts(run.value.task_id);
  await pollLogs();
  return run.value;
});

async function pollLogs(): Promise<void> {
  const after = lines.value.length
    ? lines.value[lines.value.length - 1].seq
    : undefined;
  const page = await api().getRunLogs(props.runId, after);
  lines.value = [...lines.value, ...page.lines];
}

async function tick(): Promise<void> {
  if (!isActive.value) return;
  try {
    run.value = await api().getRun(props.runId);
    await pollLogs();
  } catch {
    // A failed poll is not worth a banner: the next tick tries again, and the run is
    // unaffected by the browser's view of it.
  }
}

const featureUnavailable = computed(
  () =>
    resource.error.value instanceof ApiError &&
    resource.error.value.status === 404,
);

onMounted(() => {
  void resource.run();
  timer = window.setInterval(() => void tick(), 2000);
});
onUnmounted(() => {
  if (timer !== undefined) window.clearInterval(timer);
});

async function cancel(): Promise<void> {
  actionError.value = null;
  try {
    run.value = await api().cancelRun(props.runId);
  } catch (error) {
    actionError.value =
      error instanceof Error ? error.message : "Could not cancel the run.";
  }
}
</script>

<template>
  <AppLayout>
    <AsyncState
      v-if="
        resource.state.value === 'loading' || resource.state.value === 'idle'
      "
      state="loading"
    >
      Loading the run.
    </AsyncState>
    <AsyncState v-else-if="featureUnavailable" state="empty">
      這個部署沒有啟用 Agent 執行。
    </AsyncState>
    <AsyncState v-else-if="resource.state.value === 'error'" state="error">
      Could not load the run.
      <button class="link" @click="resource.run()">Retry</button>
    </AsyncState>

    <div v-else-if="run">
      <header class="head">
        <div>
          <h1>Run #{{ run.seq }}</h1>
          <p>
            {{ run.status }} · 第 {{ run.attempt }} 次嘗試
            <span v-if="run.runner_name"> · {{ run.runner_name }}</span>
          </p>
        </div>
        <button v-if="canCancel && isActive" class="ghost" @click="cancel()">
          取消
        </button>
      </header>

      <p v-if="actionError" class="error">{{ actionError }}</p>

      <p v-if="run.status === 'waiting_for_input'" class="waiting">
        這個 Run 正在等你的回覆。在卡片上回覆之後，Agent 會自己拉取——
        平台不會中斷它，而 24 小時無人回覆這張卡會退回「阻塞」。
      </p>

      <dl class="facts">
        <div>
          <dt>來源</dt>
          <dd>
            <span v-if="run.source_kind === 'none'">不需要程式碼</span>
            <span v-else>{{ run.source_ref ?? "—" }}</span>
          </dd>
        </div>
        <div>
          <dt>執行的版本</dt>
          <!-- "Which version of the code did this run actually execute" — the reason
               `commit_sha` is reported at all. -->
          <dd>
            <code v-if="run.commit_sha">{{ run.commit_sha.slice(0, 12) }}</code>
            <span v-else class="muted">—</span>
          </dd>
        </div>
        <div>
          <dt>最後動靜</dt>
          <!-- The child's event stream, not the lease. The lease answers "is the runner
               alive" and Central judges it; this answers "is the child progressing". -->
          <dd>
            {{ run.last_event_at ? formatInstant(run.last_event_at) : "—" }}
          </dd>
        </div>
        <div>
          <dt>磁碟</dt>
          <dd>{{ formatBytes(run.disk_bytes) }}</dd>
        </div>
        <div v-if="run.error_code">
          <dt>錯誤</dt>
          <dd>
            <code>{{ run.error_code }}</code>
          </dd>
        </div>
      </dl>

      <p v-if="run.summary" class="summary">{{ run.summary }}</p>

      <section>
        <h2>產物</h2>
        <p v-if="!artifacts.length" class="muted">
          這次執行還沒有附加任何產物。
        </p>
        <ul v-else class="artifacts">
          <li v-for="artifact in artifacts" :key="artifact.id">
            <template v-if="artifact.deleted_at">
              <!-- Deleted artifacts stay as a grey line rather than disappearing —
                   the same rule the activity timeline follows, and the reason a reason
                   is required in the first place. -->
              <span class="deleted"
                >{{ artifact.filename }}（已刪除：{{
                  artifact.delete_reason
                }}）</span
              >
            </template>
            <template v-else>
              <a :href="api().artifactDownloadUrl(artifact.id)" download>
                {{ artifact.filename }}
              </a>
              <span class="muted">
                {{ formatBytes(artifact.size) }} · {{ artifact.content_type }}
              </span>
            </template>
          </li>
        </ul>
      </section>

      <section>
        <h2>Log</h2>
        <p v-if="run.log_truncated_bytes > 0" class="truncated">
          這份 log 從中間截斷了，省略
          {{ formatBytes(run.log_truncated_bytes) }}。 開頭與結尾都保留著。
        </p>
        <!-- Rendered as text. Not parsed, not syntax-highlighted per event type: the
             schema is a third-party CLI's and changes with its version. -->
        <pre v-if="lines.length" class="log">{{
          lines.map((line) => line.data).join("\n")
        }}</pre>
        <p v-else class="muted">還沒有輸出。</p>
      </section>
    </div>
  </AppLayout>
</template>

<style scoped>
.head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
}
.facts {
  display: grid;
  gap: 0.25rem;
  font-size: 0.9rem;
}
.facts div {
  display: flex;
  gap: 0.5rem;
}
.facts dt {
  min-width: 8rem;
  opacity: 0.7;
}
.facts dd {
  margin: 0;
}
.waiting,
.truncated {
  background: #fff6e5;
  padding: 0.5rem 0.75rem;
  border-radius: 4px;
  font-size: 0.9rem;
}
.summary {
  border-left: 3px solid var(--color-border, #d0d0d0);
  padding-left: 0.75rem;
}
.artifacts {
  list-style: none;
  padding: 0;
  display: grid;
  gap: 0.25rem;
}
.deleted {
  opacity: 0.55;
}
.log {
  max-height: 28rem;
  overflow: auto;
  background: #101010;
  color: #e8e8e8;
  padding: 0.75rem;
  border-radius: 4px;
  font-size: 0.8rem;
  white-space: pre-wrap;
  word-break: break-word;
}
.muted {
  opacity: 0.65;
}
.error {
  color: #b3261e;
}
</style>
