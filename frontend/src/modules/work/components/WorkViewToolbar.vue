<script setup lang="ts">
/**
 * The board's one row of controls (PX-31/PX-32/PX-33, plan/26/06 §2).
 *
 * Five things here are decisions rather than layout:
 *
 * **Search is its own control, beside Filter rather than inside it.** The server treats it
 * the same way and `search_clause` says why: fifteen validated fields plus one
 * unconstrained one is not an allowlist. It is **debounced, not submitted** — a board that
 * needs Enter is a board people stop searching.
 *
 * **The filter builder writes the same `f=` a chip writes.** A chip is a saved row of the
 * builder, not a different mechanism, so "clear the filter" has one meaning and a chip
 * lights up when the builder happens to have built its filter.
 *
 * **A quick filter writes the URL and never the view** (D103). Chips that quietly rewrote
 * a shared view would mean one person's scan changes what the whole team sees, with no
 * undo. So the toolbar says *modified* and offers Save as / Revert instead.
 *
 * **The two runtime chips are disabled with a reason, not answered with zero.** `Blocked`
 * and `No runner` map onto attention's two non-database levels; when the registry cannot
 * be consulted, "0 cards" is a false statement that reads as *fixed* (ADR 0040 §2).
 *
 * **Attention can be grouped and not sorted.** Two of its eight levels are not in SQL, so
 * an ordering would be mostly right — which is harder to debug than none (D92).
 */
import { computed, ref, watch } from "vue";

import UiButton from "../../../components/ui/UiButton.vue";
import {
  BUILDER_FIELDS,
  OP_LABELS,
  type BuilderRow,
  buildFilter,
  readBuilder,
} from "../filterBuilder";
import { QUICK_FILTERS, RUNTIME_UNAVAILABLE } from "../quickFilters";
import { MAX_SEARCH_LENGTH, type Density } from "../viewState";

const props = withDefaults(
  defineProps<{
    views: { id: string; name: string; scope: string; is_default: boolean }[];
    activeView: string | null;
    /** True when the current filter differs from the saved view's. */
    modified: boolean;
    activeChips: string[];
    search: string | null;
    filter: Record<string, unknown> | null;
    group: string | null;
    order: string | null;
    density: Density;
    layout: "board" | "list";
    runtimeAvailable?: boolean;
    /** Set when the filter was too long for the URL (D103). */
    filterNotInLink?: boolean;
    canManageViews?: boolean;
    fullScreen?: boolean;
  }>(),
  {
    runtimeAvailable: true,
    filterNotInLink: false,
    canManageViews: false,
    fullScreen: false,
  },
);
const emit = defineEmits<{
  (event: "select-view", viewId: string | null): void;
  (event: "toggle-chip", key: string): void;
  (event: "set-search", search: string | null): void;
  (event: "set-filter", filter: Record<string, unknown> | null): void;
  (event: "set-default", viewId: string): void;
  (event: "duplicate-view", viewId: string): void;
  (event: "delete-view", viewId: string): void;
  (event: "rename-view", viewId: string): void;
  (event: "set-group", group: string | null): void;
  (event: "set-order", order: string | null): void;
  (event: "set-density", density: Density): void;
  (event: "set-layout", layout: "board" | "list"): void;
  (event: "save-as"): void;
  (event: "revert"): void;
  (event: "toggle-full-screen"): void;
}>();

const GROUPS = [
  { value: "lifecycle", label: "階段" },
  { value: "owner", label: "負責人" },
  { value: "epic", label: "Epic" },
  { value: "risk", label: "風險" },
  { value: "requirement", label: "需求" },
  { value: "execution_status", label: "執行狀態" },
  { value: "attention", label: "注意力" },
  { value: "blocking_reason", label: "阻塞原因" },
];

// Seven fields, and **`attention` is not among them** (D92).
const ORDERS = [
  { value: "rank:asc", label: "手動排序" },
  { value: "updated_at:desc", label: "最近更新" },
  { value: "created_at:desc", label: "最近建立" },
  { value: "priority:desc", label: "優先級" },
  { value: "risk:desc", label: "風險" },
  { value: "title:asc", label: "標題" },
  { value: "card_ref:asc", label: "卡號" },
];

const activeViewName = computed(
  () =>
    props.views.find((view) => view.id === props.activeView)?.name ??
    "全部卡片",
);

function chipDisabled(needsRuntime: boolean | undefined): boolean {
  return Boolean(needsRuntime) && !props.runtimeAvailable;
}

// --- search -----------------------------------------------------------------------
//
// Debounced rather than submitted. 250ms is the number kintra settled on: short enough
// that it feels like the list is following the typing, long enough that a five-letter
// word is one request rather than five.
const SEARCH_DEBOUNCE_MS = 250;
const draft = ref(props.search ?? "");
let timer: ReturnType<typeof setTimeout> | null = null;

// The prop leads when it changes from outside — a shared link opened, Revert pressed,
// the browser's Back button. Without this the box keeps whatever was last typed and
// disagrees with the board it sits above.
watch(
  () => props.search,
  (value) => {
    if ((value ?? "") !== draft.value.trim()) draft.value = value ?? "";
  },
);

function onSearchInput(value: string): void {
  draft.value = value;
  if (timer) clearTimeout(timer);
  timer = setTimeout(() => {
    timer = null;
    emit("set-search", draft.value.trim() || null);
  }, SEARCH_DEBOUNCE_MS);
}

function commitSearch(): void {
  // Enter and blur both skip the wait. Not *instead* of the debounce — somebody who
  // presses Enter has finished typing and should not wait another quarter second.
  if (timer) clearTimeout(timer);
  timer = null;
  emit("set-search", draft.value.trim() || null);
}

function clearSearch(): void {
  draft.value = "";
  commitSearch();
}

// --- the filter builder -----------------------------------------------------------
const builderOpen = ref(false);
const builder = ref<BuilderRow[]>([]);
const representable = ref(true);

watch(
  () => props.filter,
  (value) => {
    const read = readBuilder(value ?? null);
    builder.value = read.rows;
    representable.value = read.representable;
  },
  { immediate: true },
);

function fieldSpec(field: string) {
  return (
    BUILDER_FIELDS.find((entry) => entry.field === field) ?? BUILDER_FIELDS[0]
  );
}

function addRow(): void {
  builder.value = [
    ...builder.value,
    { field: BUILDER_FIELDS[0].field, op: "eq", values: [] },
  ];
}

function removeRow(index: number): void {
  builder.value = builder.value.filter((_row, position) => position !== index);
  applyBuilder();
}

function setRowField(index: number, field: string): void {
  // The values go with the field. Keeping them would leave `risk = ready` on screen,
  // which the server refuses — a dropdown must not be able to build a 400.
  builder.value = builder.value.map((row, position) =>
    position === index ? { field, op: "eq", values: [] } : row,
  );
  applyBuilder();
}

function setRowOp(index: number, op: BuilderRow["op"]): void {
  builder.value = builder.value.map((row, position) =>
    position === index
      ? {
          ...row,
          op,
          values:
            op === "eq" || op === "neq" ? row.values.slice(0, 1) : row.values,
        }
      : row,
  );
  applyBuilder();
}

function toggleRowValue(index: number, value: string): void {
  builder.value = builder.value.map((row, position) => {
    if (position !== index) return row;
    const single = row.op === "eq" || row.op === "neq";
    if (single)
      return { ...row, values: row.values[0] === value ? [] : [value] };
    return {
      ...row,
      values: row.values.includes(value)
        ? row.values.filter((entry) => entry !== value)
        : [...row.values, value],
    };
  });
  applyBuilder();
}

function applyBuilder(): void {
  emit("set-filter", buildFilter(builder.value));
}

function clearFilter(): void {
  builder.value = [];
  emit("set-filter", null);
}

const activeViewIsShared = computed(
  () =>
    props.views.find((view) => view.id === props.activeView)?.scope ===
    "project",
);
const activeViewIsDefault = computed(
  () =>
    props.views.find((view) => view.id === props.activeView)?.is_default ===
    true,
);
</script>

<template>
  <div class="toolbar">
    <div class="row">
      <label class="control">
        <span class="control-label">檢視</span>
        <select
          data-view-selector
          :value="activeView ?? ''"
          @change="
            emit(
              'select-view',
              ($event.target as HTMLSelectElement).value || null,
            )
          "
        >
          <option value="">全部卡片</option>
          <option v-for="view in views" :key="view.id" :value="view.id">
            {{ view.name }}{{ view.scope === "project" ? "（共用）" : ""
            }}{{ view.is_default ? "（預設）" : "" }}
          </option>
        </select>
      </label>

      <!-- **Said, not only marked with a suffix.** A shared view is the one control on
           this page whose edits change what other people see, and the option text is
           inside a closed `<select>` most of the time. -->
      <span v-if="activeViewIsShared" class="shared-note" data-shared-view-note
        >這是共用檢視，修改會影響所有人</span
      >

      <label class="control search">
        <span class="control-label">搜尋</span>
        <input
          type="search"
          data-search-input
          :value="draft"
          :maxlength="MAX_SEARCH_LENGTH"
          placeholder="標題或卡號"
          @input="onSearchInput(($event.target as HTMLInputElement).value)"
          @keydown.enter.prevent="commitSearch"
          @blur="commitSearch"
        />
      </label>
      <button
        v-if="draft"
        type="button"
        class="ghost"
        data-clear-search
        @click="clearSearch"
      >
        清除搜尋
      </button>

      <button
        type="button"
        class="ghost"
        :aria-expanded="builderOpen"
        data-toggle-filter-builder
        @click="builderOpen = !builderOpen"
      >
        篩選{{ builder.length ? `（${builder.length}）` : "" }}
      </button>

      <div class="segmented" role="group" aria-label="版面">
        <button
          type="button"
          :data-active="layout === 'board'"
          data-layout-board
          @click="emit('set-layout', 'board')"
        >
          看板
        </button>
        <button
          type="button"
          :data-active="layout === 'list'"
          data-layout-list
          @click="emit('set-layout', 'list')"
        >
          清單
        </button>
      </div>

      <label class="control">
        <span class="control-label">分組</span>
        <select
          data-group-selector
          :value="group ?? ''"
          @change="
            emit(
              'set-group',
              ($event.target as HTMLSelectElement).value || null,
            )
          "
        >
          <option value="">不分組</option>
          <option
            v-for="option in GROUPS"
            :key="option.value"
            :value="option.value"
          >
            {{ option.label }}
          </option>
        </select>
      </label>

      <label class="control">
        <span class="control-label">排序</span>
        <select
          data-order-selector
          :value="order ?? 'rank:asc'"
          @change="
            emit(
              'set-order',
              ($event.target as HTMLSelectElement).value || null,
            )
          "
        >
          <option
            v-for="option in ORDERS"
            :key="option.value"
            :value="option.value"
          >
            {{ option.label }}
          </option>
        </select>
      </label>

      <label class="control">
        <span class="control-label">密度</span>
        <select
          data-density-selector
          :value="density"
          @change="
            emit(
              'set-density',
              ($event.target as HTMLSelectElement).value as Density,
            )
          "
        >
          <option value="comfortable">寬鬆</option>
          <option value="compact">緊密</option>
        </select>
      </label>

      <button
        type="button"
        class="ghost"
        :aria-pressed="fullScreen"
        data-toggle-full-screen
        @click="emit('toggle-full-screen')"
      >
        {{ fullScreen ? "離開全螢幕" : "全螢幕" }}
      </button>
    </div>

    <div v-if="builderOpen" class="builder" data-filter-builder>
      <!-- An unrepresentable filter is **kept and named**, never rewritten. It still
           applies, because the URL is what the server reads. -->
      <p
        v-if="!representable"
        class="builder-note"
        data-filter-not-representable
      >
        目前的篩選不是在這裡建的，這個面板顯示不了它。它仍然生效；按「清除篩選」會把它移除。
      </p>
      <div
        v-for="(row, index) in builder"
        :key="index"
        class="builder-row"
        data-builder-row
      >
        <select
          data-builder-field
          :value="row.field"
          @change="
            setRowField(index, ($event.target as HTMLSelectElement).value)
          "
        >
          <option
            v-for="option in BUILDER_FIELDS"
            :key="option.field"
            :value="option.field"
          >
            {{ option.label }}
          </option>
        </select>
        <select
          data-builder-op
          :value="row.op"
          @change="
            setRowOp(
              index,
              ($event.target as HTMLSelectElement).value as
                | 'eq'
                | 'neq'
                | 'in'
                | 'not_in',
            )
          "
        >
          <option v-for="op in fieldSpec(row.field).ops" :key="op" :value="op">
            {{ OP_LABELS[op] }}
          </option>
        </select>
        <span class="builder-values">
          <button
            v-for="option in fieldSpec(row.field).options"
            :key="option.value"
            type="button"
            class="chip"
            :data-builder-value="option.value"
            :data-active="row.values.includes(option.value)"
            @click="toggleRowValue(index, option.value)"
          >
            {{ option.label }}
          </button>
        </span>
        <button
          type="button"
          class="ghost"
          data-remove-builder-row
          @click="removeRow(index)"
        >
          移除
        </button>
      </div>
      <div class="builder-actions">
        <UiButton
          size="sm"
          variant="secondary"
          data-add-builder-row
          @click="addRow"
        >
          加一列條件
        </UiButton>
        <UiButton
          v-if="builder.length || !representable"
          size="sm"
          variant="ghost"
          data-clear-filter
          @click="clearFilter"
        >
          清除篩選
        </UiButton>
      </div>
    </div>

    <div v-if="activeView && canManageViews" class="row view-actions">
      <!-- **Only a shared view can be the project's default**, and the server is the
           reason rather than a styling choice: `set_default` refuses a personal view with
           `VIEW_NOT_OWNED`, because the default is what somebody sees on their *first*
           visit to this project (`plan/26/06` §2) — one person's private view cannot be
           that. Offering the button and letting it 403 is how a control teaches people to
           distrust the toolbar. -->
      <UiButton
        v-if="activeViewIsShared && !activeViewIsDefault"
        size="sm"
        variant="ghost"
        data-set-default
        @click="emit('set-default', activeView)"
      >
        設為預設
      </UiButton>
      <span v-else-if="activeViewIsDefault" class="is-default" data-is-default
        >目前的預設檢視</span
      >
      <span v-else class="is-default" data-cannot-default
        >個人檢視不能當專案預設</span
      >
      <UiButton
        size="sm"
        variant="ghost"
        data-rename-view
        @click="emit('rename-view', activeView)"
      >
        重新命名
      </UiButton>
      <UiButton
        size="sm"
        variant="ghost"
        data-duplicate-view
        @click="emit('duplicate-view', activeView)"
      >
        複製
      </UiButton>
      <UiButton
        size="sm"
        variant="ghost"
        data-delete-view
        @click="emit('delete-view', activeView)"
      >
        刪除
      </UiButton>
    </div>

    <div class="row chips">
      <button
        v-for="chip in QUICK_FILTERS"
        :key="chip.key"
        type="button"
        class="chip"
        :data-chip="chip.key"
        :data-active="activeChips.includes(chip.key)"
        :disabled="chipDisabled(chip.needsRuntime)"
        :title="
          chipDisabled(chip.needsRuntime) ? RUNTIME_UNAVAILABLE : undefined
        "
        @click="emit('toggle-chip', chip.key)"
      >
        {{ chip.label }}
      </button>
      <!-- Said out loud, not only as a tooltip: a disabled chip with no reason is a
           control people assume is broken. -->
      <span v-if="!runtimeAvailable" class="runtime-note" data-runtime-note>
        {{ RUNTIME_UNAVAILABLE }}
      </span>
    </div>

    <div v-if="modified || filterNotInLink" class="row status">
      <span v-if="modified" class="modified" data-modified>
        已修改（{{ activeViewName }}）
      </span>
      <UiButton
        v-if="modified && canManageViews"
        size="sm"
        variant="secondary"
        data-save-as
        @click="emit('save-as')"
      >
        另存為…
      </UiButton>
      <UiButton
        v-if="modified"
        size="sm"
        variant="ghost"
        data-revert
        @click="emit('revert')"
      >
        還原
      </UiButton>
      <!-- The filter is still applied; it is the *link* that does not carry it. Saying so
           is the whole point (D103). -->
      <span v-if="filterNotInLink" class="not-in-link" data-not-in-link>
        此篩選未包含在連結中
      </span>
    </div>
  </div>
</template>

<style scoped>
.toolbar {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  margin-bottom: var(--space-3);
}
.row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-3);
}
.control {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  font-size: var(--font-xs);
  color: var(--text-muted);
}
.control.search input {
  min-width: 12rem;
  padding: var(--space-1) var(--space-2);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  background: var(--surface-default);
  color: var(--text-primary);
  font-size: var(--font-sm);
}
.shared-note,
.is-default {
  font-size: var(--font-xs);
  color: var(--text-muted);
}
.builder {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding: var(--space-3);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  background: var(--surface-canvas);
}
.builder-note {
  margin: 0;
  font-size: var(--font-xs);
  color: var(--text-muted);
}
.builder-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
}
.builder-values {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-1);
}
.builder-actions {
  display: flex;
  gap: var(--space-2);
}
.view-actions {
  gap: var(--space-2);
}
.control select {
  padding: 3px 6px;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  background: var(--surface-elevated);
  color: var(--text-primary);
  font-size: var(--font-xs);
}
.segmented {
  display: inline-flex;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  overflow: hidden;
}
.segmented button {
  padding: 3px 10px;
  border: 0;
  background: var(--surface-elevated);
  color: var(--text-secondary);
  font-size: var(--font-xs);
  cursor: pointer;
}
.segmented button[data-active="true"] {
  background: var(--action-primary);
  color: var(--text-inverse);
}
.chips {
  gap: var(--space-2);
}
.chip {
  padding: 2px 10px;
  border: 1px solid var(--border-default);
  border-radius: 999px;
  background: var(--surface-elevated);
  color: var(--text-secondary);
  font-size: var(--font-xs);
  cursor: pointer;
}
.chip[data-active="true"] {
  border-color: var(--action-primary);
  background: color-mix(
    in srgb,
    var(--action-primary) 12%,
    var(--surface-elevated)
  );
  color: var(--text-primary);
  font-weight: 600;
}
.chip:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.runtime-note,
.not-in-link {
  color: var(--attention-warning);
  font-size: var(--font-xs);
}
.status {
  gap: var(--space-2);
}
.modified {
  color: var(--text-secondary);
  font-size: var(--font-xs);
  font-weight: 600;
}
.ghost {
  padding: 3px 8px;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  background: var(--surface-elevated);
  color: var(--text-secondary);
  font-size: var(--font-xs);
  cursor: pointer;
}
</style>
