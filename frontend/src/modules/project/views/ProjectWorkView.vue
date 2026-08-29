<script setup lang="ts">
/**
 * The Active Board and the Backlog, on the read model (PX-29…PX-36).
 *
 * **Four columns, and they are not hardcoded** (plan/26/06 §3.1). They are the result of
 * `group=lifecycle` over a filter that admits `ready`, `in_progress`, `review` and `done`
 * — so changing the grouping changes the layout without a second piece of layout code, and
 * `backlog` is absent because it has a view of its own.
 *
 * **Blocked work stays in its stage.** A `blocked` column loses a card's position in the
 * work; the card carries its attention instead (ADR 0040 §1).
 *
 * **Done shows a window, and says so.** "近 7 天 / 共 348" rather than a bare number,
 * because a Done column that grows forever is a column nobody scrolls and a Done count
 * that means "ever" answers a question nobody asked.
 *
 * Freshness is the shared counts poller (D95): twenty seconds, paused when the tab is
 * hidden, and the items are re-fetched only when a count actually moved.
 */
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import { ApiError } from "../../../api/client";
import type { WorkItemCard, WorkView } from "../../../api/dto";
import AsyncState from "../../../components/common/AsyncState.vue";
import UiButton from "../../../components/ui/UiButton.vue";
import { useToast } from "../../../components/ui/useToast";
import { api } from "../../../stores/auth";
import TaskDrawer from "../../task/TaskDrawer.vue";
import { useTaskDrawer } from "../../task/useTaskDrawer";
import BoardColumn from "../../work/components/BoardColumn.vue";
import BulkActionBar from "../../work/components/BulkActionBar.vue";
import MoveDialog from "../../work/components/MoveDialog.vue";
import ReadyTransitionDialog from "../../work/components/ReadyTransitionDialog.vue";
import WorkItemRow from "../../work/components/WorkItemRow.vue";
import WorkViewToolbar from "../../work/components/WorkViewToolbar.vue";
import { useOptimisticMove } from "../../work/composables/useOptimisticMove";
import { useWorkItems } from "../../work/composables/useWorkItems";
import { QUICK_FILTERS } from "../../work/quickFilters";
import {
  MAX_FILTER_URL_LENGTH,
  NO_VIEW,
  encodeFilter,
  isModified,
  readDensity,
  readFullScreen,
  readViewState,
  writeDensity,
  writeFullScreen,
  writeViewState,
  type Density,
} from "../../work/viewState";
import { useProjectContext } from "../useProjectContext";

const context = useProjectContext();
const { projectId, isArchived, can } = context;
const route = useRoute();
const router = useRouter();
const toast = useToast();

// --- the four lanes of the Active Board -----------------------------------------

const ACTIVE_LIFECYCLES = ["ready", "in_progress", "review", "done"] as const;
const LANE_LABELS: Record<string, string> = {
  ready: "就緒",
  in_progress: "進行中",
  review: "審查",
  done: "完成",
  backlog: "待辦",
  __none__: "未分類",
};

const layout = ref<"board" | "list">("board");
const density = ref<Density>(readDensity());
const fullScreen = ref(readFullScreen());
const views = ref<WorkView[]>([]);
const selected = ref<Set<string>>(new Set());
const busy = ref(false);
const moving = ref<WorkItemCard | null>(null);
const announcement = ref("");
const dragging = ref<WorkItemCard | null>(null);

// --- the Ready transition (PX-30, D97) -------------------------------------------
//
// **The process definition is loaded once and the card is fetched on demand.** Which
// readiness items a project has is a property of the project (a project may switch items
// off), and which of them a card is missing is a property of the card — and the card's
// answer is deliberately absent from the board's payload, because putting it there
// measured +20 % of the whole response for something one dialog needs about one card
// (`test_work_items_size`).
const readinessItems = ref<{ key: string; label: string }[]>([]);
const readyCandidate = ref<{ card: WorkItemCard; missing: string[] } | null>(
  null,
);
const readinessLabels = computed(() =>
  Object.fromEntries(
    readinessItems.value.map((item) => [item.key, item.label]),
  ),
);

/** Which of this project's readiness items the card has not ticked.
 *
 *  Read from `/api/tasks/{id}` rather than from the board card, and computed against the
 *  **project's** item list rather than a constant: a project that switched an item off
 *  must not be told it is missing it. */
async function missingReadinessFor(card: WorkItemCard): Promise<string[]> {
  const task = await api().getTask(card.id);
  const ticked = task.readiness ?? {};
  return readinessItems.value
    .map((item) => item.key)
    .filter((key) => !ticked[key]);
}

const state = computed(() =>
  readViewState(route.query as Record<string, unknown>),
);
/** The project's default shared view, or null.
 *
 *  **The project's, not the reader's.** `plan/26/06` §2 is explicit and the server agrees:
 *  `set_default` refuses a personal view, because the default is what somebody sees on
 *  their *first* visit here — a private view cannot be that.
 *
 *  **And only when its layout is the one on screen.** Every seeded view carries a layout,
 *  and the default one is `Active Work` (board). Applying it to the list layout would make
 *  the Backlog show the four active lanes — so a card somebody had just created in the
 *  Backlog would vanish as they typed it. The list's own default is the built-in
 *  `lifecycle = backlog` below. */
const defaultView = computed(
  () =>
    views.value.find(
      (view) =>
        view.is_default &&
        view.scope === "project" &&
        view.layout === layout.value,
    ) ?? null,
);
/** Which view the board is showing.
 *
 *  Falls back to the project's default when the URL names neither a view nor a filter —
 *  kintra's `BoardFilterCriteria.is_empty()`, ported as a rule (`plan/26/06` §2, exit
 *  condition "沒有 filter 時套用預設 view"). Without it the first screen is every card in
 *  the project unfiltered, which is the picture this phase exists to replace. */
const activeView = computed(() => {
  // `?view=all` is the reader saying "no view" — see `NO_VIEW`. Checked before the lookup
  // so the sentinel can never be mistaken for an id.
  if (state.value.view === NO_VIEW) return null;
  const named = views.value.find((view) => view.id === state.value.view);
  if (named) return named;
  return state.value.view === null && state.value.filter === null
    ? defaultView.value
    : null;
});
// **The toolbar is handed the resolved id, not the URL's.** A default view that is in
// effect but not named in the link still has to appear selected and still has to offer its
// own actions — showing "全部卡片" above a filtered board is the toolbar misdescribing what
// the reader is looking at.
/** Which chips the current filter corresponds to.
 *
 *  Derived from the filter rather than stored separately, so a shared URL shows the same
 *  chips lit that the person who sent it had lit. */
const activeChips = computed(() => {
  const encoded = state.value.filter ? encodeFilter(state.value.filter) : null;
  if (!encoded) return [];
  return QUICK_FILTERS.filter(
    (chip) => encoded === encodeFilter(chip.filter),
  ).map((chip) => chip.key);
});
/** Whether the board is showing something other than what the view saved.
 *
 *  **Only when there is an `f=` at all.** Without the first clause this reported *modified*
 *  for every selected view: `state.filter` is null when nothing was typed, the view's
 *  filter is not, and the comparison said they differ — so the toolbar offered "Revert"
 *  on a view nobody had touched, and the label meant nothing by the second time somebody
 *  saw it. Found by the browser run of the default-view exit condition, where the label
 *  appeared on a first visit to the board. */
const modified = computed(
  () =>
    state.value.filter !== null &&
    isModified(state.value.filter, (activeView.value?.filter ?? null) as never),
);
const filterNotInLink = computed(
  () =>
    Boolean(state.value.filter) &&
    encodeFilter(state.value.filter!).length > MAX_FILTER_URL_LENGTH,
);

/** The board's own default: the four active lanes, grouped by lifecycle.
 *
 *  Applied when the URL names neither a view nor a filter (kintra's
 *  `BoardFilterCriteria.is_empty()`, ported as a rule in plan/26/06 §2). Without it the
 *  first screen is every card in the project unfiltered — which is the picture this phase
 *  exists to replace. */
const effectiveFilter = computed(() => {
  if (state.value.filter) return state.value.filter;
  if (activeView.value)
    return activeView.value.filter as Record<string, unknown>;
  // **`?view=all` means all**, so the layout's built-in narrowing is skipped too —
  // otherwise "show me everything" would still hide the backlog on the board and the
  // active lanes in the list, which is not what the option says.
  if (state.value.view === NO_VIEW) return null;
  return layout.value === "list"
    ? { field: "lifecycle", op: "eq", value: "backlog" }
    : { field: "lifecycle", op: "in", value: [...ACTIVE_LIFECYCLES] };
});

const work = useWorkItems(() => ({
  projectId,
  // The **resolved** view, so the default one is applied server-side too. Sending the
  // URL's null while `effectiveFilter` used the default's filter would mean the counts and
  // the items were answering two different questions.
  view: activeView.value?.id ?? null,
  filter: effectiveFilter.value,
  search: state.value.search,
  group: state.value.group ?? (layout.value === "board" ? "lifecycle" : null),
  order: state.value.order ?? "rank:asc",
  limit: 50,
}));

const columns = computed(() => {
  const groups = work.page.value?.groups ?? [];
  if (layout.value === "list" || state.value.group !== null) {
    return groups.map((group) => ({
      ...group,
      label: LANE_LABELS[group.key] ?? group.key,
      windowNote: null as string | null,
    }));
  }
  // Board layout: the four lanes in order, including the empty ones. An absent column is
  // a column a card cannot be dragged into.
  return ACTIVE_LIFECYCLES.map((key) => {
    const group = groups.find((entry) => entry.key === key);
    return {
      key,
      label: LANE_LABELS[key],
      count: group?.count ?? 0,
      items: group?.items ?? [],
      next_cursor: group?.next_cursor ?? null,
      windowNote:
        key === "done" && group
          ? `近 7 天 · 共 ${group.count}`
          : (null as string | null),
    };
  });
});

const itemsByGroup = computed(() =>
  Object.fromEntries(columns.value.map((column) => [column.key, column.items])),
);
const rows = computed(() =>
  (work.page.value?.groups ?? []).flatMap((group) => group.items),
);

// --- the mutation, one path for both entrances ----------------------------------

const move = useOptimisticMove(() => {
  work.invalidate();
  void work.load();
});

const LIFECYCLE_TO_STAGE: Record<string, string> = {
  ready: "ready",
  in_progress: "implementing",
  review: "verify",
  done: "done",
  backlog: "backlog",
};

async function performMove(payload: {
  card: WorkItemCard;
  previous: WorkItemCard | null;
  next: WorkItemCard | null;
  groupKey: string;
}): Promise<void> {
  moving.value = null;
  // **The grouping has to *be* lifecycle, not merely be unset.** The first version
  // checked `group === null`, which meant that choosing "group by 階段" explicitly — the
  // same grouping the board already had — silently stopped a cross-column move from
  // changing the stage. The card moved on screen and came back on the next poll. Caught
  // by the browser evidence run, not by a unit test, because both halves were individually
  // correct.
  const grouping = state.value.group ?? "lifecycle";
  const crossing =
    grouping === "lifecycle" &&
    layout.value === "board" &&
    payload.card.lifecycle !== payload.groupKey;
  // Announced **before** as well as after: a screen-reader user needs to know what is
  // about to happen and then whether it did (plan/26/06 §3.4).
  announcement.value = `正在移動 ${payload.card.card_ref}`;
  const outcome = await move.move({
    card: payload.card,
    previous: payload.previous,
    next: payload.next,
    lifecycleStage: crossing ? LIFECYCLE_TO_STAGE[payload.groupKey] : null,
  });
  announcement.value = outcome.announcement;
  toast.push(
    outcome.ok
      ? { kind: "success", title: "卡片已移動" }
      : {
          kind: "error",
          title: "卡片沒有移動",
          message: outcome.reason ?? undefined,
        },
  );
}

function onDrop(groupKey: string): void {
  const card = dragging.value;
  dragging.value = null;
  if (!card) return;
  const target = itemsByGroup.value[groupKey] ?? [];
  const last = target.filter((item) => item.id !== card.id).at(-1) ?? null;
  // Dropped on the column rather than between two cards: the bottom. Named by its
  // neighbour, not by an index.
  void performMove({ card, previous: last, next: null, groupKey });
}

// --- selection and bulk ---------------------------------------------------------

function toggle(taskId: string): void {
  const next = new Set(selected.value);
  if (next.has(taskId)) next.delete(taskId);
  else next.add(taskId);
  selected.value = next;
}

/** Inline create, in the Backlog (PX-30).
 *
 *  One field and Enter. The Backlog is where work arrives, and a dialog between "I
 *  thought of something" and "it is written down" is where the thought goes instead —
 *  the same argument requirement intake makes for its single field (D28).
 */
const newTitle = ref("");

async function createCard(): Promise<void> {
  const title = newTitle.value.trim();
  if (!title) return;
  busy.value = true;
  try {
    await api().createTask(projectId, { title });
    newTitle.value = "";
    work.invalidate();
    await work.load();
    await work.refreshCounts();
  } catch (error) {
    toast.push({
      kind: "error",
      title: "建立失敗",
      message: error instanceof ApiError ? error.message : undefined,
    });
  } finally {
    busy.value = false;
  }
}

async function bulk(patch: Record<string, unknown>): Promise<void> {
  busy.value = true;
  try {
    const result = await api().bulkUpdateTasks({
      task_ids: [...selected.value],
      patch,
    });
    selected.value = new Set();
    work.invalidate();
    await work.load();
    toast.push({ kind: "success", title: `已更新 ${result.updated} 張` });
  } catch (error) {
    toast.push({
      kind: "error",
      title: "批次修改未執行",
      // All-or-nothing, so naming the reason is the whole recovery: nothing changed.
      message: error instanceof ApiError ? error.message : undefined,
    });
  } finally {
    busy.value = false;
  }
}

// --- URL writes -----------------------------------------------------------------

async function patchQuery(
  next: Parameters<typeof writeViewState>[0],
): Promise<void> {
  await router.replace({
    query: writeViewState(next, route.query as Record<string, unknown>),
  });
}

/** Move a card into Ready, asking first when the Definition of Ready is not met.
 *
 *  **The dialog is a warning, not a gate** — the server writes either way. So this asks,
 *  and if there is nothing missing it does not: a confirmation nobody needs is a
 *  confirmation everybody learns to dismiss. */
async function requestReady(card: WorkItemCard): Promise<void> {
  let missing: string[] = [];
  try {
    missing = await missingReadinessFor(card);
  } catch {
    // The card could not be read. Move anyway rather than blocking on a check that is
    // advisory in the first place — the server still returns the warnings.
    missing = [];
  }
  if (missing.length === 0) {
    await moveToReady(card);
    return;
  }
  readyCandidate.value = { card, missing };
}

async function moveToReady(card: WorkItemCard): Promise<void> {
  busy.value = true;
  try {
    await api().updateTask(card.id, { stage: "ready", version: card.version });
    work.invalidate();
    await work.load();
    await work.refreshCounts();
  } catch (error) {
    toast.push({
      kind: "error",
      title: `${card.card_ref} 沒有移動`,
      message: error instanceof ApiError ? error.message : undefined,
    });
  } finally {
    busy.value = false;
    readyCandidate.value = null;
  }
}

/** "Fill it in" — close the dialog and open the card on the field that fills the item.
 *
 *  The readiness *key* travels, not the label: the Drawer maps keys to its own fields, and
 *  a label is for reading. */
function fillReadiness(readinessKey: string): void {
  const card = readyCandidate.value?.card;
  readyCandidate.value = null;
  if (card) drawer.open(card.id, readinessKey);
}

async function renameCard(payload: {
  card: WorkItemCard;
  title: string;
}): Promise<void> {
  try {
    await api().updateTask(payload.card.id, {
      title: payload.title,
      version: payload.card.version,
    });
    work.invalidate();
    await work.load();
  } catch (error) {
    // The row has already reverted to the stored title, because it renders `card.title`
    // and nothing was written. So the toast is the whole recovery: a 409 here means
    // somebody else edited the card, and re-typing over their change is not the fix.
    toast.push({
      kind: "error",
      title: `${payload.card.card_ref} 沒有改名`,
      message: error instanceof ApiError ? error.message : undefined,
    });
  }
}

function toggleChip(key: string): void {
  const chip = QUICK_FILTERS.find((entry) => entry.key === key);
  if (!chip) return;
  // **The URL, never the view** (D103). The toolbar then says "modified" and offers Save
  // as / Revert; a chip that rewrote a shared view would change what a whole team sees.
  const already = activeChips.value.includes(key);
  void patchQuery({ filter: already ? null : chip.filter });
}

async function saveAs(): Promise<void> {
  const name = window.prompt("新檢視的名稱");
  if (!name) return;
  const created = await api().createWorkView(projectId, {
    name,
    layout: layout.value,
    scope: "personal",
    filter: effectiveFilter.value,
    group_by: state.value.group,
    order_by: state.value.order
      ? [
          {
            field: state.value.order.split(":")[0],
            direction: state.value.order.split(":")[1] ?? "asc",
          },
        ]
      : [],
  });
  views.value = await api().listWorkViews(projectId);
  await patchQuery({ view: created.id, filter: null });
}

// --- managing a saved view (PX-33) ----------------------------------------------
//
// Four actions, and two of them are asymmetric on purpose.
//
// **Delete confirms; default does not.** Setting a default is one click to undo — pick
// another view and set that. Deleting a shared view takes away something other people
// were using and there is no undo, so it asks, and it says which one.
//
// **A duplicate is always personal**, whatever it was copied from. Copying a shared view
// to experiment with is the common case, and a copy that landed shared would mean an
// experiment appearing in everybody's list.

async function refreshViews(): Promise<void> {
  views.value = await api()
    .listWorkViews(projectId)
    .catch(() => []);
}

async function withViewError(action: () => Promise<void>): Promise<void> {
  try {
    await action();
  } catch (error) {
    toast.push({
      kind: "error",
      title: "檢視未變更",
      // `VIEW_NOT_OWNED` and `VIEW_DEFAULT_CONFLICT` both arrive here, and both name
      // something the person can act on.
      message: error instanceof ApiError ? error.message : undefined,
    });
  }
}

function setDefaultView(viewId: string): void {
  void withViewError(async () => {
    await api().updateWorkView(viewId, { is_default: true });
    await refreshViews();
  });
}

function renameView(viewId: string): void {
  const current = views.value.find((view) => view.id === viewId);
  const name = window.prompt("新的名稱", current?.name ?? "");
  if (!name || name === current?.name) return;
  void withViewError(async () => {
    await api().updateWorkView(viewId, { name });
    await refreshViews();
  });
}

function duplicateView(viewId: string): void {
  const current = views.value.find((view) => view.id === viewId);
  const name = window.prompt("副本的名稱", `${current?.name ?? "檢視"} 副本`);
  if (!name) return;
  void withViewError(async () => {
    const copy = await api().duplicateWorkView(viewId, name);
    await refreshViews();
    await patchQuery({ view: copy.id, filter: null });
  });
}

function deleteView(viewId: string): void {
  const current = views.value.find((view) => view.id === viewId);
  const shared = current?.scope === "project";
  const confirmed = window.confirm(
    shared
      ? `「${current?.name}」是共用檢視，刪除之後所有人都看不到它。要刪除嗎？`
      : `要刪除「${current?.name ?? "這個檢視"}」嗎？`,
  );
  if (!confirmed) return;
  void withViewError(async () => {
    await api().deleteWorkView(viewId);
    await refreshViews();
    // Back to the unfiltered board rather than to another view: picking one for somebody
    // would be guessing, and `?view=` pointing at a deleted row is a 404 on next load.
    await patchQuery({ view: null, filter: null });
  });
}

const drawer = useTaskDrawer();
/** The read model's card for whatever the Drawer has open.
 *
 *  Handed down rather than refetched: the Drawer needs `primary_attention` to decide
 *  whether the conversation takes the focus, and whether an execution setting is the
 *  reason the card is stuck. Both are answers `derive_attention` already gave on this
 *  page, and asking again would be a second answer. */
const drawerCard = computed(
  () =>
    rows.value
      .concat(columns.value.flatMap((column) => column.items))
      .find((card) => card.id === drawer.taskId.value) ?? null,
);

let release: (() => void) | null = null;

onMounted(async () => {
  await refreshViews();
  // The project's own readiness items, once. A constant list here would tell a project
  // that switched an item off that it is missing it.
  readinessItems.value = await api()
    .getProcess(projectId)
    .then((process) =>
      process.readiness.map(({ key, label }) => ({ key, label })),
    )
    .catch(() => []);
  await work.load();
  await work.refreshCounts();
  release = work.subscribeToPolling();
});

onUnmounted(() => {
  release?.();
  release = null;
});

watch(
  [
    // `activeView`, not `state.view`: the saved views arrive after mount, so the default
    // resolves *after* the first load. Watching the URL alone would leave the first screen
    // unfiltered until something else changed.
    () => activeView.value?.id ?? null,
    () => state.value.filter,
    () => state.value.search,
    () => state.value.group,
    () => state.value.order,
    layout,
  ],
  async () => {
    work.invalidate();
    await work.load();
  },
);

watch(density, (value) => writeDensity(value));
watch(fullScreen, (value) => writeFullScreen(value));
</script>

<template>
  <section class="tab-panel work-panel" :data-full-screen="fullScreen">
    <WorkViewToolbar
      :views="views"
      :active-view="activeView?.id ?? null"
      :modified="modified"
      :active-chips="activeChips"
      :search="state.search"
      :filter="state.filter"
      :group="state.group"
      :order="state.order"
      :density="density"
      :layout="layout"
      :runtime-available="work.runtimeAvailable.value"
      :filter-not-in-link="filterNotInLink"
      :can-manage-views="can.createTasks.value"
      :full-screen="fullScreen"
      @select-view="patchQuery({ view: $event ?? NO_VIEW, filter: null })"
      @toggle-chip="toggleChip"
      @set-search="patchQuery({ search: $event })"
      @set-filter="patchQuery({ filter: $event })"
      @set-default="setDefaultView"
      @rename-view="renameView"
      @duplicate-view="duplicateView"
      @delete-view="deleteView"
      @set-group="patchQuery({ group: $event })"
      @set-order="patchQuery({ order: $event })"
      @set-density="density = $event"
      @set-layout="layout = $event"
      @save-as="saveAs"
      @revert="patchQuery({ filter: null })"
      @toggle-full-screen="fullScreen = !fullScreen"
    />

    <BulkActionBar
      :count="selected.size"
      :busy="busy"
      @set-stage="bulk({ stage: $event })"
      @set-risk="bulk({ risk: $event })"
      @clear="selected = new Set()"
    />

    <!-- Both directions of a move are announced here (plan/26/06 §3.4). -->
    <p class="sr-only" aria-live="polite" data-announcement>
      {{ announcement }}
    </p>

    <TaskDrawer
      :project-id="projectId"
      :task-id="drawer.taskId.value"
      :card-ref="drawerCard?.card_ref ?? null"
      :card="drawerCard"
      :focus-readiness="drawer.focus.value"
      @close="drawer.close"
      @focused="drawer.clearFocus"
      @changed="
        work.invalidate();
        work.load();
      "
    />

    <AsyncState v-if="work.error.value" state="error">
      無法載入卡片。
      <UiButton size="sm" variant="ghost" @click="work.load()">重試</UiButton>
    </AsyncState>

    <!-- `tabindex="0"` because this scrolls horizontally and its children are cards, not
         focus stops in reading order: a keyboard user who cannot focus the container
         cannot scroll to the fourth lane at all. WCAG 2.1.1, and axe reports it as
         `scrollable-region-focusable`. The `role`/`aria-label` pair is what stops that
         tab stop from being an unnamed one — landing on "group" tells a screen-reader
         user nothing about where they are. -->
    <div
      v-else-if="layout === 'board'"
      class="lanes"
      tabindex="0"
      role="group"
      aria-label="工作看板，四個階段"
    >
      <BoardColumn
        v-for="column in columns"
        :key="column.key"
        :label="column.label"
        :group-key="column.key"
        :count="column.count"
        :items="column.items"
        :has-more="Boolean(column.next_cursor)"
        :density="density"
        :can-write="can.writeTasks.value && !isArchived"
        :window-note="column.windowNote"
        :pending="move.pending.value"
        @open="drawer.open"
        @load-more="work.loadMore"
        @drag-start="dragging = $event"
        @drop="onDrop"
        @move="moving = $event"
      />
    </div>

    <div
      v-else-if="layout === 'list' && can.createTasks.value && !isArchived"
      class="inline-create"
    >
      <input
        v-model="newTitle"
        placeholder="新卡片的標題，按 Enter 建立"
        data-new-card
        @keyup.enter="createCard"
      />
      <UiButton
        size="sm"
        variant="primary"
        :disabled="!newTitle.trim() || busy"
        data-create-card
        @click="createCard"
      >
        建立
      </UiButton>
    </div>
    <ul v-if="layout === 'list'" class="rows">
      <WorkItemRow
        v-for="card in rows"
        :key="card.id"
        :card="card"
        :selected="selected.has(card.id)"
        :can-write="can.writeTasks.value && !isArchived"
        @open="drawer.open"
        @toggle="toggle"
        @move="moving = $event"
        @rename="renameCard"
        @ready="requestReady"
      />
    </ul>

    <ReadyTransitionDialog
      :card-ref="readyCandidate?.card.card_ref ?? null"
      :missing="readyCandidate?.missing ?? []"
      :labels="readinessLabels"
      :busy="busy"
      @close="readyCandidate = null"
      @proceed="readyCandidate && moveToReady(readyCandidate.card)"
      @fill="fillReadiness"
    />

    <MoveDialog
      :card="moving"
      :groups="
        columns.map((column) => ({ key: column.key, label: column.label }))
      "
      :items-by-group="itemsByGroup"
      @close="moving = null"
      @confirm="performMove"
    />
  </section>
</template>

<style scoped>
.inline-create {
  display: flex;
  gap: var(--space-2);
  margin-bottom: var(--space-3);
}
.inline-create input {
  flex: 1;
  max-width: 420px;
  padding: 6px 8px;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  background: var(--surface-elevated);
  color: var(--text-primary);
  font-size: var(--font-sm);
}
.work-panel {
  display: block;
}
/* Full screen is a page state rather than a layout: the toolbar and the columns are the
 * same components, given the whole viewport (PX-36). */
.work-panel[data-full-screen="true"] {
  position: fixed;
  inset: 0;
  z-index: 30;
  overflow: auto;
  padding: var(--space-4);
  background: var(--surface-canvas);
}
.lanes {
  display: grid;
  grid-auto-flow: column;
  grid-auto-columns: minmax(260px, 1fr);
  gap: var(--space-3);
  padding: 1px 1px var(--space-2);
  overflow-x: auto;
  scrollbar-width: thin;
}
/* The tab stop added for WCAG 2.1.1 has to be **visible** when it is reached. A
   focusable element with `outline: none` is worse than an unfocusable one: the keyboard
   user is now somewhere, and nothing on screen says where. */
.lanes:focus-visible {
  outline: 2px solid var(--border-focus);
  outline-offset: 2px;
}
.rows {
  list-style: none;
  margin: 0;
  padding: 0;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  background: var(--surface-elevated);
}
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip-path: inset(50%);
  white-space: nowrap;
}
</style>
