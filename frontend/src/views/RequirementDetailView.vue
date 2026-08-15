<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { RouterLink } from "vue-router";

import { ApiError } from "../api/client";
import {
  ACTION_TASK_APPROVE,
  ACTION_TASK_CREATE,
  ACTION_TASK_UPDATE,
  SPEC_SECTIONS,
  type AcceptProposalResult,
  type FeatureSpec,
  type RequirementDetail,
  type TaskProposal,
} from "../api/dto";
import AsyncState from "../components/common/AsyncState.vue";
import ProposalTree from "../components/project/ProposalTree.vue";
import AppLayout from "../components/layout/AppLayout.vue";
import PageHead from "../components/ui/PageHead.vue";
import UiCard from "../components/ui/UiCard.vue";
import { useAsyncResource } from "../composables/useAsyncResource";
import { api, useAuthStore } from "../stores/auth";
import { formatInstant } from "../utils/time";

const props = defineProps<{ id: string; requirementId: string }>();
const auth = useAuthStore();
const detail = ref<RequirementDetail | null>(null);
const objective = ref("");
const scope = ref("");
const nonGoals = ref("");
const criteriaJson = ref("[]");
const questionsJson = ref("[]");
const proposalJson = ref('{"tasks": []}');
const actionError = ref("");
const actionResult = ref<AcceptProposalResult | null>(null);
// The readiness vocabulary comes from the process definition, never from a constant
// here: a project may disable items (ADR 0033 §5), and a hardcoded list would show a
// card as short of something this project switched off.
const readinessKeys = ref<string[]>([]);
// Which two versions the comparison shows. Defaults to the last two; a specification
// with six versions is one somebody wants to compare across.
const leftSeq = ref<number | null>(null);
const rightSeq = ref<number | null>(null);

const resource = useAsyncResource(async () => {
  const [loaded, process] = await Promise.all([
    api().getRequirement(props.requirementId),
    api().getProcess(props.id),
  ]);
  detail.value = loaded;
  readinessKeys.value = process.readiness.map((item) => item.key);
  if (leftSeq.value === null && loaded.specs.length > 1) {
    leftSeq.value = loaded.specs[loaded.specs.length - 2].seq;
  }
  if (rightSeq.value === null && loaded.specs.length > 0) {
    rightSeq.value = loaded.specs[loaded.specs.length - 1].seq;
  }
});

function parseArray(value: string): Array<Record<string, unknown>> {
  const parsed: unknown = JSON.parse(value);
  if (!Array.isArray(parsed)) throw new Error("必須是 JSON 陣列");
  return parsed as Array<Record<string, unknown>>;
}

async function addSpec(): Promise<void> {
  actionError.value = "";
  try {
    await api().addSpec(props.requirementId, {
      objective: objective.value || null,
      scope: scope.value || null,
      non_goals: nonGoals.value || null,
      acceptance_criteria: parseArray(criteriaJson.value),
      open_questions: parseArray(questionsJson.value),
    });
    await resource.run();
  } catch (error) {
    actionError.value =
      error instanceof Error ? error.message : "新增規格失敗。";
  }
}

async function approve(): Promise<void> {
  actionError.value = "";
  try {
    await api().approveRequirement(props.requirementId);
    await resource.run();
  } catch (error) {
    actionError.value =
      error instanceof ApiError ? error.message : "核准失敗。";
  }
}

async function propose(): Promise<void> {
  actionError.value = "";
  try {
    const tree = JSON.parse(proposalJson.value) as Record<string, unknown>;
    await api().createProposal(props.requirementId, tree);
    await resource.run();
  } catch (error) {
    actionError.value =
      error instanceof Error ? error.message : "建立提案失敗。";
  }
}

async function accept(
  proposal: TaskProposal,
  payload: {
    acceptIds: string[];
    overrides: Record<string, Record<string, unknown>>;
  },
): Promise<void> {
  actionError.value = "";
  actionResult.value = null;
  try {
    actionResult.value = await api().acceptProposal(proposal.id, {
      accept_ids: payload.acceptIds,
      overrides: payload.overrides,
    });
    await resource.run();
  } catch (error) {
    actionError.value =
      error instanceof ApiError ? error.message : "接受失敗。";
  }
}

async function reject(proposal: TaskProposal, note: string): Promise<void> {
  actionError.value = "";
  try {
    await api().rejectProposal(proposal.id, note);
    await resource.run();
  } catch (error) {
    actionError.value =
      error instanceof ApiError ? error.message : "拒絕失敗。";
  }
}

/** The two versions being compared, left first. */
const comparedSpecs = computed<FeatureSpec[]>(() => {
  const specs = detail.value?.specs ?? [];
  const pick = (seq: number | null): FeatureSpec | undefined =>
    specs.find((spec) => spec.seq === seq);
  return [pick(leftSeq.value), pick(rightSeq.value)].filter(
    (spec): spec is FeatureSpec => spec !== undefined,
  );
});

/**
 * Which sections differ between the two versions.
 *
 * Section-level, never character-level: "which section changed" is what a reviewer
 * needs, and a character diff needs a diff component — the near neighbour of the thing
 * `plan/14` withdrew.
 */
const changedSections = computed(() => {
  const [left, right] = comparedSpecs.value;
  if (!left || !right) return new Set<string>();
  const changed = new Set<string>();
  for (const field of ["objective", "scope", "non_goals"] as const) {
    if (left[field] !== right[field]) changed.add(field);
  }
  for (const { key } of SPEC_SECTIONS) {
    if (
      JSON.stringify(left.sections?.[key] ?? null) !==
      JSON.stringify(right.sections?.[key] ?? null)
    ) {
      changed.add(key);
    }
  }
  return changed;
});

function sectionText(spec: FeatureSpec, key: string): string {
  const value = spec.sections?.[key];
  if (value === undefined || value === null || value === "") return "—";
  return typeof value === "string" ? value : JSON.stringify(value, null, 2);
}

/** Unresolved questions on a version, using the server's own rule. */
function unresolved(spec: FeatureSpec): Array<Record<string, unknown>> {
  return spec.open_questions.filter(
    (question) => !question.answer && !question.resolved_as,
  );
}

onMounted(() => resource.run());
</script>

<template>
  <AppLayout>
    <main class="requirement-page">
      <nav class="breadcrumbs" aria-label="Breadcrumb">
        <RouterLink
          :to="{
            name: 'project-detail',
            params: { id },
            query: { tab: 'requirements' },
          }"
        >
          Requirements
        </RouterLink>
        <span>/</span><span>{{ detail?.card_ref ?? "Requirement" }}</span>
      </nav>

      <AsyncState v-if="resource.state.value === 'loading'" state="loading"
        >載入需求…</AsyncState
      >
      <AsyncState v-else-if="resource.state.value === 'error'" state="error">
        無法載入需求。<button class="ghost" @click="resource.run">重試</button>
      </AsyncState>
      <template v-else-if="detail">
        <PageHead>
          <template #title>{{ detail.raw_text }}</template>
          <template #subtitle
            >{{ detail.card_ref }} · {{ detail.status }}</template
          >
        </PageHead>
        <ol class="stepper" aria-label="需求流程">
          <li class="done">1 提出需求</li>
          <li :class="{ done: detail.specs.length > 0 }">2 撰寫規格</li>
          <li :class="{ done: detail.approved_at }">3 人工核准</li>
          <li :class="{ done: detail.proposals.length > 0 }">4 任務提案</li>
        </ol>
        <p
          v-if="detail.blocking_questions.length"
          id="blocking-questions"
          class="notice open-questions"
          data-blocking-questions
        >
          尚有未決問題：{{ detail.blocking_questions.join("、") }}
        </p>
        <p v-if="actionError" class="notice error" role="alert">
          {{ actionError }}
        </p>
        <p v-if="actionResult" class="notice" role="status">
          已建立 {{ actionResult.created.length }} 張任務卡。
          <template v-if="Object.keys(actionResult.incomplete).length">
            未符合 DoR 而留在 Backlog：
            {{
              Object.entries(actionResult.incomplete)
                .map(([ref, missing]) => `${ref}（${missing.join("、")}）`)
                .join("；")
            }}
          </template>
          <template
            v-if="Object.keys(actionResult.unresolved_dependencies).length"
          >
            <br />
            相依指向沒被接受的節點，因此沒有建立相依：
            {{
              Object.entries(actionResult.unresolved_dependencies)
                .map(([ref, items]) => `${ref}（${items.join("、")}）`)
                .join("；")
            }}
          </template>
        </p>

        <UiCard>
          <template #header>規格審閱</template>
          <p v-if="detail.specs.length === 0" class="muted">尚無規格版本。</p>
          <template v-else>
            <div class="version-pick">
              <label>
                比較
                <select v-model.number="leftSeq" data-compare-left>
                  <option
                    v-for="spec in detail.specs"
                    :key="spec.id"
                    :value="spec.seq"
                  >
                    v{{ spec.seq }}
                  </option>
                </select>
              </label>
              <label>
                與
                <select v-model.number="rightSeq" data-compare-right>
                  <option
                    v-for="spec in detail.specs"
                    :key="spec.id"
                    :value="spec.seq"
                  >
                    v{{ spec.seq }}
                  </option>
                </select>
              </label>
            </div>
            <div class="spec-compare">
              <article v-for="spec in comparedSpecs" :key="spec.id">
                <h3>
                  v{{ spec.seq }} · {{ formatInstant(spec.created_at) }}
                  <span class="badge author">
                    {{
                      spec.authored_by_kind === "runner"
                        ? "Agent 撰寫"
                        : "人撰寫"
                    }}
                  </span>
                  <RouterLink
                    v-if="spec.run_id"
                    class="run-link"
                    :to="{
                      name: 'run-detail',
                      params: { id, runId: spec.run_id },
                    }"
                  >
                    看執行紀錄
                  </RouterLink>
                </h3>

                <!-- Unresolved questions first, and gone entirely when there are none:
                     a green "no open questions" panel would take the most expensive
                     space on the screen to report something that did not happen. -->
                <section
                  v-if="unresolved(spec).length"
                  class="open-questions"
                  data-open-questions
                >
                  <h4>未解決的問題（{{ unresolved(spec).length }}）</h4>
                  <ul>
                    <li
                      v-for="(question, index) in unresolved(spec)"
                      :key="index"
                    >
                      {{ question.question ?? question.id }}
                    </li>
                  </ul>
                </section>

                <dl>
                  <template
                    v-for="field in ['objective', 'scope', 'non_goals']"
                    :key="field"
                  >
                    <dt :data-changed="changedSections.has(field)">
                      {{
                        field === "objective"
                          ? "目標"
                          : field === "scope"
                            ? "範圍"
                            : "非目標"
                      }}
                    </dt>
                    <dd>{{ spec[field as "objective"] ?? "—" }}</dd>
                  </template>
                </dl>

                <h4>驗收標準</h4>
                <ul class="criteria">
                  <li
                    v-for="(item, index) in spec.acceptance_criteria"
                    :key="index"
                  >
                    {{ item.text ?? JSON.stringify(item) }}
                  </li>
                  <li
                    v-if="spec.acceptance_criteria.length === 0"
                    class="muted"
                  >
                    —
                  </li>
                </ul>

                <!-- The nine sections Monstrare's template has. `user_stories` is the
                     one a decomposition reads, which is why it is not folded away. -->
                <section
                  v-for="section in SPEC_SECTIONS"
                  :key="section.key"
                  class="section"
                  :data-section="section.key"
                  :data-changed="changedSections.has(section.key)"
                >
                  <h4>{{ section.label }}</h4>
                  <pre>{{ sectionText(spec, section.key) }}</pre>
                </section>
              </article>
            </div>
          </template>
        </UiCard>

        <UiCard v-if="auth.hasPermission(ACTION_TASK_UPDATE)" class="form-grid">
          <template #header>新增規格版本</template>
          <label>目標<textarea v-model="objective" /></label>
          <label>範圍<textarea v-model="scope" /></label>
          <label>非目標<textarea v-model="nonGoals" /></label>
          <label
            >驗收標準 JSON<textarea v-model="criteriaJson" data-spec-criteria />
          </label>
          <label
            >未決問題 JSON<textarea
              v-model="questionsJson"
              data-spec-questions
            />
          </label>
          <button class="primary" @click="addSpec">儲存新版本</button>
        </UiCard>

        <UiCard>
          <template #header>人工核准</template>
          <!-- The disabled state says the same sentence the API would: a rule that only
               greys out a button is a rule people look for a way round. -->
          <p v-if="detail.specs.length === 0" class="muted" data-approve-reason>
            先寫一份規格，或派給 Agent 釐清。
          </p>
          <p
            v-else-if="detail.blocking_questions.length"
            class="muted"
            data-approve-reason
          >
            這幾個問題還沒有解決，所以還不能核准：{{
              detail.blocking_questions.join("、")
            }}
          </p>
          <p v-else class="muted" data-approve-reason>
            核准之後這個需求就不能再新增規格版本了。
          </p>
          <button
            v-if="auth.hasPermission(ACTION_TASK_APPROVE)"
            class="primary"
            :disabled="
              detail.blocking_questions.length > 0 || detail.specs.length === 0
            "
            :aria-describedby="
              detail.blocking_questions.length
                ? 'blocking-questions'
                : undefined
            "
            data-approve-requirement
            @click="approve"
          >
            核准規格
          </button>
        </UiCard>

        <UiCard>
          <template #header>任務提案</template>
          <div v-if="auth.hasPermission(ACTION_TASK_CREATE)" class="form-grid">
            <label
              >提案樹 JSON<textarea
                v-model="proposalJson"
                data-proposal-tree-json
              />
            </label>
            <button class="ghost" @click="propose">建立提案</button>
          </div>
          <article
            v-for="proposal in detail.proposals"
            :key="proposal.id"
            class="proposal"
          >
            <h3>
              提案 #{{ proposal.seq }}
              <span class="badge status">{{ proposal.status }}</span>
              <span
                v-if="
                  proposal.remaining_item_ids.length &&
                  proposal.status === 'partially_accepted'
                "
                class="badge remaining"
              >
                還有 {{ proposal.remaining_item_ids.length }} 張可以接受
              </span>
            </h3>
            <p v-if="proposal.decision_note" class="decision-note">
              決定理由：{{ proposal.decision_note }}
            </p>
            <ProposalTree
              v-if="['pending', 'partially_accepted'].includes(proposal.status)"
              :proposal="proposal"
              :readiness-keys="readinessKeys"
              :can-decide="auth.hasPermission(ACTION_TASK_APPROVE)"
              @accept="(payload) => accept(proposal, payload)"
              @reject="(note) => reject(proposal, note)"
            />
          </article>
        </UiCard>
      </template>
    </main>
  </AppLayout>
</template>

<style scoped>
.requirement-page,
.form-grid {
  display: grid;
  gap: var(--space-3);
}
.breadcrumbs,
.stepper {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
.stepper {
  margin: 0;
  padding: 0;
  list-style: none;
}
.stepper li {
  flex: 1;
  padding: var(--space-2);
  border-top: 3px solid var(--border-default);
  color: var(--text-muted);
  font-size: var(--font-sm);
}
.stepper li.done {
  border-color: var(--stage-done);
  color: var(--text-primary);
}
.open-questions {
  margin: 0;
  border-left: 3px solid var(--risk-medium);
  padding: var(--space-2) var(--space-3);
  background: var(--surface-default);
}
.spec-compare {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-3);
}
.spec-compare article,
.proposal {
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  padding: var(--space-3);
}
.version-pick {
  display: flex;
  gap: var(--space-3);
  margin-bottom: var(--space-2);
}
.open-questions ul {
  margin: 0;
  padding-left: var(--space-4);
}
.open-questions h4 {
  margin: 0 0 var(--space-1);
}
.criteria {
  margin: 0;
  padding-left: var(--space-4);
}
.section[data-changed="true"],
dt[data-changed="true"] {
  border-left: 3px solid var(--risk-medium);
  padding-left: var(--space-2);
}
.badge {
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  padding: 0 var(--space-1);
  font-size: var(--font-xs);
  color: var(--text-muted);
  margin-left: var(--space-2);
}
.run-link {
  margin-left: var(--space-2);
  font-size: var(--font-xs);
}
.decision-note {
  margin: 0 0 var(--space-2);
  font-size: var(--font-sm);
  color: var(--text-muted);
}
textarea {
  display: block;
  width: 100%;
  min-height: 6rem;
}
pre {
  overflow: auto;
  white-space: pre-wrap;
}
@media (max-width: 800px) {
  .spec-compare {
    grid-template-columns: 1fr;
  }
}
</style>
