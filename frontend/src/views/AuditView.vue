<script setup lang="ts">
// Admin audit log viewer (P4-05, FR-AUTH-002, SEC-006).
//
// The server is the authority: it holds the bounds, the closed action vocabulary
// and the cursor. This view renders what it is given and never re-derives
// permission — `audit.view` gates the nav entry as a courtesy, and a Developer who
// types the URL gets the forbidden state from the server's own 403.

import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import AppLayout from "../components/layout/AppLayout.vue";
import UiDataTable from "../components/ui/UiDataTable.vue";
import UiEmptyState from "../components/ui/UiEmptyState.vue";
import UiInlineNotice from "../components/ui/UiInlineNotice.vue";
import UiLoadingState from "../components/ui/UiLoadingState.vue";
import ErrorNotice from "../components/common/ErrorNotice.vue";
import {
  defaultFilter,
  filterFromQuery,
  filterToQuery,
  useAuditStore,
  type AuditFilter,
  type AuditRange,
} from "../stores/audit";
import { ACTION_GROUPS, actionLabel } from "../utils/auditActions";
import { formatInstant, localTimeZone } from "../utils/time";

const audit = useAuditStore();
const route = useRoute();
const router = useRouter();

// Draft is what the form edits; the store's filter is what was actually queried.
// Keeping them apart is why changing a field does not silently refetch and why
// "Clear" can be distinguished from "Apply".
const draft = ref<AuditFilter>(defaultFilter());
const expanded = ref<string | null>(null);
const copied = ref<string | null>(null);
const timeZone = localTimeZone();

const RANGES: { value: AuditRange; label: string }[] = [
  { value: "1h", label: "最近 1 小時" },
  { value: "24h", label: "最近 24 小時" },
  { value: "7d", label: "最近 7 天" },
  { value: "custom", label: "自訂範圍" },
];

const rows = computed(() => audit.items);
const showTable = computed(
  () => audit.state === "success" || audit.state === "partial",
);

onMounted(async () => {
  draft.value = filterFromQuery(
    route.query as Record<string, string | string[] | undefined>,
  );
  audit.setFilter(draft.value);
  await audit.search();
});

// Abort in-flight work and drop the rows when leaving, so returning to the page
// never shows another filter's results for a frame.
onUnmounted(() => audit.reset());

// The result count is announced rather than only shown, because a filter that
// returns fewer rows is the outcome of the action the user just took.
const announcement = computed(() => {
  if (audit.state === "loading") return "正在查詢 Audit Log…";
  if (audit.state === "empty") return "此條件下沒有紀錄。";
  if (audit.state === "success" || audit.state === "partial") {
    return `已載入 ${audit.loadedCount} 筆紀錄${audit.hasMore ? "，還有更多" : "，已到結尾"}。`;
  }
  return "";
});

async function apply(): Promise<void> {
  audit.setFilter(draft.value);
  // The filter lives in the URL so a view can be shared and survives a reload.
  await router.replace({ query: filterToQuery(draft.value) });
  await audit.search();
}

async function clear(): Promise<void> {
  draft.value = defaultFilter();
  await apply();
}

function toggleAction(action: string): void {
  const actions = new Set(draft.value.actions);
  if (actions.has(action)) {
    actions.delete(action);
  } else {
    actions.add(action);
  }
  draft.value = { ...draft.value, actions: [...actions] };
}

function toggleRow(id: string): void {
  expanded.value = expanded.value === id ? null : id;
}

async function copyRequestId(requestId: string): Promise<void> {
  try {
    await navigator.clipboard?.writeText(requestId);
    copied.value = requestId;
  } catch {
    // Clipboard access can be denied; the id is selectable text either way.
    copied.value = null;
  }
}

// Reset the "copied" acknowledgement when the rows change under it.
watch(rows, () => {
  copied.value = null;
});
</script>

<template>
  <AppLayout>
    <header class="head">
      <div>
        <h1>Audit Log</h1>
        <p>
          Accountable operations across this control plane. Read-only, Admin
          only.
        </p>
      </div>
      <button
        class="ghost"
        :disabled="audit.state === 'loading'"
        @click="audit.search()"
      >
        Refresh
      </button>
    </header>

    <form class="filters" @submit.prevent="apply">
      <fieldset>
        <legend>Action</legend>
        <div class="groups">
          <div v-for="group in ACTION_GROUPS" :key="group.title" class="group">
            <p class="group-title">{{ group.title }}</p>
            <label v-for="action in group.actions" :key="action" class="check">
              <input
                type="checkbox"
                :checked="draft.actions.includes(action)"
                @change="toggleAction(action)"
              />
              <span>{{ actionLabel(action) }}</span>
              <code>{{ action }}</code>
            </label>
          </div>
        </div>
      </fieldset>

      <div class="fields">
        <label>
          <span>時間範圍</span>
          <select v-model="draft.range">
            <option
              v-for="range in RANGES"
              :key="range.value"
              :value="range.value"
            >
              {{ range.label }}
            </option>
          </select>
        </label>
        <template v-if="draft.range === 'custom'">
          <label>
            <span>From</span>
            <input v-model="draft.from" type="datetime-local" />
          </label>
          <label>
            <span>To</span>
            <input v-model="draft.to" type="datetime-local" />
          </label>
        </template>
        <label>
          <span>Actor (user id)</span>
          <input v-model="draft.userId" type="text" placeholder="UUID" />
        </label>
        <label>
          <span>Node id</span>
          <input v-model="draft.nodeId" type="text" placeholder="UUID" />
        </label>
        <label>
          <span>Session id</span>
          <input v-model="draft.sessionId" type="text" placeholder="UUID" />
        </label>
      </div>

      <div class="filter-actions">
        <button
          class="primary"
          type="submit"
          :disabled="audit.state === 'loading'"
        >
          Apply
        </button>
        <button class="ghost" type="button" @click="clear">Clear</button>
      </div>
    </form>

    <p class="sr-only" role="status" aria-live="polite">{{ announcement }}</p>

    <!-- One v-if chain: exactly one of these states renders. `error` uses ErrorNotice
         for the catalog's cause / next-step presentation, so a too-wide time range and
         an unreachable Central read differently and each says what to do about itself
         (P4-07). -->
    <UiLoadingState
      v-if="audit.state === 'loading'"
      label="正在查詢 Audit Log"
    />
    <UiInlineNotice
      v-else-if="audit.state === 'forbidden'"
      tone="error"
      title="無法存取"
      >{{ audit.message }}
      <RouterLink :to="{ name: 'nodes' }"
        >返回 Nodes</RouterLink
      ></UiInlineNotice
    >
    <ErrorNotice
      v-else-if="audit.state === 'error'"
      :error="audit.error"
      class="note"
      @retry="audit.search()"
    />
    <UiEmptyState
      v-else-if="audit.state === 'empty'"
      variant="empty"
      title="沒有資料"
      >此條件下沒有紀錄。可放寬時間範圍或移除部分 action 條件。</UiEmptyState
    >

    <UiInlineNotice
      v-if="audit.state === 'partial'"
      class="note"
      tone="stale"
      title="部分資料無法取得"
      >已顯示已載入的 {{ audit.loadedCount }} 筆，但載入下一頁時失敗：{{
        audit.message
      }}</UiInlineNotice
    >

    <!-- Kept visible rather than folded into the table's accessible name: the
         time zone changes how every timestamp below should be read, so it is
         information, not a label. -->
    <p v-if="showTable" class="table-note">
      Audit entries, newest first. Times shown in {{ timeZone }}.
    </p>
    <UiDataTable
      v-if="showTable"
      :label="`Audit entries, newest first, times in ${timeZone}`"
      :columns="[
        `Time (${timeZone})`,
        'Action',
        'Actor',
        'Resource',
        'request_id',
        'Metadata',
      ]"
    >
      <template v-for="row in rows" :key="row.id">
        <tr>
          <td :title="row.created_at">
            {{ formatInstant(row.created_at) }}
          </td>
          <td>
            <span class="action">{{ actionLabel(row.action) }}</span>
            <code>{{ row.action }}</code>
          </td>
          <td>
            <template v-if="row.actor">
              {{ row.actor.display_name ?? row.actor.username ?? "（已刪除）" }}
            </template>
            <template v-else>—</template>
          </td>
          <td>
            <RouterLink
              v-if="row.node"
              :to="{ name: 'node-detail', params: { id: row.node.id } }"
            >
              {{ row.node.name ?? "（已刪除的 Node）" }}
            </RouterLink>
            <RouterLink
              v-if="row.session_id"
              :to="{
                name: 'session-workspace',
                params: { id: row.session_id },
              }"
              class="session-link"
            >
              session
            </RouterLink>
            <template v-if="!row.node && !row.session_id">—</template>
          </td>
          <td>
            <template v-if="row.request_id">
              <code>{{ row.request_id }}</code>
              <button
                class="link"
                type="button"
                :aria-label="`複製 request_id ${row.request_id}`"
                @click="copyRequestId(row.request_id)"
              >
                {{ copied === row.request_id ? "已複製" : "複製" }}
              </button>
            </template>
            <template v-else>—</template>
          </td>
          <td>
            <button
              class="link"
              type="button"
              :aria-expanded="expanded === row.id"
              :aria-controls="`meta-${row.id}`"
              @click="toggleRow(row.id)"
            >
              {{ expanded === row.id ? "收合" : "展開" }}
            </button>
          </td>
        </tr>
        <tr v-if="expanded === row.id" class="meta-row">
          <td :id="`meta-${row.id}`" colspan="6">
            <pre>{{ JSON.stringify(row.metadata, null, 2) }}</pre>
          </td>
        </tr>
      </template>
    </UiDataTable>

    <div v-if="showTable" class="footer">
      <!-- Loaded count only: the server returns no total, and inventing one
           would misrepresent how much of the window has been read. -->
      <span>已載入 {{ audit.loadedCount }} 筆</span>
      <button
        v-if="audit.hasMore"
        class="ghost"
        type="button"
        :disabled="audit.loadingMore"
        @click="audit.loadMore()"
      >
        {{ audit.loadingMore ? "載入中…" : "載入更多" }}
      </button>
      <span v-else>已到結尾</span>
    </div>
  </AppLayout>
</template>

<style scoped>
.head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  margin-bottom: 20px;
}
.head h1 {
  margin: 0;
  font-size: 24px;
}
.head p {
  margin: 4px 0 0;
  color: var(--text-secondary);
  font-size: 13px;
}
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  margin: -1px;
  padding: 0;
  overflow: hidden;
  clip-path: inset(50%);
  white-space: nowrap;
}
.filters {
  margin-bottom: 18px;
  padding: 16px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-panel);
  background: var(--surface-default);
}
fieldset {
  margin: 0 0 14px;
  padding: 0;
  border: 0;
}
legend {
  padding: 0;
  color: var(--text-secondary);
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.groups {
  display: flex;
  flex-wrap: wrap;
  gap: 18px;
  margin-top: 8px;
}
.group-title {
  margin: 0 0 4px;
  color: var(--text-primary);
  font-size: 12px;
  font-weight: 600;
}
.check {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
}
.check code,
td code {
  color: var(--text-secondary);
  font-size: 11px;
}
.fields {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}
.fields label {
  display: grid;
  gap: 4px;
  font-size: 12px;
}
.fields span {
  color: var(--text-secondary);
}
.fields input,
.fields select {
  padding: 6px 8px;
  border: 1px solid var(--border-control);
  border-radius: var(--radius-control);
  background: var(--surface-raised);
  color: var(--text-primary);
  font-size: 13px;
}
.filter-actions {
  display: flex;
  gap: 10px;
  margin-top: 14px;
}
.primary,
.ghost {
  padding: 8px 14px;
  border-radius: var(--radius-control);
  font-weight: 600;
}
.primary {
  border: 0;
  background: var(--accent-strong);
  color: var(--text-on-accent);
}
.ghost {
  border: 1px solid var(--border-control);
  background: var(--surface-raised);
  color: var(--text-primary);
}
.note {
  margin-bottom: 14px;
}
.action {
  display: block;
  font-weight: 600;
}
.session-link {
  margin-left: 8px;
}
.meta-row td {
  white-space: normal;
  background: var(--surface-canvas);
}
.meta-row pre {
  margin: 0;
  max-height: 320px;
  overflow: auto;
  font-size: 12px;
}
.footer {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 14px;
  color: var(--text-secondary);
  font-size: 12px;
}
.link {
  padding: 0 4px;
  border: 0;
  background: none;
  color: var(--accent-strong);
  font-weight: 600;
}
.rid {
  margin-left: 8px;
  color: var(--text-secondary);
  font-size: 11px;
}
.table-note {
  margin: 0 0 10px;
  color: var(--text-secondary);
  font-size: 12px;
}
</style>
