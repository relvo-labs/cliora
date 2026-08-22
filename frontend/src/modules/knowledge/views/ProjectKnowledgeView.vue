<script setup lang="ts">
// The Knowledge page.
//
// A top-level route rather than another tab on `ProjectDetailView`, which is already
// 1515 lines managing twelve things; one more tab makes `beta.1`'s split more expensive
// for no gain today.
//
// It lives under `modules/` — the first thing here to do so. `PX-64`'s difficulty is
// that existing pages have to work with the flag both on and off; a page with no
// predecessor has no such problem, so it can be born in the new structure (D82).
import { computed, onMounted } from "vue";
import { useRoute } from "vue-router";

import { api, useAuthStore } from "../../../stores/auth";
import AuthorityBadge from "../components/AuthorityBadge.vue";
import CitationLink from "../components/CitationLink.vue";
import KnowledgeSearch from "../components/KnowledgeSearch.vue";
import SourceHealth from "../components/SourceHealth.vue";
import { sourceLabel, useKnowledgeQueries } from "../queries";

const route = useRoute();
const auth = useAuthStore();
const client = api();
const projectId = computed(() => String(route.params.id));
const canManage = computed(() => auth.hasPermission("project.manage"));

const queries = useKnowledgeQueries(() => projectId.value);

// `knowledge_enabled=false` answers 404 on every one of these, so a project with memory
// switched off shows the enable prompt rather than an empty search box. An empty box
// would say "nothing has been written", which is a different and wrong answer.
const disabled = computed(() => queries.health.state.value === "error");

async function enable(): Promise<void> {
  await client.setKnowledgeEnabled(projectId.value, true);
  await queries.refreshAll();
}

async function resync(): Promise<void> {
  await client.resyncKnowledge(projectId.value);
  await queries.refreshAll();
}

onMounted(() => void queries.refreshAll());
</script>

<template>
  <div class="knowledge">
    <header class="knowledge__header">
      <h2>專案記憶</h2>
      <button v-if="canManage && !disabled" type="button" @click="resync">
        重新同步
      </button>
    </header>

    <section
      v-if="disabled"
      class="knowledge__enable"
      data-testid="enable-prompt"
    >
      <h3>這個專案還沒有啟用專案記憶</h3>
      <p>
        啟用之後，平台會把這個專案已經存在的事實——卡片、對話、決策、驗證、產物——
        建立成可檢索、可引用的來源。程式庫文件由 Agent 在 run 裡推送。
      </p>
      <p class="knowledge__note">
        啟用不會複製任何新資料，也不會新增任何對外連線。關閉時既有來源標為停用而不刪除。
      </p>
      <button v-if="canManage" type="button" @click="enable">
        啟用專案記憶
      </button>
      <p v-else class="knowledge__note">啟用需要專案管理權限。</p>
    </section>

    <template v-else>
      <KnowledgeSearch :project-id="projectId" />

      <SourceHealth :health="queries.health.data.value" />

      <section class="knowledge__decisions">
        <h3>決策</h3>
        <div class="knowledge__columns">
          <div
            v-for="column in ['accepted', 'superseded', 'conflicting'] as const"
            :key="column"
          >
            <h4>
              {{
                column === "accepted"
                  ? "已接受"
                  : column === "superseded"
                    ? "已被取代"
                    : "衝突"
              }}
            </h4>
            <ul>
              <li
                v-for="row in queries.decisions.data.value?.[column] ?? []"
                :key="row.source_id"
              >
                <AuthorityBadge
                  :authority="row.authority"
                  :version="row.version"
                />
                <CitationLink :uri="row.uri" :title="row.title" />
              </li>
            </ul>
            <p
              v-if="!(queries.decisions.data.value?.[column] ?? []).length"
              class="knowledge__note"
            >
              <template v-if="column === 'conflicting'">
                目前沒有偵測到衝突。
              </template>
              <template v-else>—</template>
            </p>
          </div>
        </div>
      </section>

      <section class="knowledge__recent">
        <h3>最近學到的</h3>
        <ul>
          <li
            v-for="row in queries.recent.data.value ?? []"
            :key="row.source_id"
          >
            <AuthorityBadge :authority="row.authority" :version="row.version" />
            <span class="knowledge__type">{{
              sourceLabel(row.source_type)
            }}</span>
            <CitationLink :uri="row.uri" :title="row.title" />
          </li>
        </ul>
      </section>
    </template>
  </div>
</template>

<style scoped>
.knowledge {
  display: flex;
  flex-direction: column;
  gap: var(--space-6);
  padding: var(--space-5);
}
.knowledge__header {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
}
.knowledge__columns {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--space-4);
}
.knowledge__columns ul {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.knowledge__note {
  color: var(--text-muted);
  font-size: var(--font-sm);
}
.knowledge__type {
  color: var(--text-muted);
  font-size: var(--font-xs);
  margin-inline: var(--space-2);
}
.knowledge__recent ul {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
</style>
