<script setup lang="ts">
// Search, and the line under each result that says why it is there.
//
// **That line is the point of this page.** Retrieval an operator cannot inspect makes
// "why did the agent do that?" permanently unanswerable, and the ranking is the part
// nobody can read from the outside. It comes from the server's `why` verbatim: a second
// explanation computed here would disagree with the first one day, and nobody would be
// able to tell which was lying.
import { computed, ref, watch } from "vue";

import type { KnowledgeHit } from "../../../api/dto";
import AuthorityBadge from "./AuthorityBadge.vue";
import CitationLink from "./CitationLink.vue";
import { explainWhy, sourceLabel, useKnowledgeSearch } from "../queries";

const props = defineProps<{ projectId: string; initialQuery?: string }>();
const emit = defineEmits<{ (event: "select", hit: KnowledgeHit): void }>();

const query = ref(props.initialQuery ?? "");
const sourceType = ref("");
const authority = ref("");
const includeHistory = ref(false);

const search = useKnowledgeSearch(
  () => props.projectId,
  () => ({
    q: query.value,
    sourceType: sourceType.value || undefined,
    authority: authority.value || undefined,
    includeHistory: includeHistory.value,
  }),
);

const results = computed(() => search.data.value?.items ?? []);
const degraded = computed(() => search.data.value?.degraded ?? null);

async function submit(): Promise<void> {
  if (!query.value.trim()) return;
  await search.run();
}

// Re-run when a filter changes but **not** when the text does: searching on every
// keystroke would send a query per character to an endpoint that reads two GIN indexes.
watch([sourceType, authority, includeHistory], () => {
  if (query.value.trim()) void search.run();
});
</script>

<template>
  <section class="search">
    <form class="search__form" @submit.prevent="submit">
      <input
        v-model="query"
        class="search__input"
        type="search"
        placeholder="搜尋這個專案的記憶"
        aria-label="搜尋這個專案的記憶"
      />
      <button type="submit" class="search__submit">搜尋</button>
    </form>

    <div class="search__filters">
      <label>
        來源類型
        <select v-model="sourceType" aria-label="來源類型">
          <option value="">全部</option>
          <option value="policy">專案規則</option>
          <option value="decision">決策</option>
          <option value="ticket">卡片</option>
          <option value="conversation">對話</option>
          <option value="repo_doc">程式庫文件</option>
          <option value="artifact">產物</option>
          <option value="verification">驗證</option>
        </select>
      </label>
      <label>
        可信層級
        <select v-model="authority" aria-label="可信層級">
          <option value="">全部</option>
          <option value="authoritative">正式決策</option>
          <option value="accepted">已接受</option>
          <option value="canonical">程式庫現況</option>
          <option value="verified">已驗證</option>
          <option value="generated">Agent 產出</option>
          <option value="discussion">討論</option>
        </select>
      </label>
      <label class="search__history">
        <input v-model="includeHistory" type="checkbox" />
        含已被取代的版本
      </label>
    </div>

    <p v-if="degraded" class="search__degraded" role="status">
      查詢過短，只做了模糊比對——換一個長一點的詞可能找到更多。
    </p>

    <p v-if="search.state.value === 'empty'" class="search__empty">
      沒有找到符合的來源。
    </p>

    <ol v-else class="search__results">
      <li
        v-for="hit in results"
        :key="hit.source_id"
        class="result"
        :class="{ 'result--historical': hit.historical }"
        @click="emit('select', hit)"
      >
        <header class="result__head">
          <AuthorityBadge :authority="hit.authority" :version="hit.version" />
          <span class="result__type">{{ sourceLabel(hit.source_type) }}</span>
          <span class="result__title">{{ hit.title }}</span>
          <span v-if="hit.historical" class="result__historical">已被取代</span>
        </header>
        <p class="result__excerpt">{{ hit.excerpt }}</p>
        <p class="result__why">為什麼：{{ explainWhy(hit.why) }}</p>
        <CitationLink :uri="hit.uri" :title="hit.title" />
      </li>
    </ol>

    <p v-if="search.data.value" class="search__meta">
      {{ search.data.value.total }} 筆結果・通道：{{
        search.data.value.channels.join("＋")
      }}
    </p>
  </section>
</template>

<style scoped>
.search__form {
  display: flex;
  gap: var(--space-2);
}
.search__input {
  flex: 1;
}
.search__filters {
  display: flex;
  gap: var(--space-4);
  align-items: center;
  margin-block: var(--space-3);
  font-size: var(--font-sm);
}
.search__degraded {
  color: var(--status-busy);
  font-size: var(--font-sm);
}
.search__results {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}
.result {
  padding: var(--space-3);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  background: var(--surface-elevated);
}
.result--historical {
  opacity: 0.7;
}
.result__head {
  display: flex;
  align-items: baseline;
  gap: var(--space-2);
  flex-wrap: wrap;
}
.result__title {
  font-weight: 600;
}
.result__type,
.result__historical {
  color: var(--text-muted);
  font-size: var(--font-xs);
}
.result__excerpt {
  margin-block: var(--space-2);
  color: var(--text-secondary);
}
.result__why {
  color: var(--text-muted);
  font-size: var(--font-xs);
}
.search__meta {
  margin-block-start: var(--space-4);
  color: var(--text-muted);
  font-size: var(--font-xs);
}
</style>
