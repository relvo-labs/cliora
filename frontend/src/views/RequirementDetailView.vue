<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { RouterLink } from "vue-router";

import { ApiError } from "../api/client";
import {
  ACTION_TASK_APPROVE,
  ACTION_TASK_CREATE,
  ACTION_TASK_UPDATE,
  type AcceptProposalResult,
  type RequirementDetail,
  type TaskProposal,
} from "../api/dto";
import AsyncState from "../components/common/AsyncState.vue";
import AppLayout from "../components/layout/AppLayout.vue";
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
const selectedProposalItems = ref<Record<string, string[]>>({});

function proposalTasks(proposal: TaskProposal): Array<Record<string, unknown>> {
  const tasks = proposal.tree.tasks;
  return Array.isArray(tasks)
    ? tasks.filter(
        (item): item is Record<string, unknown> =>
          typeof item === "object" && item !== null,
      )
    : [];
}

function proposalItemId(item: Record<string, unknown>): string {
  return typeof item.id === "string" ? item.id : "";
}

function proposalItemTitle(item: Record<string, unknown>): string {
  return typeof item.title === "string" ? item.title : "未命名任務";
}

const resource = useAsyncResource(async () => {
  detail.value = await api().getRequirement(props.requirementId);
  for (const proposal of detail.value.proposals) {
    if (!(proposal.id in selectedProposalItems.value)) {
      selectedProposalItems.value[proposal.id] = proposalTasks(proposal)
        .map(proposalItemId)
        .filter(Boolean);
    }
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

async function accept(proposal: TaskProposal): Promise<void> {
  if (!window.confirm("接受這份提案並建立所選任務嗎？")) return;
  actionError.value = "";
  actionResult.value = null;
  try {
    actionResult.value = await api().acceptProposal(proposal.id, {
      accept_ids: selectedProposalItems.value[proposal.id] ?? [],
    });
    await resource.run();
  } catch (error) {
    actionError.value =
      error instanceof ApiError ? error.message : "接受失敗。";
  }
}

const comparedSpecs = computed(() => detail.value?.specs.slice(-2) ?? []);
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
        <header>
          <span class="ref">{{ detail.card_ref }}</span>
          <h1>{{ detail.raw_text }}</h1>
          <span class="status">{{ detail.status }}</span>
        </header>
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
        </p>

        <section>
          <h2>規格版本比較</h2>
          <div class="spec-compare">
            <article v-for="spec in comparedSpecs" :key="spec.id">
              <h3>v{{ spec.seq }} · {{ formatInstant(spec.created_at) }}</h3>
              <dl>
                <dt>目標</dt>
                <dd>{{ spec.objective ?? "—" }}</dd>
                <dt>範圍</dt>
                <dd>{{ spec.scope ?? "—" }}</dd>
                <dt>非目標</dt>
                <dd>{{ spec.non_goals ?? "—" }}</dd>
              </dl>
              <h4>驗收標準</h4>
              <pre>{{ JSON.stringify(spec.acceptance_criteria, null, 2) }}</pre>
              <h4>未決問題</h4>
              <pre>{{ JSON.stringify(spec.open_questions, null, 2) }}</pre>
            </article>
            <p v-if="comparedSpecs.length === 0" class="muted">
              尚無規格版本。
            </p>
          </div>
        </section>

        <section
          v-if="auth.hasPermission(ACTION_TASK_UPDATE)"
          class="form-grid"
        >
          <h2>新增規格版本</h2>
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
        </section>

        <section>
          <h2>人工核准</h2>
          <p
            v-if="detail.blocking_questions.length"
            class="notice"
            data-blocking-questions
          >
            尚有未決問題：{{ detail.blocking_questions.join("、") }}
          </p>
          <button
            v-if="auth.hasPermission(ACTION_TASK_APPROVE)"
            class="primary"
            :disabled="
              detail.blocking_questions.length > 0 || detail.specs.length === 0
            "
            data-approve-requirement
            @click="approve"
          >
            核准規格
          </button>
        </section>

        <section>
          <h2>任務提案</h2>
          <div v-if="auth.hasPermission(ACTION_TASK_CREATE)" class="form-grid">
            <label
              >提案樹 JSON<textarea v-model="proposalJson" data-proposal-tree />
            </label>
            <button class="ghost" @click="propose">建立提案</button>
          </div>
          <article
            v-for="proposal in detail.proposals"
            :key="proposal.id"
            class="proposal"
          >
            <h3>提案 v{{ proposal.seq }} · {{ proposal.status }}</h3>
            <pre>{{ JSON.stringify(proposal.tree, null, 2) }}</pre>
            <fieldset
              v-if="
                auth.hasPermission(ACTION_TASK_APPROVE) &&
                ['pending', 'partially_accepted'].includes(proposal.status)
              "
            >
              <legend>選擇要建立的任務</legend>
              <label
                v-for="item in proposalTasks(proposal)"
                :key="proposalItemId(item)"
                class="proposal-item"
              >
                <input
                  v-model="selectedProposalItems[proposal.id]"
                  type="checkbox"
                  :value="proposalItemId(item)"
                />
                {{ proposalItemTitle(item) }}
              </label>
              <button
                class="primary"
                data-accept-proposal
                :disabled="!selectedProposalItems[proposal.id]?.length"
                @click="accept(proposal)"
              >
                接受所選任務
              </button>
            </fieldset>
          </article>
        </section>
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
header {
  display: flex;
  align-items: baseline;
  gap: var(--space-2);
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
.proposal-item {
  display: block;
  margin-block: var(--space-2);
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
