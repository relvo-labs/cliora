<script setup lang="ts">
// The session list. plan/28 changes three things about it.
//
// **The name and the path are one column, not two.** A path in its own column
// sets that column's width from its longest value, which is how a table gets
// wide enough to need a page-level scrollbar. As a second line under the name it
// costs nothing horizontally, and the name is what identifies the row anyway.
//
// **Search and a runtime filter**, over the rows already fetched. No new
// request and no new endpoint: this is a display filter. It exists because
// plan/28 requires the empty-list and no-results states to be *different*, and
// without a filter there is no no-results state to distinguish.
//
// **Empty and no-results say different things**, because the next action
// differs: one is "create the first session", the other is "clear the filter".
// The component that used to render both printed the same line for each.

import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { RefreshCw, Search } from "lucide-vue-next";

import { ACTION_SESSION_CREATE } from "../api/dto";
import type { SessionDetail } from "../api/dto";
import AppLayout from "../components/layout/AppLayout.vue";
import ErrorNotice from "../components/common/ErrorNotice.vue";
import StatusBadge from "../components/common/StatusBadge.vue";
import NewSessionDialog from "../components/session/NewSessionDialog.vue";
import UiButton from "../components/ui/UiButton.vue";
import UiDataTable from "../components/ui/UiDataTable.vue";
import UiEmptyState from "../components/ui/UiEmptyState.vue";
import UiInlineNotice from "../components/ui/UiInlineNotice.vue";
import UiLoadingState from "../components/ui/UiLoadingState.vue";
import { useAsyncResource } from "../composables/useAsyncResource";
import { useAuthStore } from "../stores/auth";
import { useSessionsStore } from "../stores/sessions";
import { formatInstant } from "../utils/time";

const auth = useAuthStore();
const sessions = useSessionsStore();
const router = useRouter();

const canCreate = computed(() => auth.hasPermission(ACTION_SESSION_CREATE));
const dialogOpen = ref(false);

const query = ref("");
const runtimeFilter = ref("all");

const resource = useAsyncResource(() => sessions.fetchList(), {
  isEmpty: (list) => list.length === 0,
});

const displayState = computed(() =>
  resource.state.value === "success" && sessions.list.length === 0
    ? "empty"
    : resource.state.value,
);

// Offered runtimes come from the rows themselves rather than a fixed list: a
// filter that offers a runtime no session uses is a dead end, and one that
// omits a runtime that is present hides rows.
const runtimes = computed(() => [
  ...new Set(sessions.list.map((s) => s.runtime)),
]);

const filtered = computed(() => {
  const needle = query.value.trim().toLowerCase();
  return sessions.list.filter((s) => {
    const matchesRuntime =
      runtimeFilter.value === "all" || s.runtime === runtimeFilter.value;
    if (!matchesRuntime) return false;
    if (!needle) return true;
    return `${s.name} ${s.workspace}`.toLowerCase().includes(needle);
  });
});

const isFiltered = computed(
  () => query.value.trim() !== "" || runtimeFilter.value !== "all",
);

function clearFilters(): void {
  query.value = "";
  runtimeFilter.value = "all";
}

onMounted(() => resource.run());

function open(id: string): void {
  void router.push({ name: "session-workspace", params: { id } });
}

function onCreated(session: SessionDetail): void {
  dialogOpen.value = false;
  open(session.id);
}
</script>

<template>
  <AppLayout>
    <header class="head">
      <div>
        <h1>Sessions</h1>
        <p>跨節點的工作，從這裡繼續。</p>
      </div>
      <div class="head-actions">
        <UiButton
          variant="secondary"
          :busy="resource.state.value === 'loading'"
          @click="resource.run()"
        >
          <template #icon><RefreshCw class="icon" /></template>
          重新整理
        </UiButton>
        <UiButton v-if="canCreate" variant="primary" @click="dialogOpen = true">
          建立 Session
        </UiButton>
      </div>
    </header>

    <!-- Hidden while there is nothing to filter: a search box over an empty
         list invites the user to search for something that cannot be there. -->
    <div v-if="displayState === 'success'" class="filters">
      <label class="search">
        <Search class="icon" aria-hidden="true" />
        <span class="sr-only">搜尋 Sessions</span>
        <input
          v-model="query"
          type="search"
          placeholder="搜尋名稱或工作目錄"
          aria-label="搜尋名稱或工作目錄"
        />
      </label>
      <label class="runtime">
        <span class="sr-only">Runtime 篩選</span>
        <select v-model="runtimeFilter" aria-label="Runtime 篩選">
          <option value="all">所有 Runtime</option>
          <option v-for="rt in runtimes" :key="rt" :value="rt">{{ rt }}</option>
        </select>
      </label>
      <!-- The filter state in words, not only in the controls' values: a user
           who has scrolled past the toolbar should be able to tell why the list
           is short. -->
      <p v-if="isFiltered" class="filter-note" role="status">
        顯示 {{ filtered.length }} / {{ sessions.list.length }} 筆
      </p>
    </div>

    <UiLoadingState
      v-if="displayState === 'loading'"
      label="正在載入 Sessions"
    />
    <UiInlineNotice
      v-else-if="displayState === 'forbidden'"
      tone="error"
      title="無法存取"
      message="你的角色沒有檢視 Sessions 的權限。UI 隱藏不能取代伺服器授權。"
    />
    <ErrorNotice
      v-else-if="displayState === 'error'"
      :error="resource.error.value"
      @retry="resource.run()"
    />
    <UiEmptyState
      v-else-if="displayState === 'empty'"
      variant="empty"
      title="尚未建立 Session"
      detail="從「建立 Session」開始一段新的工作。"
    >
      <!-- The create entry only for someone who holds session.create. A
           courtesy, not authorization: the server refuses either way. -->
      <template v-if="canCreate" #action>
        <UiButton variant="primary" @click="dialogOpen = true">
          建立 Session
        </UiButton>
      </template>
    </UiEmptyState>

    <UiDataTable
      v-else
      label="Sessions"
      :columns="['SESSION / WORKSPACE', 'NODE', 'RUNTIME', '狀態', '最近活動']"
      :no-results="filtered.length === 0"
    >
      <template #no-results>
        <UiEmptyState
          variant="no-results"
          title="沒有符合條件的項目"
          detail="調整搜尋字串，或清除 Runtime 篩選。"
        >
          <template #action>
            <UiButton variant="secondary" @click="clearFilters">
              清除搜尋與篩選
            </UiButton>
          </template>
        </UiEmptyState>
      </template>
      <tr v-for="s in filtered" :key="s.id">
        <td>
          <UiButton variant="quiet" @click="open(s.id)">{{ s.name }}</UiButton>
          <!-- The path as a second line. -->
          <small :title="s.workspace">{{ s.workspace }}</small>
        </td>
        <td>{{ s.node_id }}</td>
        <td>{{ s.runtime }}</td>
        <td><StatusBadge :status="s.status" kind="session" /></td>
        <td :title="s.last_activity_at ?? ''">
          {{ formatInstant(s.last_activity_at) }}
        </td>
      </tr>
    </UiDataTable>

    <NewSessionDialog
      :open="dialogOpen"
      @created="onCreated"
      @cancel="dialogOpen = false"
    />
  </AppLayout>
</template>

<style scoped>
.head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;
  flex-wrap: wrap;
}
.head h1 {
  margin: 0;
  font-size: 24px;
  letter-spacing: -0.02em;
}
.head p {
  margin: 6px 0 0;
  color: var(--text-secondary);
  font-size: 13px;
}
.head-actions {
  display: flex;
  gap: 10px;
}
.icon {
  width: 15px;
  height: 15px;
}
.filters {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
  flex-wrap: wrap;
}
.search {
  position: relative;
  display: flex;
  align-items: center;
}
.search .icon {
  position: absolute;
  left: 10px;
  color: var(--text-secondary);
  pointer-events: none;
}
.search input {
  min-width: 260px;
  min-height: var(--density-control);
  padding: 0 10px 0 32px;
  border: 1px solid var(--border-control);
  border-radius: var(--radius-control);
  background: var(--surface-default);
  color: var(--text-primary);
  font-size: 13px;
}
.runtime select {
  min-height: var(--density-control);
  padding: 0 8px;
  border: 1px solid var(--border-control);
  border-radius: var(--radius-control);
  background: var(--surface-default);
  color: var(--text-primary);
  font-size: 13px;
}
.filter-note {
  margin: 0;
  color: var(--text-secondary);
  font-size: 12px;
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
