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
 *  - **The execution block is no longer inert.** `source`, `delivery: branch`, the
 *    tags and the declared secrets are all acted on from V2.3; what is still refused is
 *    refused *at dispatch*, naming the version. A stale "nobody will act on this" is
 *    worse than no note at all.
 *  - **A mistyped tag is warned about where it is typed.** It is the commonest failure
 *    of tag dispatch and its symptom is a card that waits forever, so catching it
 *    against what online runners report costs one request and saves an investigation.
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
import BaseBadge from "../ui/BaseBadge.vue";
import DeliveryBadge from "../ui/DeliveryBadge.vue";
import RiskBadge from "../ui/RiskBadge.vue";
import SourceBadge from "../ui/SourceBadge.vue";
import StageBadge from "../ui/StageBadge.vue";
import UiCard from "../ui/UiCard.vue";

const props = defineProps<{
  task: Task;
  process: ProcessDefinition;
  client: ApiClient;
  canApprove: boolean;
  /** `task.update`, **not** `task.approve`. Editing a card's execution settings is an
   *  edit; approving a gate is a different power and the two must not share a flag —
   *  that separation is what makes "an agent's output is not an approval" hold. */
  canEdit: boolean;
  canStartSession: boolean;
  sessions?: SessionSummary[];
  activity?: ActivityEvent[];
  actorNames?: Record<string, string>;
  /** Tags the online runners actually report. Used only to warn — a runner that comes
   *  online tomorrow is a legitimate reason for a tag nothing has yet. */
  availableTags?: string[];
}>();
const emit = defineEmits<{
  (event: "changed"): void;
  (event: "start-session", task: Task): void;
}>();

const error = ref<string | null>(null);

const requiredLabels = computed(() => props.task.required_labels ?? []);
const requiredSecrets = computed(() => props.task.required_secrets ?? []);
// Only warn about a tag nothing online has. With no runner list at all (the page loaded
// before the agents did, or the reader cannot see them) this is empty and the warning
// stays quiet — a false "nobody has this" is worse than no warning.
const unmatchedTags = computed(() => {
  const available = new Set(props.availableTags ?? []);
  if (!available.size) return [];
  return requiredLabels.value.filter((tag) => !available.has(tag));
});

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

const evidence = computed<Record<string, unknown>[]>(() => {
  const value = props.task.links?.evidence;
  return Array.isArray(value)
    ? value.filter((item): item is Record<string, unknown> =>
        Boolean(item && typeof item === "object"),
      )
    : [];
});

function sourceOf(item: Record<string, unknown>): string | null {
  return typeof item.source === "string" ? item.source : null;
}

function isFailed(item: Record<string, unknown>): boolean {
  return [false, "failed", "fail", "error"].includes(
    item.result as false | string,
  );
}

// The execution settings, editable rather than merely displayed.
//
// **They were display-only until V2.3, and that made the whole dispatch path
// unreachable from the console**: a new card defaults to `delivery: pull_request`,
// which is refused at dispatch until V2.4, and nothing on this page could change it.
// A field the platform acts on and the console cannot set is worse than one it ignores.
async function setExecution(changes: Record<string, unknown>): Promise<void> {
  error.value = null;
  try {
    await props.client.updateTask(props.task.id, {
      ...changes,
      // Optimistic lock: two tabs editing one card is the case this exists for.
      version: props.task.version,
    });
    emit("changed");
  } catch (caught) {
    error.value =
      caught instanceof ApiError && caught.status === 409
        ? "這張卡剛被別人改過，請重新載入。"
        : caught instanceof ApiError
          ? caught.message
          : "操作失敗。";
  }
}

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
      <StageBadge :stage="task.stage" />
      <RiskBadge :risk="task.risk" />
    </header>

    <p v-if="error" class="notice error" role="alert">{{ error }}</p>

    <div class="columns">
      <UiCard>
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
          <template
            v-for="(item, index) in task.acceptance_criteria"
            :key="index"
          >
            <li v-if="isFailed(item)" class="failed" data-failed-check>
              <div>
                <span class="result">{{ item.result ?? "失敗" }}</span>
                {{ item.text }}
              </div>
              <SourceBadge
                v-if="sourceOf(item)"
                :source="sourceOf(item) as string"
              />
              <pre v-if="item.summary || item.command">{{
                item.summary ?? item.command
              }}</pre>
            </li>
            <li v-else>
              <details>
                <summary>
                  <span class="result">{{ item.result ?? "未驗" }}</span>
                  {{ item.text }}
                  <SourceBadge
                    v-if="sourceOf(item)"
                    :source="sourceOf(item) as string"
                  />
                </summary>
                <pre v-if="item.summary || item.command">{{
                  item.summary ?? item.command
                }}</pre>
              </details>
            </li>
          </template>
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
      </UiCard>

      <UiCard>
        <h3>Agent 執行</h3>
        <button
          v-if="canStartSession"
          class="primary"
          data-start-session
          @click="emit('start-session', task)"
        >
          開始工作
        </button>

        <h4>執行設定</h4>
        <dl class="execution">
          <dt>Runtime</dt>
          <dd>任一支援環境</dd>
          <dt>Runner</dt>
          <dd>{{ task.assigned_runner_id ?? "任一 Agent" }}</dd>
          <dt>來源</dt>
          <dd>
            <select
              v-if="canEdit"
              :value="task.source"
              @change="
                setExecution({
                  source: ($event.target as HTMLSelectElement).value,
                })
              "
            >
              <option value="none">none — 不需要程式碼</option>
              <option value="repo">repo — clone 專案的 repository</option>
              <option value="existing_branch">
                existing_branch — 接續一條既有分支
              </option>
            </select>
            <SourceBadge v-else :source="task.source" />
          </dd>
          <dt>交付</dt>
          <dd>
            <select
              v-if="canEdit"
              :value="task.delivery"
              @change="
                setExecution({
                  delivery: ($event.target as HTMLSelectElement).value,
                })
              "
            >
              <option value="none">none — 不交付</option>
              <option value="artifact">artifact — 附成卡片產物</option>
              <option value="branch">branch — 推一條 cliora/ 分支</option>
              <!-- Shown rather than removed: hiding them would turn "will this
                   platform ever open a PR" into a question somebody has to ask. They
                   are refused at dispatch, and the refusal names the version. -->
              <option value="pull_request">pull_request — V2.4 起生效</option>
              <option value="existing_pr">existing_pr — V2.4 起生效</option>
            </select>
            <DeliveryBadge v-else :delivery="task.delivery" />
          </dd>
          <dt>base branch</dt>
          <dd>{{ task.base_branch ?? "—" }}</dd>
          <!-- Tags decide **which machine** gets this card. They are shown here even
               when empty, because "no tag" is a dispatch-relevant fact rather than an
               absent decoration — and the warning below is the cheapest place to catch
               the commonest failure of the whole mechanism. -->
          <dt>Tag</dt>
          <dd>
            <span v-if="requiredLabels.length" class="tags">
              <BaseBadge
                v-for="tag in requiredLabels"
                :key="tag"
                variant="quiet"
                >{{ tag }}</BaseBadge
              >
            </span>
            <span v-else class="muted">（未宣告，任一 Agent 都可能領走）</span>
          </dd>
          <dt>機密</dt>
          <dd>
            <span v-if="requiredSecrets.length" class="tags">
              <BaseBadge
                v-for="secretName in requiredSecrets"
                :key="secretName"
                variant="quiet"
                >{{ secretName }}</BaseBadge
              >
            </span>
            <span v-else class="muted">（未宣告）</span>
          </dd>
        </dl>
        <!-- A mistyped tag is the commonest way this mechanism fails, and the card then
             sits in the queue forever. Catching it against the tags online runners
             actually report costs one request and is far cheaper than discovering it
             from a stuck card (SC-08). It **warns and does not block**: a runner that
             comes online tomorrow is a legitimate reason. -->
        <p v-if="unmatchedTags.length" class="hint warn">
          ⚠ 目前沒有 runner 具備
          <template v-for="(tag, i) in unmatchedTags" :key="tag"
            ><code>{{ tag }}</code
            ><span v-if="i < unmatchedTags.length - 1">、</span></template
          >，這張卡會一直等。
        </p>
        <!-- Every new card starts here, and every one of them is refused at dispatch.
             The default was chosen for the end state (a PR is the common case); until
             V2.4 exists it means the out-of-the-box card cannot be dispatched, so the
             page says which values do work rather than leaving the reader at a 409. -->
        <p
          v-if="
            task.delivery === 'pull_request' || task.delivery === 'existing_pr'
          "
          class="hint warn"
        >
          ⚠ 這個交付方式從 V2.4 起生效，現在派工會被拒絕。可用的是
          <code>none</code>、<code>artifact</code> 與 <code>branch</code>。
        </p>
        <p v-if="task.delivery === 'branch'" class="hint">
          交付方式是分支：完成時平台會推送
          <code>cliora/{{ task.card_ref }}-&lt;執行次數&gt;</code>。
        </p>
        <!-- V2.1 寫的是「本階段沒有任何執行者會依它行動」，而那句話在 V2.2 之後
             不再為真：`source` 的三個值與 `delivery` 的兩個值現在真的會被依循，
             其餘的在派工當下就被擋下並指名從哪一版開始生效（ADR 0029 §6）。
             一句過期的「沒有人會照做」比沒有說明更糟。 -->
        <p class="hint">
          來源與「不交付／附成產物」自 V2.2 起會被 Agent 依循； 分支與 PR
          的交付方式在派工當下會被擋下，並說明從哪一版開始生效。
        </p>

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
      </UiCard>
    </div>

    <UiCard class="report">
      <template #header>驗證報告與證據</template>
      <p v-if="evidence.length === 0" class="empty">
        尚無證據。驗證結果會保留來源層級，平台不替互相矛盾的資料仲裁。
      </p>
      <ul v-else class="evidence" data-evidence>
        <li v-for="(item, index) in evidence" :key="index">
          <SourceBadge
            v-if="sourceOf(item)"
            :source="sourceOf(item) as string"
          />
          <span>{{ item.label ?? item.text ?? item.kind ?? "證據" }}</span>
          <code v-if="item.value !== undefined">{{ item.value }}</code>
        </li>
      </ul>
    </UiCard>
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
  font-size: var(--font-lg);
}
.ref {
  font-family: var(--font-mono);
  color: var(--text-muted);
}
.columns {
  display: grid;
  grid-template-columns: 1fr 300px;
  gap: var(--space-4);
  margin-top: var(--space-3);
}
.report {
  margin-top: var(--space-4);
}
h3 {
  font-size: var(--font-sm);
  margin-top: 0;
}
h4 {
  font-size: var(--font-sm);
  margin: var(--space-3) 0 var(--space-1);
}
h4 small {
  color: var(--text-muted);
  font-weight: 400;
}
ul {
  list-style: none;
  margin: 0;
  padding: 0;
}
.readiness li[data-met="false"] {
  color: var(--text-muted);
}
.readiness small {
  display: block;
  color: var(--text-muted);
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
  color: var(--text-muted);
  font-size: var(--font-xs);
}
.approved {
  color: var(--status-online);
  font-size: var(--font-xs);
}
.hint,
.empty,
.provenance {
  color: var(--text-muted);
  font-size: var(--font-xs);
}
.criteria .result {
  font-family: var(--font-mono);
  font-size: var(--font-xs);
  margin-right: var(--space-1);
}
.criteria details summary {
  cursor: pointer;
}
.criteria .failed {
  display: grid;
  gap: var(--space-2);
  margin: var(--space-2) 0;
  padding: var(--space-3);
  border-left: 3px solid var(--status-error);
  border-radius: var(--radius-sm);
  background: var(--surface-default);
}
.criteria pre {
  overflow-x: auto;
  margin: var(--space-2) 0 0;
  font-family: var(--font-mono);
  font-size: var(--font-xs);
  white-space: pre-wrap;
}
.evidence {
  display: grid;
  gap: var(--space-2);
}
.evidence li {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
.evidence code {
  margin-left: auto;
  font-family: var(--font-mono);
}
.execution dt {
  color: var(--text-muted);
  font-size: var(--font-xs);
}
</style>
