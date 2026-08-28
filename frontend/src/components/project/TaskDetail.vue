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
import { RouterLink } from "vue-router";

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

const CARD_KIND_LABELS: Record<string, string> = {
  clarification: "釐清",
  decomposition: "拆解",
  mockup: "Mockup",
};
const cardKindLabel = computed(
  () => CARD_KIND_LABELS[props.task.card_kind] ?? props.task.card_kind,
);

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
/** Which extra fields this delivery mode needs, so the panel can show them.
 *
 *  Shown conditionally rather than always: a `target branch` box on a card that
 *  delivers nothing is a question with no right answer, and the panel already carries
 *  enough rows.
 */
const needsTargetBranch = computed(
  () => props.task.delivery === "pull_request",
);
const needsBaseBranch = computed(
  () =>
    props.task.source === "existing_branch" ||
    props.task.delivery === "existing_pr",
);
/** A pull request needs code. The two fields are independent by design, and this is
 *  the one combination they cannot form (ADR 0033 §1). */
const needsSourceForDelivery = computed(
  () =>
    (props.task.delivery === "pull_request" ||
      props.task.delivery === "existing_pr") &&
    props.task.source === "none",
);
const existingPrOutOfNamespace = computed(
  () =>
    props.task.delivery === "existing_pr" &&
    !!props.task.base_branch &&
    !props.task.base_branch.startsWith("cliora/"),
);

/** Space- or comma-separated input into a list, empties dropped.
 *
 *  A text box rather than a tag widget: tags are free strings on purpose (no
 *  dictionary until one capability is spelled three ways), and a widget would imply a
 *  vocabulary that does not exist.
 */
function splitList(value: string): string[] {
  return value
    .split(/[\s,、]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

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

/** Tick or untick one readiness item (V2-P1, PX-30).
 *
 *  **The whole map, not a patch of one key.** `readiness` is a JSONB column and
 *  `update_task` assigns the value it is given, so sending `{acceptance_criteria: true}`
 *  alone would erase the other six. The server does not merge, and it should not: a
 *  partial write to a JSON column is the kind of API where losing data looks like it
 *  worked.
 *
 *  Ticking one is **not** a claim that the platform verified it. A readiness item is
 *  somebody's judgement that the card is ready to be worked on, which is why the list
 *  warns and never refuses (ADR 0028 §1) — and why the console had no control for it until
 *  the Ready-transition dialog gave "fill it in" somewhere to go.
 */
async function setReadiness(key: string, met: boolean): Promise<void> {
  await setExecution({
    readiness: { ...(props.task.readiness ?? {}), [key]: met },
  });
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
      <!-- Only when it is not the default: a board where every card carries a kind
           badge is a board where the badge says nothing. -->
      <span
        v-if="task.card_kind && task.card_kind !== 'implementation'"
        class="kind-badge"
        data-card-kind
        >{{ cardKindLabel }}</span
      >
    </header>

    <!-- FR-SPEC-006. The columns existed from V2.1; this is the render (RQ-10 §5). -->
    <p v-if="task.requirement_id" class="provenance" data-provenance>
      來自需求的提案
      <RouterLink
        :to="{
          name: 'requirement-detail',
          params: { id: task.project_id, requirementId: task.requirement_id },
        }"
        >查看來源需求</RouterLink
      >
    </p>

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
          <li
            v-for="item in readiness"
            :key="item.key"
            :data-met="item.met"
            :data-readiness="item.key"
          >
            <label v-if="canEdit">
              <input
                type="checkbox"
                :checked="item.met"
                :data-readiness-check="item.key"
                @change="
                  setReadiness(
                    item.key,
                    ($event.target as HTMLInputElement).checked,
                  )
                "
              />
              {{ item.label }}
              <small>{{ item.hint }}</small>
            </label>
            <template v-else>
              <span aria-hidden="true">{{ item.met ? "✓" : "○" }}</span>
              {{ item.label }}
              <small>{{ item.hint }}</small>
            </template>
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
            <!-- `aria-label` because the `<dt>` beside it is a *visual* label only:
                 a definition list associates nothing programmatically, so a screen
                 reader announced this as an unnamed combobox. Unlike the `<p>` case in
                 `MetricCard`, `aria-label` **is** permitted on `<select>`. -->
            <select
              v-if="canEdit"
              aria-label="來源"
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
              aria-label="交付"
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
              <option value="pull_request">pull_request — 推分支並開 PR</option>
              <option value="existing_pr">
                existing_pr — 接續平台開過的 PR
              </option>
            </select>
            <DeliveryBadge v-else :delivery="task.delivery" />
          </dd>
          <!-- Editable from V2.4, and the reason it was not before is the reason it
               has to be now: `existing_branch` and `existing_pr` both name the branch
               here, and a field the console can only display makes those two modes
               unreachable from the console. That is the same defect V2.3 shipped for
               `source`/`delivery` and had to fix. -->
          <dt>base branch</dt>
          <dd>
            <input
              v-if="canEdit && needsBaseBranch"
              type="text"
              :value="task.base_branch ?? ''"
              placeholder="cliora/TASK-1-1"
              @change="
                setExecution({
                  base_branch:
                    ($event.target as HTMLInputElement).value.trim() || null,
                })
              "
            />
            <span v-else>{{ task.base_branch ?? "—" }}</span>
          </dd>
          <dt v-if="needsTargetBranch">target branch</dt>
          <dd v-if="needsTargetBranch">
            <input
              v-if="canEdit"
              type="text"
              :value="task.target_branch ?? ''"
              placeholder="main"
              @change="
                setExecution({
                  target_branch:
                    ($event.target as HTMLInputElement).value.trim() || null,
                })
              "
            />
            <span v-else>{{ task.target_branch ?? "—" }}</span>
          </dd>
          <!-- Tags decide **which machine** gets this card. They are shown here even
               when empty, because "no tag" is a dispatch-relevant fact rather than an
               absent decoration — and the warning below is the cheapest place to catch
               the commonest failure of the whole mechanism. -->
          <dt>Tag</dt>
          <dd>
            <input
              v-if="canEdit"
              type="text"
              :value="requiredLabels.join(' ')"
              placeholder="docker node20"
              @change="
                setExecution({
                  required_labels: splitList(
                    ($event.target as HTMLInputElement).value,
                  ),
                })
              "
            />
            <span v-else-if="requiredLabels.length" class="tags">
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
            <input
              v-if="canEdit"
              type="text"
              :value="requiredSecrets.join(' ')"
              placeholder="NPM_TOKEN"
              @change="
                setExecution({
                  required_secrets: splitList(
                    ($event.target as HTMLInputElement).value,
                  ),
                })
              "
            />
            <span v-else-if="requiredSecrets.length" class="tags">
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
        <!-- What each mode still needs, said **here** rather than at the 409. Every
             one of these is a refusal a person would otherwise meet after choosing the
             mode, and the fix for all of them is a field on this same panel. -->
        <p v-if="needsSourceForDelivery" class="hint warn">
          ⚠ 這個交付方式要交付程式碼變更，但來源是 <code>none</code>。
          把來源改成 <code>repo</code>，或把交付方式改成
          <code>none</code>／<code>artifact</code>。
        </p>
        <p
          v-else-if="task.delivery === 'pull_request' && !task.target_branch"
          class="hint warn"
        >
          ⚠ 以合併請求交付必須指定 target branch（PR 要開向哪一條分支）。
        </p>
        <p v-else-if="existingPrOutOfNamespace" class="hint warn">
          ⚠ <code>{{ task.base_branch }}</code> 不在
          <code>cliora/</code> 命名空間內，而平台只推得到那裡面。
          <code>existing_pr</code> 只能接續平台自己開的 PR；要接續別人的分支，
          請改用 <code>branch</code> 並自行合併。
        </p>
        <p v-if="task.delivery === 'branch'" class="hint">
          交付方式是分支：完成時平台會推送
          <code>cliora/{{ task.card_ref }}-&lt;執行次數&gt;</code>。
        </p>
        <!-- V2.1 said "nothing acts on these yet", V2.3 said "the PR modes are
             blocked at dispatch". Both were true when written and neither is now: all
             five delivery modes work. **A sentence that was true once is the most
             expensive kind of stale**, because a reader has no way to tell. -->
        <p class="hint">
          五種交付方式都會被依循。<code>pull_request</code> 的 PR 由平台建立，
          而它的作者是憑證的擁有者、不是派工的人；平台永不自動合併。
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
.kind-badge {
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  padding: 0 var(--space-1);
  font-size: var(--font-xs);
  color: var(--text-muted);
}
.provenance {
  margin: 0 0 var(--space-2);
  font-size: var(--font-sm);
  color: var(--text-muted);
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
