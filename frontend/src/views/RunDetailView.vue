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
import PageHead from "../components/ui/PageHead.vue";
import RunBadge from "../components/ui/RunBadge.vue";
import SourceBadge from "../components/ui/SourceBadge.vue";
import UiCard from "../components/ui/UiCard.vue";
import {
  SOURCE_AGENT,
  SOURCE_MACHINE,
  SOURCE_PLATFORM,
} from "../components/ui/labels";
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
// Names only. The list route omits the field entirely, so an absent one reads as "not
// asked for" rather than as "none" — which is why this defaults to empty rather than
// rendering a dash that would claim something.
const secretNames = computed(() => run.value?.secret_names ?? []);
const timeline = computed(() => {
  if (!run.value) return [];
  return [
    { at: run.value.queued_at, label: "排入佇列" },
    { at: run.value.claimed_at, label: "Runner 認領" },
    { at: run.value.started_at, label: "開始執行" },
    { at: run.value.finished_at, label: "執行結束" },
  ].filter((item): item is { at: string; label: string } => Boolean(item.at));
});

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

    <div v-else-if="run" class="run-page">
      <PageHead>
        <template #title>Run #{{ run.seq }}</template>
        <template #subtitle>第 {{ run.attempt }} 次嘗試</template>
        <template #actions>
          <RunBadge :status="run.status" :runner-name="run.runner_name" />
          <button v-if="canCancel && isActive" class="ghost" @click="cancel()">
            取消
          </button>
        </template>
      </PageHead>

      <p v-if="actionError" class="error">{{ actionError }}</p>

      <p v-if="run.status === 'waiting_for_input'" class="waiting">
        這個 Run 正在等你的回覆。在卡片上回覆之後，Agent 會自己拉取——
        平台不會中斷它，而 24 小時無人回覆這張卡會退回「阻塞」。
      </p>

      <UiCard>
        <template #header>執行摘要</template>
        <dl class="facts">
          <div>
            <dt>來源</dt>
            <dd>
              <SourceBadge :source="SOURCE_PLATFORM" />
              <span v-if="run.source_kind === 'none'">不需要程式碼</span>
              <span v-else>{{ run.source_ref ?? "—" }}</span>
            </dd>
          </div>
          <div>
            <dt>執行的版本</dt>
            <!-- "Which version of the code did this run actually execute" — the reason
               `commit_sha` is reported at all. -->
            <dd>
              <SourceBadge :source="SOURCE_MACHINE" />
              <code v-if="run.commit_sha">{{
                run.commit_sha.slice(0, 12)
              }}</code>
              <span v-else class="muted">—</span>
            </dd>
          </div>
          <div>
            <dt>最後動靜</dt>
            <!-- The child's event stream, not the lease. The lease answers "is the runner
               alive" and Central judges it; this answers "is the child progressing". -->
            <dd>
              <SourceBadge :source="SOURCE_MACHINE" />
              {{ run.last_event_at ? formatInstant(run.last_event_at) : "—" }}
            </dd>
          </div>
          <div>
            <dt>磁碟</dt>
            <dd>{{ formatBytes(run.disk_bytes) }}</dd>
          </div>
          <!-- **Names only, and there is no version of this that could show a value.**
               Present even when empty, because "this run held no credential" is a fact
               worth being able to read off the page. -->
          <div>
            <dt>使用的機密</dt>
            <dd>
              <SourceBadge :source="SOURCE_PLATFORM" />
              <span v-if="secretNames.length">{{
                secretNames.join("、")
              }}</span>
              <span v-else class="muted">無</span>
            </dd>
          </div>
          <div v-if="run.error_code">
            <dt>錯誤</dt>
            <dd>
              <code>{{ run.error_code }}</code>
            </dd>
          </div>
        </dl>
      </UiCard>

      <p v-if="run.summary" class="summary">
        <SourceBadge :source="SOURCE_AGENT" />
        {{ run.summary }}
      </p>

      <UiCard>
        <template #header>時間軸</template>
        <ol class="timeline">
          <li v-for="item in timeline" :key="item.label">
            <time :datetime="item.at">{{ formatInstant(item.at) }}</time>
            <span class="dot" aria-hidden="true"></span>
            <strong>{{ item.label }}</strong>
            <span class="muted">—</span>
          </li>
        </ol>
      </UiCard>

      <UiCard>
        <template #header>產物</template>
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
      </UiCard>

      <UiCard>
        <template #header>Log</template>
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
      </UiCard>
    </div>
  </AppLayout>
</template>

<style scoped>
.run-page {
  display: grid;
  gap: var(--space-4);
}
.facts {
  display: grid;
  gap: var(--space-2);
  margin: 0;
  font-size: var(--font-base);
}
.facts div {
  display: flex;
  align-items: center;
  gap: var(--space-2);
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
  margin: 0;
  padding: var(--space-2) var(--space-3);
  border-left: 3px solid var(--risk-medium);
  border-radius: var(--radius-sm);
  background: var(--surface-default);
  font-size: var(--font-sm);
}
.summary {
  border-left: 3px solid var(--border-default);
  padding-left: var(--space-3);
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
  background: var(--terminal-background);
  color: var(--terminal-foreground);
  padding: var(--space-3);
  border-radius: var(--radius-sm);
  font-size: var(--font-sm);
  white-space: pre-wrap;
  word-break: break-word;
}
.muted {
  opacity: 0.65;
}
.error {
  color: var(--status-error);
}
.timeline {
  display: grid;
  gap: 0;
  margin: 0;
  padding: 0;
  list-style: none;
}
.timeline li {
  display: grid;
  grid-template-columns: minmax(150px, auto) 16px 1fr 48px;
  align-items: center;
  gap: var(--space-2);
  min-height: 34px;
  border-bottom: 1px solid var(--border-default);
  font-size: var(--font-sm);
}
.timeline time {
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: var(--font-xs);
}
.dot {
  width: 8px;
  height: 8px;
  border: 2px solid var(--source-platform);
  border-radius: 50%;
}
</style>
