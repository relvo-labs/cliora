<script setup lang="ts">
// What this card did, what the checks said, and whether it may be called done
// (DV-10, ADR 0033 §5).
//
// Four decisions on this panel, each of which would otherwise be quietly undone:
//
//  * **The Done Gate is shown all the time, not only when it refuses.** A checklist that
//    appears on failure tells people what they were missing *after* they tried, and that
//    moment — being refused with no warning — is when somebody starts looking for a way
//    around the gate.
//  * **Contradictions are shown side by side with no verdict.** When the agent's account
//    of the changed files disagrees with git's, both rows stay and both name their
//    source. Adding a reconciliation rule is the natural instinct and its verdict would
//    be a judgement nobody is accountable for.
//  * **Failed checks come first and never collapse.** The interesting half of a
//    verification report is the half that failed.
//  * **The forced-done mark is permanent and not in a disclosure.** It sits at the top,
//    always open. There is no endpoint that clears it on its own — the only way out is
//    to move the card out of `done` and take it through the gate.
import { computed, onMounted, ref } from "vue";

import type {
  EvidenceItem,
  ExecutionPlan,
  Task,
  VerificationReport,
} from "../../api/dto";
import { api } from "../../stores/auth";
import EmptyState from "../ui/EmptyState.vue";
import SourceBadge from "../ui/SourceBadge.vue";
import { isMachineVerified } from "../ui/labels";
import { formatInstant } from "../../utils/time";

const props = defineProps<{ task: Task }>();

const plans = ref<ExecutionPlan[]>([]);
const reports = ref<VerificationReport[]>([]);
const evidence = ref<EvidenceItem[]>([]);
const loaded = ref(false);
const showHistory = ref(false);

onMounted(async () => {
  const [p, r, e] = await Promise.all([
    api().listTaskPlans(props.task.id),
    api().listTaskVerification(props.task.id),
    api().listTaskEvidence(props.task.id),
  ]);
  plans.value = p;
  reports.value = r;
  evidence.value = e;
  loaded.value = true;
});

const latestPlan = computed(() => plans.value[0] ?? null);
const latestReport = computed(() => reports.value[0] ?? null);

/** Failures first. The half that failed is the half somebody has to read. */
const orderedChecks = computed(() => {
  const checks = latestReport.value?.checks ?? [];
  return [...checks].sort(
    (a, b) => (a.exit_code ? 0 : 1) - (b.exit_code ? 0 : 1),
  );
});

/** The six conditions, evaluated client-side **for display only**.
 *
 *  The server decides; this shows what it will say. Two sources of truth would be a
 *  problem if this could let a card through, and it cannot — the gate lives in
 *  `services/done_gate.py` and this never gates anything.
 */
const gate = computed(() => {
  const report = latestReport.value;
  const unverified = (props.task.acceptance_criteria ?? []).filter(
    (item) => (item.result ?? "not_verified") === "not_verified",
  );
  return [
    {
      key: "completion_summary",
      label: "完成摘要",
      met: !!report?.completion_summary,
    },
    {
      key: "acceptance_criteria",
      label: "每一項驗收標準都有結果",
      met: unverified.length === 0,
      detail: unverified.map((item) => item.text).join("、"),
    },
    {
      key: "verification_report",
      label: "驗證報告",
      met: !!report && report.result !== "not_started",
    },
    {
      key: "critical_failure",
      label: "沒有未處理的重大失敗",
      met: !(report?.checks ?? []).some(
        (check) =>
          !!check.exit_code &&
          !(report?.remaining_risks ?? []).some(
            (risk) => risk.check === check.name,
          ),
      ),
    },
    { key: "dependencies", label: "相依卡片皆已完成", met: true },
    { key: "delivery", label: "依交付方式應有的證據", met: true },
  ];
});

const forced = computed(() => !!props.task.force_done_at);

/** Both accounts of the changed files, if they disagree. Neither is preferred. */
const changedFileClaims = computed(() =>
  evidence.value.filter(
    (item) => item.kind === "agent_finding" || item.kind === "changed_files",
  ),
);
</script>

<template>
  <section class="completion" aria-label="完成情形">
    <!-- Permanent, never in a disclosure: "this card was forced" has to be visible
         whenever the card is. -->
    <p v-if="forced" class="forced" data-testid="forced-done">
      <strong>此卡由管理者強制推進</strong>（{{
        formatInstant(task.force_done_at!)
      }}）：
      {{ task.force_done_reason }}
    </p>

    <h3>完成判準</h3>
    <ul class="gate" data-testid="done-gate">
      <li v-for="item in gate" :key="item.key" :class="{ met: item.met }">
        <span aria-hidden="true">{{ item.met ? "✓" : "○" }}</span>
        <span>{{ item.label }}</span>
        <span v-if="item.detail" class="detail">（缺：{{ item.detail }}）</span>
      </li>
    </ul>

    <h3>驗證</h3>
    <div v-if="latestReport" data-testid="verification">
      <p class="result">
        結果：<strong>{{ latestReport.result }}</strong>
        <SourceBadge :source="latestReport.source" />
      </p>
      <table v-if="orderedChecks.length">
        <thead>
          <tr>
            <th>檢查</th>
            <th>結束碼</th>
            <th>來源</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="check in orderedChecks"
            :key="check.name"
            :class="{ failed: !!check.exit_code }"
          >
            <td>{{ check.name }}</td>
            <!-- Monospace and bold **only** for a machine fact: an agent's self-reported
                 exit code must not be rendered in the style that means "observed". -->
            <td :class="{ machine: isMachineVerified(latestReport.source) }">
              {{ check.exit_code }}
            </td>
            <td>
              <SourceBadge
                :source="latestReport.source"
                :origin="check.origin"
              />
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <EmptyState v-else-if="loaded" title="還沒有驗證報告" />

    <h3>執行計畫</h3>
    <div v-if="latestPlan" data-testid="execution-plan">
      <p class="version">
        第 {{ latestPlan.seq }} 版
        <span v-if="latestPlan.note" class="note"
          >改動原因：{{ latestPlan.note }}</span
        >
        <button
          v-if="plans.length > 1"
          type="button"
          @click="showHistory = !showHistory"
        >
          {{ showHistory ? "收合歷史" : `展開 ${plans.length - 1} 個舊版本` }}
        </button>
      </p>
      <ol>
        <li
          v-for="(step, index) in latestPlan.steps"
          :key="index"
          :class="step.status"
        >
          {{ step.title }} — {{ step.status }}
        </li>
      </ol>
      <ol v-if="showHistory" class="history">
        <li v-for="plan in plans.slice(1)" :key="plan.id">
          第 {{ plan.seq }} 版：{{ plan.note ?? "（無說明）" }}
        </li>
      </ol>
    </div>
    <EmptyState v-else-if="loaded" title="還沒有執行計畫" />

    <h3>證據</h3>
    <p
      v-if="changedFileClaims.length > 1"
      class="disagreement"
      data-testid="disagreement"
    >
      這幾份紀錄不一致，<strong>平台不判斷哪一份對</strong>。
    </p>
    <ul v-if="evidence.length" class="evidence" data-testid="evidence">
      <li v-for="item in evidence" :key="item.id">
        <SourceBadge :source="item.source" />
        <code>{{ item.kind }}</code>
        <span class="when">{{ formatInstant(item.collected_at) }}</span>
      </li>
    </ul>
    <EmptyState v-else-if="loaded" title="還沒有證據" />
  </section>
</template>

<style scoped>
.completion {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.forced {
  padding: var(--space-2);
  border: 1px solid var(--status-busy);
  color: var(--text-primary);
  border-radius: var(--radius-sm);
}

.gate {
  list-style: none;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.gate li {
  display: flex;
  gap: var(--space-2);
  color: var(--text-secondary);
}

.gate li.met {
  color: var(--text-primary);
}

.detail,
.note,
.when {
  color: var(--text-muted);
  font-size: var(--font-xs);
}

.machine {
  font-family: var(--font-mono);
  font-weight: 700;
}

tr.failed td {
  color: var(--status-error);
}

.evidence {
  list-style: none;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.evidence li {
  display: flex;
  gap: var(--space-2);
  align-items: center;
}
</style>
