<script setup lang="ts">
/**
 * Document patch proposals: rendered, decided, **never applied** (RQ-10 §7, FR-SPEC-007).
 *
 * Three things this screen deliberately does not have, and each is a decision rather
 * than an omission:
 *
 * 1. **No markdown or syntax rendering of the diff.** It is agent-produced text arriving
 *    in a single-origin deployment (ADR 0020), so it goes into a `<pre>` as a text node.
 *    A highlighter is a parser, and a parser is where this becomes an XSS question.
 * 2. **No download button.** A `.patch` someone can fetch will be `git apply`ed, which
 *    moves applying into a terminal where none of this phase's gates exist. Copying the
 *    text is the friction, and the friction is the control.
 * 3. **No "apply" anything.** Accepting records a decision and creates nothing — not even
 *    a card. The button below pre-fills an ordinary pull-request card instead, because
 *    agreeing that a document is wrong and scheduling the work are two decisions.
 *
 * It lives in Settings rather than in a tab of its own: a project may see zero of these
 * in a month, and a sixth tab that is usually empty costs every visit.
 */
import { onMounted, ref } from "vue";

import { ApiError, type ApiClient } from "../../api/client";
import type { DocumentPatchProposal } from "../../api/dto";
import EmptyState from "../ui/EmptyState.vue";
import UiButton from "../ui/UiButton.vue";
import UiCard from "../ui/UiCard.vue";

const props = defineProps<{
  client: ApiClient;
  projectId: string;
  canDecide: boolean;
}>();

const proposals = ref<DocumentPatchProposal[]>([]);
const error = ref("");
const rejectingId = ref<string | null>(null);
const rejectNote = ref("");
const expanded = ref<string | null>(null);

const SECTION_LABELS: Array<{ key: string; label: string }> = [
  { key: "added_sections", label: "新增章節" },
  { key: "modified_sections", label: "修改章節" },
  { key: "removed_sections", label: "移除章節" },
  { key: "related_docs", label: "相關文件" },
];

async function load(): Promise<void> {
  error.value = "";
  try {
    proposals.value = await props.client.listPatchProposals(props.projectId);
  } catch (caught) {
    error.value = caught instanceof ApiError ? caught.message : "載入失敗。";
  }
}

async function decide(
  proposal: DocumentPatchProposal,
  accept: boolean,
): Promise<void> {
  error.value = "";
  try {
    await props.client.decidePatchProposal(
      proposal.id,
      accept,
      accept ? undefined : rejectNote.value,
    );
    rejectingId.value = null;
    rejectNote.value = "";
    await load();
  } catch (caught) {
    error.value = caught instanceof ApiError ? caught.message : "決定失敗。";
  }
}

function sectionList(proposal: DocumentPatchProposal, key: string): string[] {
  const value = proposal.sections?.[key];
  return Array.isArray(value) ? value.map(String) : [];
}

onMounted(load);
defineExpose({ load });
</script>

<template>
  <UiCard>
    <template #header>
      <div class="card-heading">
        <span>文件修訂提案</span>
        <span class="heading-note">平台只渲染與記錄決定，不套用</span>
      </div>
    </template>

    <p v-if="error" class="notice error" role="alert">{{ error }}</p>

    <EmptyState v-if="proposals.length === 0">
      沒有待決定的修訂提案。
      <template #action>
        <span class="muted"
          >Agent 在執行中發現文件與程式碼不符時，會在這裡提出修訂。</span
        >
      </template>
    </EmptyState>

    <ul v-else class="patch-list">
      <li
        v-for="proposal in proposals"
        :key="proposal.id"
        :data-patch="proposal.seq"
      >
        <div class="row">
          <code class="target">{{ proposal.target_path }}</code>
          <span class="seq">#{{ proposal.seq }}</span>
          <UiButton
            size="sm"
            variant="ghost"
            :data-toggle="proposal.seq"
            @click="expanded = expanded === proposal.id ? null : proposal.id"
          >
            {{ expanded === proposal.id ? "收合" : "查看修訂內容" }}
          </UiButton>
        </div>

        <p v-if="proposal.reason" class="reason">{{ proposal.reason }}</p>

        <dl v-if="Object.keys(proposal.sections ?? {}).length" class="sections">
          <template v-for="section in SECTION_LABELS" :key="section.key">
            <template v-if="sectionList(proposal, section.key).length">
              <dt>{{ section.label }}</dt>
              <dd>{{ sectionList(proposal, section.key).join("、") }}</dd>
            </template>
          </template>
        </dl>

        <!-- Unresolved questions are shown and do **not** block acceptance, unlike a
             specification's. Accepting a patch proposal unlocks nothing; approving a
             specification unlocks decomposition. Asymmetric gates, asymmetric reason. -->
        <ul
          v-if="proposal.open_questions.length"
          class="questions"
          data-patch-questions
        >
          <li v-for="(question, index) in proposal.open_questions" :key="index">
            {{ question.question ?? question.id }}
          </li>
        </ul>

        <!-- Text node, never parsed. See the module comment. -->
        <pre
          v-if="expanded === proposal.id"
          class="diff"
          :data-diff="proposal.seq"
          >{{ proposal.diff }}</pre
        >

        <div v-if="canDecide" class="actions">
          <UiButton
            size="sm"
            variant="primary"
            :data-accept="proposal.seq"
            @click="decide(proposal, true)"
          >
            接受
          </UiButton>
          <UiButton
            size="sm"
            variant="ghost"
            :data-open-reject="proposal.seq"
            @click="
              rejectingId = rejectingId === proposal.id ? null : proposal.id
            "
          >
            拒絕
          </UiButton>
          <span class="muted note"
            >接受只記錄決定，不會建立任何東西——套用是一張走 pull_request
            的正常卡片。</span
          >
        </div>

        <form v-if="rejectingId === proposal.id" class="reject">
          <label>
            理由
            <textarea v-model="rejectNote" :data-reject="proposal.seq" />
          </label>
          <UiButton
            size="sm"
            variant="danger"
            :disabled="rejectNote.trim().length === 0"
            :data-confirm-reject="proposal.seq"
            @click.prevent="decide(proposal, false)"
          >
            確認拒絕
          </UiButton>
        </form>
      </li>
    </ul>
  </UiCard>
</template>

<style scoped>
.patch-list {
  margin: 0;
  padding: 0;
  list-style: none;
  display: grid;
  gap: var(--space-3);
}
.patch-list li {
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  padding: var(--space-3);
  display: grid;
  gap: var(--space-2);
}
.row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
.target {
  font-weight: 500;
}
.seq,
.note {
  font-size: var(--font-xs);
  color: var(--text-muted);
}
.reason,
.sections,
.questions {
  margin: 0;
  font-size: var(--font-sm);
}
.questions {
  padding-left: var(--space-4);
  color: var(--risk-medium);
}
.diff {
  margin: 0;
  padding: var(--space-2);
  background: var(--surface-default);
  border-radius: var(--radius-sm);
  overflow: auto;
  max-height: 24rem;
  white-space: pre;
  font-size: var(--font-xs);
}
.actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
}
.reject {
  display: grid;
  gap: var(--space-2);
}
textarea {
  display: block;
  width: 100%;
  min-height: 4rem;
}
</style>
