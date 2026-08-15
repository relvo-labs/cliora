<script setup lang="ts">
/**
 * The acceptance surface for a decomposition proposal (RQ-10, FR-SPEC-005).
 *
 * This replaces a JSON textarea, and the three things it adds are the three the textarea
 * could not express:
 *
 * 1. **what each card is missing.** A card short of its readiness items is still
 *    selectable — it lands in the backlog, which is the design and not an error — but
 *    the count has to be visible before the click, not explained after it.
 * 2. **the difference between "remaining" and "rejected".** Partial acceptance leaves
 *    the rest *available*; a screen that renders both as "not accepted" makes people
 *    believe a decision was already made.
 * 3. **how many of these open a pull request.** Counted on its own line rather than
 *    folded into the total: one acceptance can produce six outward-facing branches, and
 *    that number is the one worth stopping on (`plan/22/README` §5.1).
 *
 * Epics and user stories render as **grouping headings and are not selectable**, because
 * accepting does not create them — `accept()` sets `epic_id` and `user_story_id` to
 * null. Showing a checkbox that does nothing would be worse than showing none.
 */
import { computed, ref } from "vue";

import {
  PROPOSAL_OVERRIDE_FIELDS,
  type ProposalGroupItem,
  type ProposalTaskItem,
  type TaskProposal,
} from "../../api/dto";

const props = defineProps<{
  proposal: TaskProposal;
  /** Readiness keys from the live process definition, never a constant here. */
  readinessKeys: string[];
  canDecide: boolean;
}>();

const emit = defineEmits<{
  accept: [
    payload: {
      acceptIds: string[];
      overrides: Record<string, Record<string, unknown>>;
    },
  ];
  reject: [note: string];
}>();

const selected = ref<string[]>([]);
const overrides = ref<Record<string, Record<string, unknown>>>({});
const expanded = ref<string | null>(null);
const rejectNote = ref("");
const rejecting = ref(false);

function list<T>(key: string): T[] {
  const value = (props.proposal.tree as Record<string, unknown>)[key];
  return Array.isArray(value) ? (value as T[]) : [];
}

const epics = computed(() => list<ProposalGroupItem>("epics"));
const stories = computed(() => list<ProposalGroupItem>("user_stories"));
const tasks = computed(() => list<ProposalTaskItem>("tasks"));

const acceptedIds = computed(() => new Set(props.proposal.accepted_item_ids));

/**
 * The tree flattened into headed groups, **including one for everything unfiled**.
 *
 * One list rather than nested `v-for`s with a fallback branch, because the fallback is
 * where an ungrouped card quietly loses half its row — its badges, its missing-readiness
 * note, its edit button. Monstrare's roadmap keeps an explicit "unclassified" bucket for
 * the same reason: a card must never look different because of how it was filed.
 */
interface Group {
  key: string;
  epic: string | null;
  story: string | null;
  tasks: ProposalTaskItem[];
}

const groups = computed<Group[]>(() => {
  const byStory = new Map<string | null, ProposalTaskItem[]>();
  for (const task of tasks.value) {
    const key = task.user_story_id ?? null;
    byStory.set(key, [...(byStory.get(key) ?? []), task]);
  }
  const named: Group[] = [];
  for (const epic of epics.value) {
    for (const story of stories.value.filter(
      (item) => (item.epic_id ?? null) === epic.id,
    )) {
      const items = byStory.get(story.id) ?? [];
      if (items.length) {
        named.push({
          key: `${epic.id}/${story.id}`,
          epic: epic.title ?? epic.id,
          story: story.title ?? story.id,
          tasks: items,
        });
      }
      byStory.delete(story.id);
    }
  }
  // Stories with no epic, then everything with no story at all.
  for (const story of stories.value.filter((item) => !item.epic_id)) {
    const items = byStory.get(story.id) ?? [];
    if (items.length) {
      named.push({
        key: story.id,
        epic: null,
        story: story.title ?? story.id,
        tasks: items,
      });
    }
    byStory.delete(story.id);
  }
  const orphans = [...byStory.values()].flat();
  if (orphans.length) {
    named.push({ key: "__unfiled__", epic: null, story: null, tasks: orphans });
  }
  return named;
});

function missingReadiness(task: ProposalTaskItem): string[] {
  const readiness = task.readiness ?? {};
  return props.readinessKeys.filter((key) => !readiness[key]);
}

function effective(task: ProposalTaskItem, field: string): unknown {
  return overrides.value[task.id]?.[field] ?? task[field];
}

function setOverride(taskId: string, field: string, value: string): void {
  const current = { ...(overrides.value[taskId] ?? {}) };
  if (value === "") {
    delete current[field];
  } else {
    current[field] = value;
  }
  if (Object.keys(current).length === 0) {
    const next = { ...overrides.value };
    delete next[taskId];
    overrides.value = next;
  } else {
    overrides.value = { ...overrides.value, [taskId]: current };
  }
}

const selectedTasks = computed(() =>
  tasks.value.filter((task) => selected.value.includes(task.id)),
);

const willOpenPullRequest = computed(
  () =>
    selectedTasks.value.filter(
      (task) => effective(task, "delivery") === "pull_request",
    ).length,
);

const willLandInBacklog = computed(
  () =>
    selectedTasks.value.filter((task) => missingReadiness(task).length > 0)
      .length,
);

const withDanglingDependency = computed(
  () =>
    selectedTasks.value.filter((task) =>
      (task.depends_on ?? []).some(
        (id) => !selected.value.includes(id) && !acceptedIds.value.has(id),
      ),
    ).length,
);

const editedCount = computed(() =>
  Object.values(overrides.value).reduce(
    (total, fields) => total + Object.keys(fields).length,
    0,
  ),
);

function submit(): void {
  emit("accept", {
    acceptIds: [...selected.value],
    // Only the overrides for items in this acceptance: the server refuses the rest, and
    // sending them would turn a deliberate refusal into a confusing one.
    overrides: Object.fromEntries(
      Object.entries(overrides.value).filter(([id]) =>
        selected.value.includes(id),
      ),
    ),
  });
}
</script>

<template>
  <section class="proposal-tree" data-proposal-tree>
    <p class="grouping-note muted">
      Epic 與 User Story 目前只用於分組，接受時不會建立成獨立項目。
    </p>

    <template v-for="group in groups" :key="group.key">
      <h3 v-if="group.epic" class="group epic">Epic · {{ group.epic }}</h3>
      <h4 v-if="group.story" class="group story">Story · {{ group.story }}</h4>
      <h4 v-else class="group story muted">（未分類任務）</h4>
      <ul class="cards">
        <li v-for="task in group.tasks" :key="task.id">
          <div class="row">
            <label class="pick">
              <input
                v-model="selected"
                type="checkbox"
                :value="task.id"
                :disabled="!canDecide || acceptedIds.has(task.id)"
                :data-item="task.id"
              />
              <span class="title">{{ task.title ?? task.id }}</span>
            </label>
            <span v-if="acceptedIds.has(task.id)" class="badge accepted"
              >已建立</span
            >
            <span class="badge delivery">{{
              effective(task, "delivery") ?? "—"
            }}</span>
            <span
              v-if="effective(task, 'risk') === 'high'"
              class="badge risk-high"
            >
              高風險
            </span>
            <span
              class="badge dor"
              :data-complete="missingReadiness(task).length === 0"
            >
              DoR {{ readinessKeys.length - missingReadiness(task).length }}/{{
                readinessKeys.length
              }}
            </span>
            <button
              v-if="canDecide && !acceptedIds.has(task.id)"
              class="ghost edit"
              :data-edit="task.id"
              @click="expanded = expanded === task.id ? null : task.id"
            >
              {{ expanded === task.id ? "收合" : "編輯" }}
            </button>
          </div>
          <p v-if="missingReadiness(task).length" class="missing">
            缺 {{ missingReadiness(task).join("、") }}
            ——接受後會建立在「待辦」，不是「就緒」。
          </p>
          <form v-if="expanded === task.id" class="edit-panel">
            <label v-for="field in PROPOSAL_OVERRIDE_FIELDS" :key="field">
              {{ field }}
              <input
                :value="overrides[task.id]?.[field] ?? ''"
                :data-override="`${task.id}.${field}`"
                :placeholder="String(task[field] ?? '')"
                @input="
                  setOverride(
                    task.id,
                    field,
                    ($event.target as HTMLInputElement).value,
                  )
                "
              />
            </label>
            <p class="muted">
              就緒條件由拆解填寫，這裡改不了。要補齊請先建立卡片再修改——那一步會留下紀錄。
            </p>
          </form>
        </li>
      </ul>
    </template>

    <footer v-if="canDecide" class="summary" data-proposal-summary>
      <p>將建立 {{ selected.length }} 張卡片</p>
      <p v-if="willOpenPullRequest" data-pr-count>
        其中 <strong>{{ willOpenPullRequest }}</strong> 張會開合併請求
      </p>
      <p v-if="willLandInBacklog">
        {{ willLandInBacklog }} 張會落在「待辦」（就緒條件缺項）
      </p>
      <p v-if="withDanglingDependency">
        {{ withDanglingDependency }} 張的相依指向沒被勾選的卡片，也會落「待辦」
      </p>
      <p v-if="editedCount" class="muted">你改了 {{ editedCount }} 個欄位</p>
      <div class="actions">
        <button
          class="primary"
          data-accept-proposal
          :disabled="selected.length === 0"
          @click="submit"
        >
          接受並建立
        </button>
        <button class="ghost" data-open-reject @click="rejecting = !rejecting">
          拒絕整份提案
        </button>
      </div>
      <form v-if="rejecting" class="reject">
        <label>
          理由
          <textarea v-model="rejectNote" data-reject-note />
        </label>
        <p class="muted">
          下次拆解時這段理由會進 Agent 的情境包，避免它再提一次同樣的東西。
        </p>
        <button
          class="danger"
          data-confirm-reject
          :disabled="rejectNote.trim().length === 0"
          @click.prevent="emit('reject', rejectNote)"
        >
          確認拒絕
        </button>
      </form>
    </footer>
  </section>
</template>

<style scoped>
.proposal-tree {
  display: grid;
  gap: var(--space-2);
}
.grouping-note {
  margin: 0;
  font-size: var(--font-sm);
}
.group {
  margin: var(--space-3) 0 0;
  font-size: var(--font-sm);
  color: var(--text-muted);
}
.group.story {
  margin-left: var(--space-3);
}
.cards {
  margin: 0;
  padding: 0 0 0 var(--space-4);
  list-style: none;
  display: grid;
  gap: var(--space-2);
}
.cards li {
  border-left: 2px solid var(--border-default);
  padding-left: var(--space-2);
}
.row,
.pick {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
.title {
  font-weight: 500;
}
.badge {
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  padding: 0 var(--space-1);
  font-size: var(--font-xs);
  color: var(--text-muted);
}
.badge.risk-high {
  border-color: var(--risk-high);
  color: var(--risk-high);
}
.badge.dor[data-complete="false"] {
  border-color: var(--risk-medium);
  color: var(--risk-medium);
}
.badge.accepted {
  border-color: var(--stage-done);
  color: var(--stage-done);
}
.missing {
  margin: 0 0 0 var(--space-4);
  font-size: var(--font-xs);
  color: var(--risk-medium);
}
.edit-panel,
.reject {
  display: grid;
  gap: var(--space-2);
  margin: var(--space-2) 0 0 var(--space-4);
  padding: var(--space-2);
  border: 1px dashed var(--border-default);
  border-radius: var(--radius-sm);
}
.summary {
  border-top: 1px solid var(--border-default);
  padding-top: var(--space-2);
  display: grid;
  gap: var(--space-1);
}
.summary p {
  margin: 0;
}
.actions {
  display: flex;
  gap: var(--space-2);
  margin-top: var(--space-2);
}
textarea {
  display: block;
  width: 100%;
  min-height: 4rem;
}
</style>
