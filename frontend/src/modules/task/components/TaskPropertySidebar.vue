<script setup lang="ts">
/**
 * The Drawer's right column (PX-39, plan/26/07 §2).
 *
 * **The execution settings are collapsed by default and expand themselves when one of them
 * is the reason the card is stuck** (§2, "Advanced execution"). That is the mitigation for
 * progressive disclosure: hiding a setting is fine until the setting is the answer, and
 * then hiding it is the interface refusing to say why.
 *
 * Four situations open it, and the decision is **not recomputed here** — it reads the
 * card's attention **signals** and its own fields, because `derive_attention` is the single
 * definition (ADR 0040 §3).
 *
 * **The signals, not the primary.** The first version read `primary_attention`, and it left
 * the execution block collapsed on exactly the cards whose execution settings were the
 * answer: a card that has no eligible runner *and* is awaiting a human decision badges as
 * `pending_human_approval`, because that outranks it (D107). So the situation was true, the
 * block stayed shut, and the interface refused to say why. The board's card carries only the
 * primary on purpose — at two hundred cards the set is most of the payload — so the set
 * comes from `/api/tasks/{id}/attention`, one card, when the Drawer opens. Found by the
 * browser run of wave 5 (`plan/26/12` §2.28).
 *
 * **On a phone the whole sidebar collapses into one accordion** (PX-46). Below 760px the
 * Drawer is one column, so the sidebar lands *under* the conversation — eight rows of
 * properties between the reader and the composer. Collapsed, it is one line they can pass.
 *
 * Two things about how that is done. It is driven by `matchMedia`, not by CSS: a
 * `<details>` cannot be forced open by a stylesheet, so a media query alone would leave
 * desktop readers with a collapsed sidebar they have to open every time. And the forced-open
 * rule still wins — a card stuck on an execution setting expands on a phone too, because
 * the reason hiding is acceptable is that it stops being hidden when it is the answer.
 */
import { computed, onUnmounted, ref, watch } from "vue";

import type { Task, TaskAttention, WorkItemCard } from "../../../api/dto";

const props = defineProps<{
  task: Task;
  /** The read model's view of the same card, when the board had one. */
  card: WorkItemCard | null;
  /** This card's full signal set, when the Drawer has fetched it. Null while in flight or
   *  when the fetch failed — in which case the primary is the best available answer and
   *  the block falls back to it rather than to silence. */
  attention?: TaskAttention | null;
}>();

const open = ref(false);

/** Whether this is the narrow layout. `matchMedia` rather than a resize listener: the
 *  query fires on change only, and it is the same 760px the Drawer's own stylesheet uses.
 *
 *  Guarded for the absence of `matchMedia` because the component test environment has
 *  none, and a sidebar that throws on mount is worse than one that assumes a wide
 *  screen. */
const NARROW = "(max-width: 760px)";
const narrow = ref(
  typeof window !== "undefined" && typeof window.matchMedia === "function"
    ? window.matchMedia(NARROW).matches
    : false,
);
if (typeof window !== "undefined" && typeof window.matchMedia === "function") {
  const query = window.matchMedia(NARROW);
  const onChange = (event: MediaQueryListEvent) => {
    narrow.value = event.matches;
  };
  query.addEventListener("change", onChange);
  onUnmounted(() => query.removeEventListener("change", onChange));
}

/** Whether the properties list is showing.
 *
 *  Wide: always. Narrow: only when the reader opened it, or when something forced the
 *  execution block open — in which case the properties above it would otherwise be
 *  hidden between the reason and the rows it points at. */
const propertiesOpen = ref(false);
const showProperties = computed(
  () => !narrow.value || propertiesOpen.value || Boolean(forced.value),
);

/** Why the execution block is expanded, or null when nothing forced it.
 *
 *  Returned as a sentence rather than a boolean so the block can say *which* setting to
 *  look at — "expand this" without "because of this" makes a reader read all eight rows.
 */
const forced = computed<string | null>(() => {
  // The set when it has arrived, the primary as a fallback. Falling back rather than
  // waiting because the primary is a true statement about the card, just an incomplete
  // one — and a block that stayed shut until a second request resolved would flicker open
  // under the reader's cursor.
  const signals = new Set(
    props.attention?.signals ??
      (props.card?.primary_attention ? [props.card.primary_attention] : []),
  );
  if (signals.has("no_eligible_runner")) {
    return "沒有符合條件的 Agent — 檢查下面的必要標籤與派工診斷。";
  }
  if (signals.has("assigned_runner_offline")) {
    return "指定的 Agent 離線 — 見下面的指定 Agent。";
  }
  if ((props.task.required_secrets ?? []).length && props.card?.is_blocked) {
    return "這張卡宣告了必要機密，而它目前被阻塞 — 見下面的機密名稱。";
  }
  if (!props.task.repository_id && props.task.delivery !== "none") {
    return "這張卡宣告了交付方式，但沒有綁定程式庫 — 見下面的程式庫／分支。";
  }
  return null;
});

watch(
  forced,
  (reason) => {
    // Opened, never closed again by this watcher: a reader who collapsed it after reading
    // should not have it reopen under them on the next poll.
    if (reason) open.value = true;
  },
  { immediate: true },
);
</script>

<template>
  <aside class="sidebar" aria-label="卡片屬性" :data-narrow="narrow">
    <button
      v-if="narrow"
      type="button"
      class="disclosure"
      :aria-expanded="showProperties"
      data-properties-toggle
      @click="propertiesOpen = !propertiesOpen"
    >
      卡片屬性
      <span aria-hidden="true">{{ showProperties ? "▾" : "▸" }}</span>
    </button>
    <dl v-if="showProperties" class="properties">
      <dt>負責人</dt>
      <dd>{{ card?.owner_name ?? "—" }}</dd>
      <dt>優先／風險</dt>
      <dd>{{ task.priority }} / {{ task.risk }}</dd>
      <dt>階段</dt>
      <dd>{{ task.stage }}</dd>
      <dt>就緒程度</dt>
      <dd>{{ card?.readiness ?? "—" }}</dd>
      <dt>需求 / Epic / Story</dt>
      <dd>
        {{ task.requirement_id ? "已連結" : "—" }} /
        {{ task.epic_id ? "已連結" : "—" }} /
        {{ task.user_story_id ? "已連結" : "—" }}
      </dd>
      <dt>更新時間</dt>
      <dd>{{ task.updated_at }}</dd>
    </dl>

    <section class="execution" :data-open="open" data-execution-block>
      <button
        type="button"
        class="disclosure"
        :aria-expanded="open"
        data-execution-toggle
        @click="open = !open"
      >
        執行設定
        <span aria-hidden="true">{{ open ? "▾" : "▸" }}</span>
      </button>
      <!-- The reason is **at the top of the block**, not beside the row it concerns: a
           reader who just had this opened for them needs to know why before they read
           eight rows of settings. -->
      <p v-if="forced" class="forced" role="status" data-execution-reason>
        {{ forced }}
      </p>
      <dl v-if="open" class="properties">
        <dt>指定 Agent</dt>
        <dd>
          {{
            card?.active_run_runner_name ?? task.assigned_runner_id ?? "任一"
          }}
        </dd>
        <dt>必要標籤</dt>
        <dd>{{ (task.required_labels ?? []).join("、") || "—" }}</dd>
        <dt>來源／交付</dt>
        <dd>{{ task.source }} / {{ task.delivery }}</dd>
        <dt>程式庫／分支</dt>
        <dd>
          {{ task.repository_id ?? "未綁定" }} /
          {{ task.base_branch ?? "—" }}
        </dd>
        <dt>必要機密</dt>
        <dd>{{ (task.required_secrets ?? []).join("、") || "—" }}</dd>
        <dt>阻塞原因</dt>
        <dd>{{ card?.blocking_reason ?? "—" }}</dd>
      </dl>
    </section>
  </aside>
</template>

<style scoped>
.sidebar {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}
.properties {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: var(--space-1) var(--space-3);
  margin: 0;
  font-size: var(--font-xs);
}
.properties dt {
  color: var(--text-muted);
}
.properties dd {
  margin: 0;
  color: var(--text-primary);
  overflow-wrap: anywhere;
}
.execution {
  border-top: 1px solid var(--border-default);
  padding-top: var(--space-3);
}
.disclosure {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  width: 100%;
  padding: 0;
  border: 0;
  background: none;
  color: var(--text-secondary);
  font-size: var(--font-xs);
  font-weight: 600;
  cursor: pointer;
}
/* Marked, not only worded: a block that opened itself should look different from one the
 * reader opened. */
.forced {
  margin: var(--space-2) 0 0;
  border-left: 3px solid var(--attention-warning);
  padding-left: var(--space-2);
  color: var(--text-secondary);
  font-size: var(--font-xs);
}
.execution[data-open="true"] .properties {
  margin-top: var(--space-2);
}
</style>
