<script setup lang="ts">
/**
 * The six-lane board (TK-09, ADR 0028).
 *
 * **Two ways to move a card, and the menu is the primary one.** HTML5 drag-and-drop is
 * unusable with a keyboard and unreliable under Playwright, so the "移動到…" menu is
 * both the accessible path and the one the e2e suite asserts through; the drag is a
 * convenience layered on top. Shipping only the drag would mean shipping a board some
 * people cannot use and nobody can test reliably.
 *
 * **No drag-and-drop dependency.** `package.json` carries none today, and this needed
 * about forty lines of native events — a library would have been a permanent
 * dependency bought for that.
 *
 * The interaction contract is the part worth reading (`plan/17/07-…md` §2.2):
 * optimistic move → `PATCH` with the version → on **any** refusal, put the card back
 * and say something specific. A card that stays in its new lane after a failure is a
 * card the user believes moved.
 */
import { computed, ref } from "vue";

import { ApiError, type ApiClient } from "../../api/client";
import type { Board, BoardCard, TaskStage } from "../../api/dto";
import BaseBadge from "../ui/BaseBadge.vue";
import DeliveryBadge from "../ui/DeliveryBadge.vue";
import RiskBadge from "../ui/RiskBadge.vue";
import RunBadge from "../ui/RunBadge.vue";
import { useToast } from "../ui/useToast";

const props = defineProps<{
  board: Board;
  client: ApiClient;
  canWrite: boolean;
}>();
const emit = defineEmits<{
  (event: "changed"): void;
  (event: "open", taskId: string): void;
}>();

const dragging = ref<BoardCard | null>(null);
const pending = ref<string | null>(null);
const menuFor = ref<string | null>(null);
const rollback = ref<{ id: string; mode: "drag" | "menu" } | null>(null);
const toast = useToast();
const reduceMotion =
  typeof window.matchMedia === "function" &&
  window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/** Cards the browser has moved but the server has not confirmed. Held separately
 *  from `props.board` so a rollback is "forget this entry" rather than a re-fetch —
 *  the re-fetch happens too, but after the card is already back where it belongs. */
const optimistic = ref<Record<string, TaskStage>>({});

const lanes = computed(() =>
  props.board.lanes.map((lane) => ({
    ...lane,
    cards: props.board.lanes
      .flatMap((source) => source.cards)
      .filter(
        (card) => (optimistic.value[card.id] ?? card.stage) === lane.stage,
      ),
  })),
);

function overWip(lane: {
  wip_suggested: number | null;
  cards: unknown[];
}): boolean {
  return lane.wip_suggested !== null && lane.cards.length > lane.wip_suggested;
}

async function move(
  card: BoardCard,
  stage: TaskStage,
  mode: "drag" | "menu" = "menu",
): Promise<void> {
  menuFor.value = null;
  if (!props.canWrite || card.stage === stage) return;
  optimistic.value = { ...optimistic.value, [card.id]: stage };
  pending.value = card.id;
  try {
    await props.client.updateTask(card.id, { version: card.version, stage });
    toast.push({ kind: "success", title: "卡片已移動" });
    emit("changed");
  } catch (error) {
    // Back where it was, always. The message is specific because "操作失敗" leaves
    // the user with nothing to do next.
    const { [card.id]: _moved, ...rest } = optimistic.value;
    optimistic.value = rest;
    const explanation = explain(error);
    rollback.value = { id: card.id, mode: reduceMotion ? "menu" : mode };
    window.setTimeout(() => {
      if (rollback.value?.id === card.id) rollback.value = null;
    }, 360);
    toast.push({
      kind: "error",
      title: "卡片沒有移動",
      message: explanation,
    });
    emit("changed");
  } finally {
    pending.value = null;
  }
}

function explain(error: unknown): string {
  if (!(error instanceof ApiError)) return "移動失敗，請重試。";
  const details = error.details as { blocking_refs?: string[] } | undefined;
  switch (error.code) {
    case "TASK_VERSION_CONFLICT":
      return "這張卡剛被別人改過，已重新載入。";
    case "TASK_DEPENDENCY_UNSATISFIED":
      return `${(details?.blocking_refs ?? []).join("、")} 尚未完成。`;
    case "PROJECT_ARCHIVED":
      return "這個專案已封存，卡片不能再變更。";
    default:
      return error.message;
  }
}

function onDrop(stage: TaskStage): void {
  const card = dragging.value;
  dragging.value = null;
  if (card) void move(card, stage, "drag");
}

function waitingCopy(card: BoardCard): string | null {
  if (card.active_run_status !== "queued") return null;
  if (card.waiting_reason === "assigned_offline") {
    return `等待指定的 Agent：${card.active_run_runner_name ?? "（未知）"}（目前離線）`;
  }
  if (card.waiting_reason === "no_eligible_runner") return "等待可用的 Agent";
  return "排隊中";
}
</script>

<template>
  <div class="board">
    <div class="lanes">
      <section
        v-for="lane in lanes"
        :key="lane.stage"
        class="lane"
        :data-stage="lane.stage"
        @dragover.prevent
        @drop.prevent="onDrop(lane.stage)"
      >
        <header>
          <h3>{{ lane.label }}</h3>
          <!-- WIP turns colour and refuses nothing: Monstrare's semantics, kept. -->
          <span class="count" :data-over-wip="overWip(lane)">
            {{ lane.cards.length
            }}<template v-if="lane.wip_suggested">
              / {{ lane.wip_suggested }}</template
            >
          </span>
        </header>
        <ul>
          <li
            v-for="card in lane.cards"
            :key="card.id"
            class="card"
            :data-card-ref="card.card_ref"
            :data-pending="pending === card.id"
            :data-human-waiting="
              card.active_run_status === 'waiting_for_input' || undefined
            "
            :class="{
              'rollback-drag':
                rollback?.id === card.id && rollback.mode === 'drag',
              'rollback-menu':
                rollback?.id === card.id && rollback.mode === 'menu',
            }"
            :draggable="canWrite"
            @dragstart="dragging = card"
            @dragend="dragging = null"
          >
            <div
              v-if="card.active_run_status === 'waiting_for_input'"
              class="human-waiting"
            >
              <span aria-hidden="true"></span>
              等待你的回覆
            </div>
            <button class="card-open" @click="emit('open', card.id)">
              <span class="ref">{{ card.card_ref }}</span>
              <span class="title">{{ card.title }}</span>
            </button>
            <div class="badges">
              <RiskBadge :risk="card.risk" />
              <DeliveryBadge :delivery="card.delivery" />
              <BaseBadge
                v-if="card.blocking_count > 0"
                variant="outline"
                tone="risk-medium"
              >
                阻塞 {{ card.blocking_count }}
              </BaseBadge>
              <RunBadge
                v-if="card.active_run_status"
                :status="card.active_run_status"
                :runner-name="card.active_run_runner_name"
              />
            </div>
            <p v-if="waitingCopy(card)" class="waiting-copy">
              {{ waitingCopy(card) }}
            </p>
            <p class="assignment">
              {{
                card.active_run_runner_name
                  ? `指定 ${card.active_run_runner_name}`
                  : "任一 Agent"
              }}<template v-if="card.owner_name">
                · {{ card.owner_name }}</template
              >
            </p>
            <div v-if="canWrite" class="move">
              <button
                class="ghost"
                :aria-expanded="menuFor === card.id"
                :data-move-for="card.card_ref"
                @click="menuFor = menuFor === card.id ? null : card.id"
              >
                移動到…
              </button>
              <ul v-if="menuFor === card.id" class="menu">
                <li v-for="target in board.lanes" :key="target.stage">
                  <button
                    :disabled="target.stage === card.stage"
                    :data-move-to="target.stage"
                    @click="move(card, target.stage)"
                  >
                    {{ target.label }}
                  </button>
                </li>
              </ul>
            </div>
          </li>
        </ul>
        <p v-if="lane.cards.length === 0" class="empty">—</p>
      </section>
    </div>
  </div>
</template>

<style scoped>
.lanes {
  display: grid;
  grid-template-columns: repeat(6, minmax(224px, 1fr));
  gap: var(--space-3);
  padding: 1px 1px var(--space-2);
  overflow-x: auto;
  scrollbar-width: thin;
}
.lane {
  position: relative;
  overflow: hidden;
  background: var(--surface-default);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  padding: var(--space-3);
  min-width: 224px;
  min-height: 430px;
}
.lane::before {
  position: absolute;
  inset: 0 auto 0 0;
  width: 3px;
  content: "";
  background: var(--stage-backlog);
}
.lane[data-stage="blocked"]::before {
  background: var(--stage-blocked);
}
.lane[data-stage="ready"]::before {
  background: var(--stage-ready);
}
.lane[data-stage="implementing"]::before {
  background: var(--stage-implementing);
}
.lane[data-stage="verify"]::before {
  background: var(--stage-verify);
}
.lane[data-stage="done"]::before {
  background: var(--stage-done);
}
.lane header {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: var(--space-3);
  padding-left: var(--space-1);
}
.lane h3 {
  font-size: var(--font-sm);
  font-weight: 700;
  letter-spacing: 0.01em;
  margin: 0;
}
.count {
  min-width: 24px;
  padding: 2px 6px;
  border-radius: 999px;
  text-align: center;
  font-size: var(--font-xs);
  color: var(--text-muted);
  background: var(--surface-canvas);
}
/* Over the advisory limit the count changes colour and nothing else happens. */
.count[data-over-wip="true"] {
  color: var(--status-busy);
  font-weight: 600;
}
.lane ul {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}
.card {
  position: relative;
  overflow: hidden;
  background: var(--surface-elevated);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  padding: var(--space-3);
  box-shadow: 0 1px 2px color-mix(in srgb, var(--text-primary) 5%, transparent);
  transition:
    border-color 0.14s ease,
    transform 0.14s ease,
    box-shadow 0.14s ease;
}
.card:hover {
  border-color: color-mix(
    in srgb,
    var(--action-primary) 42%,
    var(--border-default)
  );
  box-shadow: 0 4px 12px color-mix(in srgb, var(--text-primary) 7%, transparent);
  transform: translateY(-1px);
}
.card[data-human-waiting="true"] {
  border-color: var(--run-waiting);
  box-shadow:
    0 0 0 1px var(--run-waiting),
    0 2px 10px color-mix(in srgb, var(--run-waiting) 18%, transparent);
}
.human-waiting {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  margin: calc(-1 * var(--space-3)) calc(-1 * var(--space-3)) var(--space-3);
  padding: 6px var(--space-3);
  color: var(--text-inverse);
  background: var(--run-waiting);
  font-size: var(--font-xs);
  font-weight: 700;
}
.human-waiting span {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
  animation: human-pulse 1.35s ease-in-out infinite;
}
.card[data-pending="true"] {
  opacity: 0.6;
}
.card-open {
  display: block;
  width: 100%;
  text-align: left;
  background: none;
  border: none;
  padding: 0;
  cursor: pointer;
  color: inherit;
}
.ref {
  font-family: var(--font-mono);
  font-size: var(--font-xs);
  color: var(--text-muted);
  display: block;
  margin-bottom: var(--space-1);
}
.title {
  display: block;
  min-height: 36px;
  font-size: var(--font-base);
  font-weight: 600;
  line-height: 1.4;
}
.badges {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: var(--space-2);
}
.waiting-copy,
.assignment {
  margin: var(--space-1) 0 0;
  color: var(--text-muted);
  font-size: var(--font-xs);
  line-height: 1.35;
}
.waiting-copy {
  color: var(--text-secondary);
  font-weight: 600;
}
.menu {
  position: absolute;
  background: var(--surface-elevated);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  z-index: 2;
}
.move {
  position: relative;
  margin-top: var(--space-2);
  padding-top: var(--space-2);
  border-top: 1px solid var(--border-default);
}
.empty {
  color: var(--text-muted);
  text-align: center;
  margin: var(--space-2) 0 0;
}
@keyframes rollback-shake {
  25% {
    transform: translateX(-5px);
  }
  50% {
    transform: translateX(5px);
  }
  75% {
    transform: translateX(-3px);
  }
}
@keyframes rollback-flash {
  50% {
    outline: 2px solid var(--status-error);
    outline-offset: 1px;
  }
}
@keyframes human-pulse {
  50% {
    opacity: 0.3;
    transform: scale(0.72);
  }
}
.rollback-drag {
  animation: rollback-shake 0.32s ease;
}
.rollback-menu {
  animation: rollback-flash 0.32s ease;
}
@media (prefers-reduced-motion: reduce) {
  .card {
    transition: none;
  }
  .card:hover {
    transform: none;
  }
  .rollback-drag,
  .rollback-menu {
    animation-name: rollback-flash;
  }
  .human-waiting span {
    animation: none;
  }
}
</style>
