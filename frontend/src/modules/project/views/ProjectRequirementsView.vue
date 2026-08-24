<script setup lang="ts">
/**
 * Requirement intake and the two agent dispatches (PX-64). Formerly `?tab=requirements`.
 *
 * Intake is **one field on purpose** (D28): it accepts a vague sentence, which is the
 * premise of the whole flow. A form with ten required fields at this moment is how the
 * flow stops being used.
 */
import { onMounted, ref } from "vue";
import { RouterLink } from "vue-router";

import { ApiError } from "../../../api/client";
import type { Requirement } from "../../../api/dto";
import PatchProposals from "../../../components/project/PatchProposals.vue";
import EmptyState from "../../../components/ui/EmptyState.vue";
import UiButton from "../../../components/ui/UiButton.vue";
import UiCard from "../../../components/ui/UiCard.vue";
import { api } from "../../../stores/auth";
import { useProjectContext } from "../useProjectContext";

const context = useProjectContext();
const { projectId, isArchived, can } = context;

const requirements = ref<Requirement[]>([]);
const intakeText = ref("");
const taskError = ref("");

onMounted(async () => {
  requirements.value = await api().listRequirements(projectId);
});

async function submitIntake(): Promise<void> {
  taskError.value = "";
  try {
    await api().createRequirement(projectId, { raw_text: intakeText.value });
    intakeText.value = "";
    requirements.value = await api().listRequirements(projectId);
  } catch (error) {
    taskError.value = error instanceof ApiError ? error.message : "建立失敗。";
  }
}

/**
 * Send a requirement to an agent (RQ-10 §1.2, FR-SPEC-002).
 *
 * **Two requests, and the second one fails often** — every dispatch refusal in this phase
 * lands there (no repository registered, no eligible runner, the four card-kind rules). So
 * the failure path matters more than the success one:
 *
 * * the card **stays**. Deleting it on failure would delete a perfectly good card when the
 *   reason was "no runner is online yet", which is a wait rather than a mistake;
 * * the message names the card and links to it, because by then the card exists and the
 *   person needs to be able to find it;
 * * the requirement row remembers it, so a second click does not make a second card.
 */
const dispatchingId = ref<string | null>(null);
const dispatchedCards = ref<Record<string, { ref: string; id: string }>>({});

async function sendToAgent(
  requirementId: string,
  kind: "clarification" | "decomposition",
  cardRef: string,
): Promise<void> {
  taskError.value = "";
  dispatchingId.value = requirementId;
  let created: { id: string; card_ref: string } | null = null;
  try {
    const result = await api().createTask(projectId, {
      title: kind === "clarification" ? `釐清 ${cardRef}` : `拆解 ${cardRef}`,
      card_kind: kind,
      requirement_id: requirementId,
      // A run that reads code asks better questions; delivery is inert either way, and
      // the server refuses anything else for these kinds.
      source: "repo",
      delivery: "artifact",
      stage: "ready",
    });
    created = { id: result.task.id, card_ref: result.task.card_ref };
    dispatchedCards.value = {
      ...dispatchedCards.value,
      [requirementId]: { ref: result.task.card_ref, id: result.task.id },
    };
    await api().dispatchTask(result.task.id);
    requirements.value = await api().listRequirements(projectId);
  } catch (error) {
    const detail = error instanceof ApiError ? error.message : "派工失敗。";
    taskError.value = created
      ? `卡片 ${created.card_ref} 已建立，但派工被拒：${detail}`
      : detail;
  } finally {
    dispatchingId.value = null;
  }
}
</script>

<template>
  <section class="tab-panel">
    <div class="workbar requirement-bar">
      <div class="workbar-copy">
        <strong>Requirement intake</strong>
        <span
          >Start with one imperfect sentence; clarification happens next.</span
        >
      </div>
      <div v-if="can.createTasks.value && !isArchived" class="quick-create">
        <input
          v-model="intakeText"
          placeholder="用一句話說你想要什麼"
          data-new-requirement
        />
        <UiButton
          variant="primary"
          size="sm"
          :disabled="!intakeText"
          @click="submitIntake"
        >
          提出需求
        </UiButton>
      </div>
    </div>
    <!-- Every dispatch refusal this phase added lands here, and until V2.5 this panel had
         nowhere to show one. A refusal a person cannot see is the same as a button that
         silently does nothing. -->
    <p
      v-if="taskError"
      class="notice error"
      role="alert"
      data-requirement-error
    >
      {{ taskError }}
    </p>
    <UiCard v-if="requirements.length" flush>
      <ul class="requirements">
        <li
          v-for="item in requirements"
          :key="item.id"
          :data-status="item.status"
        >
          <RouterLink
            :to="{
              name: 'requirement-detail',
              params: { id: projectId, requirementId: item.id },
            }"
          >
            <span class="ref">{{ item.card_ref }}</span>
            {{ item.raw_text }}
          </RouterLink>
          <span class="status">{{ item.status }}</span>
          <!-- Disabled is not enough: a rule people cannot see the reason for is a rule
               they look for a way round. The API refuses the same thing. -->
          <span
            v-if="can.dispatch.value && !isArchived"
            class="requirement-actions"
          >
            <UiButton
              size="sm"
              variant="ghost"
              :disabled="
                dispatchingId === item.id ||
                !['intake', 'clarifying'].includes(item.status)
              "
              :title="
                ['intake', 'clarifying'].includes(item.status)
                  ? '建立一張釐清卡並派給 Agent'
                  : '這個需求已經有規格了'
              "
              :data-clarify="item.card_ref"
              @click="sendToAgent(item.id, 'clarification', item.card_ref)"
            >
              派給 Agent 釐清
            </UiButton>
            <UiButton
              size="sm"
              variant="ghost"
              :disabled="
                dispatchingId === item.id || item.status !== 'approved'
              "
              :title="
                item.status === 'approved'
                  ? '建立一張拆解卡並派給 Agent'
                  : '先核准規格。未核准的規格不能被拆解——這是 API 層的規則，不是介面的限制。'
              "
              :data-decompose="item.card_ref"
              @click="sendToAgent(item.id, 'decomposition', item.card_ref)"
            >
              派給 Agent 拆解
            </UiButton>
          </span>
          <RouterLink
            v-if="dispatchedCards[item.id]"
            class="dispatched-card"
            :data-dispatched="item.card_ref"
            :to="{
              name: 'task-detail',
              params: { id: projectId, taskId: dispatchedCards[item.id].id },
            }"
          >
            已建立 {{ dispatchedCards[item.id].ref }}
          </RouterLink>
        </li>
      </ul>
    </UiCard>
    <EmptyState v-else>
      還沒有需求。丟一句模糊的話進來就可以開始。
      <template #action>
        <span class="empty-guidance"
          >需求會先進入收件，再由 Agent 協助釐清。</span
        >
      </template>
    </EmptyState>

    <!-- Here rather than on Overview, where it used to be: a patch proposal is a decision
         about a requirement, and this is the page a person is on when they make it. -->
    <PatchProposals
      :client="api()"
      :project-id="projectId"
      :can-decide="can.approve.value"
    />
  </section>
</template>

<style scoped>
.tab-panel {
  display: grid;
  gap: var(--space-4);
}
.workbar {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  min-height: 58px;
  padding: var(--space-2) var(--space-3) var(--space-2) var(--space-4);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  background: var(--surface-default);
}
.workbar-copy {
  display: grid;
  gap: 2px;
  min-width: 0;
  margin-right: auto;
}
.workbar-copy strong {
  font-size: var(--font-sm);
}
.workbar-copy span {
  color: var(--text-muted);
  font-size: var(--font-xs);
}
.quick-create {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
.quick-create input {
  width: 220px;
  min-height: 32px;
  padding: 0 var(--space-3);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  color: var(--text-primary);
  background: var(--surface-elevated);
  font-size: var(--font-sm);
}
.requirement-bar .quick-create input {
  width: min(380px, 34vw);
}
.requirements {
  list-style: none;
  margin: 0;
  padding: 0;
}
.requirements li {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: var(--space-4);
  min-height: 58px;
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--border-default);
}
.requirements li:last-child {
  border-bottom: 0;
}
.requirements a {
  display: flex;
  align-items: baseline;
  gap: var(--space-3);
  min-width: 0;
  color: var(--text-primary);
  font-weight: 600;
  text-decoration: none;
}
.requirements a:hover {
  color: var(--action-primary);
}
.requirements .ref {
  flex: none;
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: var(--font-xs);
  font-weight: 400;
}
.requirement-actions {
  display: inline-flex;
  gap: var(--space-2);
}
.dispatched-card {
  font-size: var(--font-xs);
  color: var(--text-muted);
}
.requirements .status {
  padding: 2px 8px;
  border: 1px solid var(--border-default);
  border-radius: 999px;
  color: var(--text-muted);
  font-size: var(--font-xs);
  font-weight: 600;
}
.empty-guidance {
  color: var(--text-muted);
  font-size: var(--font-xs);
}
.notice {
  margin: 0 0 16px;
  padding: 10px 12px;
  border-radius: var(--radius-sm);
  background: var(--surface-canvas);
  color: var(--text-secondary);
  font-size: 13px;
}
.notice.error {
  color: var(--status-error);
}
</style>
