<script setup lang="ts">
/**
 * One card, in two columns (TK-09, `research/02/09` §4.5).
 *
 * Three things here are decisions rather than layout:
 *
 *  - **A gate shows who approved it and when.** That cell always holds a person, and
 *    showing the person is what makes "an agent's output is not an approval" visible
 *    rather than merely true.
 *  - **A derived-disabled gate says why it is disabled** and offers the way out. A gate
 *    that quietly does not exist is worse than one that explains itself (D31).
 *  - **The execution block is labelled inert.** A card saying `pull_request` produces
 *    no pull request until V2.3, and this is the one state in the phase we know
 *    misleads (ADR 0028 sec 9).
 */
import { computed, ref } from "vue";

import { ApiError, type ApiClient } from "../../api/client";
import type {
  ActivityEvent,
  ProcessDefinition,
  SessionSummary,
  Task,
} from "../../api/dto";
import { formatInstant } from "../../utils/time";

const props = defineProps<{
  task: Task;
  process: ProcessDefinition;
  client: ApiClient;
  canApprove: boolean;
  canStartSession: boolean;
  sessions?: SessionSummary[];
  activity?: ActivityEvent[];
  actorNames?: Record<string, string>;
}>();
const emit = defineEmits<{
  (event: "changed"): void;
  (event: "start-session", task: Task): void;
}>();

const error = ref<string | null>(null);

const readiness = computed(() =>
  props.process.readiness.map((item) => ({
    ...item,
    met: Boolean(props.task.readiness?.[item.key]),
  })),
);

const gates = computed(() =>
  props.process.gates.map((gate) => ({
    ...gate,
    approval: props.task.gates?.[gate.key] ?? null,
  })),
);

async function toggleGate(key: string, approved: boolean): Promise<void> {
  if (!approved && !window.confirm("確定要取消這項人工核准嗎？")) return;
  error.value = null;
  try {
    await props.client.decideGate(props.task.id, key, approved);
    emit("changed");
  } catch (caught) {
    error.value =
      caught instanceof ApiError && caught.code === "GATE_DISABLED"
        ? "這個關卡在這個部署裡不可用（未啟用 tunnel 整合）。"
        : caught instanceof ApiError
          ? caught.message
          : "操作失敗。";
  }
}
</script>

<template>
  <article class="task-detail">
    <header>
      <span class="ref">{{ task.card_ref }}</span>
      <h2>{{ task.title }}</h2>
      <span class="stage" :data-stage="task.stage">{{ task.stage }}</span>
    </header>

    <p v-if="error" class="notice error" role="alert">{{ error }}</p>

    <div class="columns">
      <section>
        <h3>任務定義</h3>
        <dl>
          <template
            v-for="pair in [
              ['目標', task.objective],
              ['範圍', task.scope],
              ['非目標', task.non_goals],
            ]"
            :key="pair[0]"
          >
            <template v-if="pair[1]">
              <dt>{{ pair[0] }}</dt>
              <dd>{{ pair[1] }}</dd>
            </template>
          </template>
        </dl>

        <h4>驗收標準</h4>
        <ul class="criteria">
          <li v-for="(item, index) in task.acceptance_criteria" :key="index">
            <span class="result">{{ item.result ?? "未驗" }}</span>
            {{ item.text }}
          </li>
          <li v-if="task.acceptance_criteria.length === 0" class="empty">
            尚未填寫
          </li>
        </ul>

        <h4>就緒條件</h4>
        <ul class="readiness">
          <li v-for="item in readiness" :key="item.key" :data-met="item.met">
            <span aria-hidden="true">{{ item.met ? "✓" : "○" }}</span>
            {{ item.label }}
            <small>{{ item.hint }}</small>
          </li>
        </ul>
        <p class="hint">
          就緒條件只提醒，不阻擋——唯一會被拒絕的是未完成的前置任務。
        </p>

        <h4>審查關卡</h4>
        <ul class="gates">
          <li v-for="gate in gates" :key="gate.key" :data-gate="gate.key">
            <template v-if="!gate.enabled">
              <span class="label">{{ gate.label }}</span>
              <span class="disabled" data-gate-disabled>
                停用 —— {{ gate.disabled_reason }}
              </span>
              <RouterLink class="link" to="/settings/integrations"
                >前往設定</RouterLink
              >
            </template>
            <template v-else>
              <span class="label">{{ gate.label }}</span>
              <span v-if="gate.approval" class="approved" data-gate-approved>
                已核准 ·
                {{
                  actorNames?.[gate.approval.approved_by] ??
                  gate.approval.approved_by
                }}
                · {{ formatInstant(gate.approval.approved_at) }}
              </span>
              <button
                v-if="canApprove"
                class="ghost"
                :data-gate-toggle="gate.key"
                @click="toggleGate(gate.key, !gate.approval)"
              >
                {{ gate.approval ? "取消核准" : "核准" }}
              </button>
            </template>
          </li>
        </ul>

        <h4>相依</h4>
        <ul class="deps">
          <li
            v-for="dep in task.depends_on"
            :key="dep.id"
            :data-stage="dep.stage"
          >
            {{ dep.card_ref }} {{ dep.title }}
          </li>
          <li v-if="task.depends_on.length === 0" class="empty">無</li>
        </ul>
        <p v-if="task.blocking_refs.length" class="notice" data-blocking>
          {{ task.blocking_refs.join("、") }}
          尚未完成，這張卡不能進入「就緒」之後的車道。
        </p>

        <p v-if="task.requirement_id" class="provenance" data-provenance>
          來源需求：{{ task.requirement_id }}<br />提案：{{
            task.proposal_id ?? "—"
          }}
        </p>
      </section>

      <section>
        <h3>執行</h3>
        <p class="hint">本階段由人執行。</p>
        <button
          v-if="canStartSession"
          class="primary"
          data-start-session
          @click="emit('start-session', task)"
        >
          開始工作
        </button>

        <h4>執行設定<small>（V2.3 起生效）</small></h4>
        <dl class="execution">
          <dt>來源</dt>
          <dd>{{ task.source }}</dd>
          <dt>交付</dt>
          <dd>{{ task.delivery }}</dd>
          <dt>base branch</dt>
          <dd>{{ task.base_branch ?? "—" }}</dd>
        </dl>
        <p class="hint">這是意圖宣告：本階段沒有任何執行者會依它行動。</p>

        <h4>Session 歷史</h4>
        <ul class="sessions">
          <li v-for="item in sessions ?? []" :key="item.id">
            <RouterLink
              :to="{ name: 'session-workspace', params: { id: item.id } }"
            >
              {{ item.name }}
            </RouterLink>
            <span :data-stage="item.status">{{ item.status }}</span>
            <small>{{ formatInstant(item.created_at) }}</small>
          </li>
          <li v-if="(sessions ?? []).length === 0" class="empty">
            尚無 Session
          </li>
        </ul>

        <h4>活動</h4>
        <ul class="activity">
          <li v-for="item in activity ?? []" :key="item.id">
            <span class="actor-kind" :data-actor-kind="item.actor_kind">
              {{
                item.actor_kind === "agent"
                  ? "Agent"
                  : item.actor_kind === "system"
                    ? "系統"
                    : "人員"
              }}
            </span>
            {{ item.kind }}
            <small
              >{{ item.actor_name ?? "—" }} ·
              {{ formatInstant(item.occurred_at) }}</small
            >
          </li>
          <li v-if="(activity ?? []).length === 0" class="empty">尚無活動</li>
        </ul>
      </section>
    </div>
  </article>
</template>

<style scoped>
header {
  display: flex;
  align-items: baseline;
  gap: var(--space-2);
}
h2 {
  margin: 0;
  font-size: var(--font-size-lg);
}
.ref {
  font-family: var(--font-mono);
  color: var(--color-text-muted);
}
.columns {
  display: grid;
  grid-template-columns: 1fr 300px;
  gap: var(--space-4);
  margin-top: var(--space-3);
}
h3 {
  font-size: var(--font-size-sm);
  margin-top: 0;
}
h4 {
  font-size: var(--font-size-sm);
  margin: var(--space-3) 0 var(--space-1);
}
h4 small {
  color: var(--color-text-muted);
  font-weight: 400;
}
ul {
  list-style: none;
  margin: 0;
  padding: 0;
}
.readiness li[data-met="false"] {
  color: var(--color-text-muted);
}
.readiness small {
  display: block;
  color: var(--color-text-muted);
  margin-left: var(--space-3);
}
.gates li {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: 2px 0;
}
.gates .label {
  min-width: 8rem;
}
.disabled {
  color: var(--color-text-muted);
  font-size: var(--font-size-xs);
}
.approved {
  color: var(--color-success);
  font-size: var(--font-size-xs);
}
.hint,
.empty,
.provenance {
  color: var(--color-text-muted);
  font-size: var(--font-size-xs);
}
.criteria .result {
  font-family: var(--font-mono);
  font-size: var(--font-size-xs);
  margin-right: var(--space-1);
}
.execution dt {
  color: var(--color-text-muted);
  font-size: var(--font-size-xs);
}
</style>
