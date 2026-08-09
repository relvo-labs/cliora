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
const message = ref<string | null>(null);
const menuFor = ref<string | null>(null);

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

async function move(card: BoardCard, stage: TaskStage): Promise<void> {
  menuFor.value = null;
  if (!props.canWrite || card.stage === stage) return;
  message.value = null;
  optimistic.value = { ...optimistic.value, [card.id]: stage };
  pending.value = card.id;
  try {
    await props.client.updateTask(card.id, { version: card.version, stage });
    emit("changed");
  } catch (error) {
    // Back where it was, always. The message is specific because "操作失敗" leaves
    // the user with nothing to do next.
    const { [card.id]: _moved, ...rest } = optimistic.value;
    optimistic.value = rest;
    message.value = explain(error);
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
  if (card) void move(card, stage);
}
</script>

<template>
  <div class="board">
    <p v-if="message" class="board-message" role="alert" data-board-message>
      {{ message }}
    </p>
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
            :draggable="canWrite"
            @dragstart="dragging = card"
            @dragend="dragging = null"
          >
            <button class="card-open" @click="emit('open', card.id)">
              <span class="ref">{{ card.card_ref }}</span>
              <span class="title">{{ card.title }}</span>
            </button>
            <div class="badges">
              <span class="badge" :data-risk="card.risk">{{ card.risk }}</span>
              <!-- The delivery declaration is inert until V2.3, so it is styled
                   quietly: a loud badge would read as a promise (ADR 0028 sec 9). -->
              <span class="badge muted">{{ card.delivery }}</span>
              <span v-if="card.blocking_count > 0" class="badge blocked">
                阻塞 {{ card.blocking_count }}
              </span>
              <span v-if="card.owner_name" class="badge muted">{{
                card.owner_name
              }}</span>
            </div>
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
  grid-template-columns: repeat(6, minmax(160px, 1fr));
  gap: var(--space-3);
  overflow-x: auto;
}
.lane {
  background: var(--color-surface-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: var(--space-2);
  min-width: 160px;
}
.lane header {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: var(--space-2);
}
.lane h3 {
  font-size: var(--font-size-sm);
  margin: 0;
}
.count {
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
}
/* Over the advisory limit the count changes colour and nothing else happens. */
.count[data-over-wip="true"] {
  color: var(--color-warning);
  font-weight: 600;
}
.lane ul {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.card {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  padding: var(--space-2);
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
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
  display: block;
}
.title {
  font-size: var(--font-size-sm);
}
.badges {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: var(--space-1);
}
.badge {
  font-size: var(--font-size-xs);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  padding: 0 4px;
}
.badge.muted {
  color: var(--color-text-muted);
}
.badge.blocked {
  color: var(--color-warning);
  border-color: var(--color-warning);
}
.menu {
  position: absolute;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  z-index: 2;
}
.move {
  position: relative;
  margin-top: var(--space-1);
}
.board-message {
  border: 1px solid var(--color-warning);
  border-radius: var(--radius-sm);
  padding: var(--space-2);
  margin-bottom: var(--space-2);
}
.empty {
  color: var(--color-text-muted);
  text-align: center;
  margin: var(--space-2) 0 0;
}
</style>
