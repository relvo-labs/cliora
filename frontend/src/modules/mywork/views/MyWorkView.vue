<script setup lang="ts">
/**
 * "What is waiting for me", across every project (PX-49, plan/26/08 §1).
 *
 * **The differentiating page.** Cliora's special states are all inside projects —
 * waiting for input, no eligible runner, assigned runner offline, failed run, gate
 * pending, verification failed — so somebody looking after three projects has had to open
 * each one to find out what happened. This page answers the question without opening any
 * of them.
 *
 * **It reads state, never "have you seen this"** (`GATE-PX-MYWORK-READS-STATE`). There is
 * no notification system in this deployment, and when one arrives it must not be able to
 * change a number on this page: a thing disappears from here when the Task, the Run or
 * the gate actually changes, not when somebody clicks.
 *
 * Freshness is the shared counts poller (D95): twenty seconds, paused while the tab is
 * hidden, and the item lists are re-fetched only when a count actually moved.
 */
import { computed, onMounted, onUnmounted, ref } from "vue";

import { ApiError } from "../../../api/client";
import { type WorkCounts } from "../../../api/dto";
import AppLayout from "../../../components/layout/AppLayout.vue";
import AsyncState from "../../../components/common/AsyncState.vue";
import PageHead from "../../../components/ui/PageHead.vue";
import { api, useAuthStore } from "../../../stores/auth";
import { countsDiffer, countsPoller } from "../../work/queryCache";
import AttentionSection from "../components/AttentionSection.vue";
import { encodeFilter, sectionsFor, type SectionResult } from "../sections";

const auth = useAuthStore();

const sections = ref<SectionResult[]>([]);
const counts = ref<WorkCounts | null>(null);
const state = ref<"loading" | "ready" | "forbidden" | "error">("loading");
const requestId = ref<string | undefined>(undefined);

const visible = computed(() =>
  sections.value.filter(
    (section) =>
      !section.spec.requires || auth.hasPermission(section.spec.requires),
  ),
);
const total = computed(() =>
  visible.value.reduce((sum, section) => sum + section.count, 0),
);

async function loadSections(): Promise<void> {
  const userId = auth.user?.id ?? "";
  const specs = sectionsFor(userId);
  try {
    const pages = await Promise.all(
      specs.map((spec) =>
        api().getMyWorkItems({ filter: encodeFilter(spec.filter), limit: 10 }),
      ),
    );
    sections.value = specs.map((spec, index) => {
      const page = pages[index];
      const items = page.groups.flatMap((group) => group.items);
      const count = page.groups.reduce((sum, group) => sum + group.count, 0);
      // The third state. A section that needs the registry and did not get it is
      // **unanswered**, not empty — see the component.
      const unavailable =
        spec.needsRuntime && !page.runtime_signals_available
          ? "節點連線資訊暫時不可用，這一段現在無法回答。"
          : null;
      return { spec, items, count, unavailable };
    });
    state.value = "ready";
  } catch (error) {
    requestId.value = error instanceof ApiError ? error.requestId : undefined;
    state.value =
      error instanceof ApiError && error.status === 403 ? "forbidden" : "error";
  }
}

/** The poller's job: fetch counts, and only touch the lists if a count moved.
 *
 *  This is what makes "poll counts, not items" a real distinction rather than a phrasing.
 *  Six section requests every twenty seconds would be worse than polling the board. */
async function refreshCounts(): Promise<void> {
  try {
    const next = await api().getMyAttentionCounts();
    if (countsDiffer(counts.value as never, next as never)) {
      counts.value = next;
      await loadSections();
    }
  } catch {
    // A failed poll leaves the page as it was. The lists on screen were true twenty
    // seconds ago, and blanking them would be a worse answer than a slightly old one.
  }
}

let release: (() => void) | null = null;

onMounted(async () => {
  await loadSections();
  counts.value = await api()
    .getMyAttentionCounts()
    .catch(() => null);
  release = countsPoller.subscribe(refreshCounts);
});

onUnmounted(() => {
  release?.();
  release = null;
});
</script>

<template>
  <AppLayout>
    <PageHead>
      <template #title>My Work</template>
      <template #subtitle>
        哪些事情在等一個人類，而那個人類是你——跨全部你看得到的專案。
      </template>
      <template #actions>
        <span v-if="state === 'ready'" class="total" data-total>
          {{ total }} 件
        </span>
      </template>
    </PageHead>

    <AsyncState v-if="state === 'loading'" state="loading">載入中…</AsyncState>
    <AsyncState v-else-if="state === 'forbidden'" state="forbidden">
      你沒有權限查看任何專案的工作。
    </AsyncState>
    <AsyncState v-else-if="state === 'error'" state="error">
      無法載入。<span v-if="requestId">Request ID: {{ requestId }}</span>
    </AsyncState>
    <div v-else class="sections">
      <AttentionSection
        v-for="section in visible"
        :key="section.spec.key"
        :section="section"
      />
    </div>
  </AppLayout>
</template>

<style scoped>
.sections {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(360px, 1fr));
  gap: var(--space-4);
  align-items: start;
}
.total {
  color: var(--text-secondary);
  font-size: var(--font-sm);
  font-variant-numeric: tabular-nums;
}
</style>
