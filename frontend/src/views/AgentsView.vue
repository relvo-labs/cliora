<script setup lang="ts">
// The Agents page (AR-10, ADR 0029/0031).
//
// Two things on this page are copy rather than data, and both are here because writing
// them once in a document was not enough:
//
//  * **the authorization posture.** V2.2 has no project↔agent binding, so any enrolled
//    node's runner can claim any project's card and pull any project's code. That is a
//    decision, not a defect, and it is stated next to the list — otherwise it gets
//    filed as a bug. The same sentence appears in ADR 0029 and in `rbac.py`.
//  * **the isolation posture.** `dedicated` is the one condition of "dedicated runner
//    node" the platform can check. A node without it also serves interactive sessions,
//    and an agent running there **can read those directories** — the platform does not
//    prevent that. Saying so turns mixed use into a visible choice instead of an
//    unnoticed fact.
import { computed, onMounted, ref } from "vue";

import { ApiError } from "../api/client";
import { ACTION_AGENT_MANAGE } from "../api/dto";
import type { AgentRunner } from "../api/dto";
import AsyncState from "../components/common/AsyncState.vue";
import AppLayout from "../components/layout/AppLayout.vue";
import BaseBadge from "../components/ui/BaseBadge.vue";
import DataTable from "../components/ui/DataTable.vue";
import PageHead from "../components/ui/PageHead.vue";
import { useAsyncResource } from "../composables/useAsyncResource";
import { api, useAuthStore } from "../stores/auth";
import { formatBytes } from "../utils/bytes";
import { formatInstant } from "../utils/time";

const auth = useAuthStore();
const canManage = computed(() => auth.hasPermission(ACTION_AGENT_MANAGE));

const agents = ref<AgentRunner[]>([]);
const actionError = ref<string | null>(null);

const resource = useAsyncResource(
  async () => {
    agents.value = await api().listAgents();
    return agents.value;
  },
  { isEmpty: (list) => list.length === 0 },
);

// A 404 here means the deployment has one of the two flags off, which is a different
// thing from "there are no agents" and gets different words.
const featureUnavailable = computed(
  () =>
    resource.error.value instanceof ApiError &&
    resource.error.value.status === 404,
);
const displayState = computed(() =>
  featureUnavailable.value ? "empty" : resource.state.value,
);

onMounted(() => resource.run());

// The three states, and why they are three.
//
// A runner with no capacity says so by **not polling** — there is no "capacity: 0"
// frame — so from Central a full runner, a runner with nowhere to put a checkout and a
// machine that has been unplugged are all the same silence. Only the node can tell them
// apart, and it reports which on its heartbeat.
//
// So this returns a different sentence for each, and none of them is 「離線」 unless the
// node really is gone. Showing a healthy-but-full machine as offline sends somebody to
// look for a network fault that is not there.
function availability(agent: AgentRunner): {
  tone: "on" | "off" | "busy";
  label: string;
} {
  if (!agent.online) {
    return { tone: "off", label: "離線" };
  }
  switch (agent.blocked_reason) {
    case "disk_quota":
    case "disk_low":
      return { tone: "busy", label: `磁碟用盡（${diskUsage(agent)}）` };
    case "at_capacity":
      return {
        tone: "busy",
        label: `滿載（${agent.active_runs} / ${agent.max_concurrent}）`,
      };
    case "waiting_limit":
      return {
        tone: "busy",
        label: `等待回覆的卡片已滿（${agent.waiting_runs} / ${agent.max_waiting}）`,
      };
    default:
      return { tone: "on", label: "線上" };
  }
}

// Both figures or neither. "4.8 GB" on its own does not say whether that is a lot, and
// a runner that could not measure its own directory must not be shown a number it did
// not report.
function diskUsage(agent: AgentRunner): string {
  if (agent.disk_used_bytes === null || agent.disk_quota_bytes === null) {
    return "用量未回報";
  }
  return `${formatBytes(agent.disk_used_bytes)} / ${formatBytes(agent.disk_quota_bytes)}`;
}

async function setEnabled(agent: AgentRunner, enabled: boolean): Promise<void> {
  actionError.value = null;
  try {
    const updated = await api().updateAgent(agent.id, { enabled });
    agents.value = agents.value.map((item) =>
      item.id === updated.id ? updated : item,
    );
  } catch (error) {
    actionError.value =
      error instanceof Error ? error.message : "Could not update the agent.";
  }
}
</script>

<template>
  <AppLayout>
    <PageHead>
      <template #title>Agents</template>
      <template #subtitle
        >Nodes that can run a card's work unattended.</template
      >
      <template #actions>
        <button
          class="ghost"
          :disabled="resource.state.value === 'loading'"
          @click="resource.run()"
        >
          Refresh
        </button>
      </template>
    </PageHead>

    <!-- Stated on the page, not only in an ADR: this is the kind of design that gets
         reported as a bug when it is written down only once. -->
    <p class="posture">
      本階段的授權邊界是<strong>節點納管</strong>：任何一台已納管節點上的 Agent
      都能領取任何專案的卡片、取得任何專案的程式碼。逐專案的授權自 V2.3 起提供。
      納管本身是管理者專屬的動作。
    </p>

    <AsyncState
      v-if="displayState === 'loading' || displayState === 'idle'"
      state="loading"
    >
      Loading agents.
    </AsyncState>
    <AsyncState v-else-if="displayState === 'forbidden'" state="forbidden">
      You do not have permission to view agents.
    </AsyncState>
    <AsyncState v-else-if="displayState === 'error'" state="error">
      Could not load agents.
      <button class="link" @click="resource.run()">Retry</button>
    </AsyncState>
    <!-- Two different empty states, because the useful next step differs: one is a
         deployment that never switched the feature on, the other is a fleet where no
         node has registered yet. -->
    <AsyncState
      v-else-if="displayState === 'empty' && featureUnavailable"
      state="empty"
    >
      這個部署沒有啟用 Agent 執行。
    </AsyncState>
    <AsyncState v-else-if="displayState === 'empty'" state="empty">
      還沒有任何節點註冊成 Agent Runner。節點需要 agentd 0.9.0
      以上，並且在設定中開啟 runner 模式。
    </AsyncState>
    <div v-else>
      <p v-if="actionError" class="error">{{ actionError }}</p>

      <DataTable>
        <thead>
          <tr>
            <th>Agent 與執行容量</th>
          </tr>
        </thead>
        <tbody class="agents">
          <tr v-for="agent in agents" :key="agent.id" class="agent">
            <td>
              <div class="row">
                <h2>{{ agent.name }}</h2>
                <span :class="['status', availability(agent).tone]">
                  {{ availability(agent).label }}
                </span>
                <span v-if="!agent.enabled" class="status off">已停用</span>
              </div>

              <p class="node">節點 {{ agent.node_name }}</p>

              <!-- The isolation posture, in the two shapes it can take. The warning is
               deliberately specific about what it means: a vague "mixed use" would be
               read as a style note rather than as "an agent can read those files". -->
              <p v-if="agent.dedicated" class="posture-ok">
                ✔ 專用 Runner（此節點未設定任何 Allowed Root）
              </p>
              <p v-else class="posture-warn">
                ⚠ 混合用途：此節點同時提供互動式 Session，而在這裡執行的 Agent
                <strong>讀得到那些目錄</strong>。平台沒有阻止這件事；專用的
                Runner 節點不設定任何 Allowed Root。
              </p>

              <dl class="facts">
                <div>
                  <dt>執行環境</dt>
                  <dd>
                    <span v-if="agent.runtimes.length" class="tags">
                      <BaseBadge
                        v-for="runtime in agent.runtimes"
                        :key="runtime"
                        variant="quiet"
                        >{{ runtime }}</BaseBadge
                      >
                    </span>
                    <span v-else class="muted">
                      無——已安裝的 CLI 都偵測不到帶事件流的非互動介面， 所以這個
                      Agent 不會被派到任何卡片。
                    </span>
                  </dd>
                </div>
                <div>
                  <dt>執行中 / 等待回覆</dt>
                  <dd>
                    {{ agent.active_runs }} / {{ agent.max_concurrent }} ·
                    {{ agent.waiting_runs }} / {{ agent.max_waiting }}
                  </dd>
                </div>
                <div>
                  <dt>指定給此 Agent 的卡片</dt>
                  <!-- Separate from occupancy on purpose: a card can name this runner for
                   days without ever producing a run, so a page showing only
                   「執行中」 makes an over-subscribed machine look idle. -->
                  <dd>{{ agent.assigned_cards }}</dd>
                </div>
                <div>
                  <dt>磁碟</dt>
                  <dd>{{ diskUsage(agent) }}</dd>
                </div>
                <div v-if="agent.labels.length">
                  <dt>標籤</dt>
                  <!-- Shown and not compared. Saying so is the honest option: a label the
                   platform ignores would otherwise look like a filter. -->
                  <dd>
                    <span class="tags">
                      <BaseBadge
                        v-for="label in agent.labels"
                        :key="label"
                        variant="quiet"
                        >{{ label }}</BaseBadge
                      >
                    </span>
                    <span class="muted"
                      >labels 目前僅供辨識，不參與資格比對。</span
                    >
                  </dd>
                </div>
                <div>
                  <dt>註冊於</dt>
                  <dd>
                    {{
                      formatInstant(
                        agent.last_registered_at ?? agent.registered_at,
                      )
                    }}
                  </dd>
                </div>
              </dl>

              <div v-if="canManage" class="actions">
                <button
                  v-if="agent.enabled"
                  class="ghost"
                  @click="setEnabled(agent, false)"
                >
                  停用
                </button>
                <button v-else class="primary" @click="setEnabled(agent, true)">
                  啟用
                </button>
              </div>
            </td>
          </tr>
        </tbody>
      </DataTable>
    </div>
  </AppLayout>
</template>

<style scoped>
.posture {
  border-left: 3px solid var(--border-default);
  padding: 0.5rem 0.75rem;
  margin: 0 0 1rem;
  font-size: 0.9rem;
}
.agent {
  background: var(--surface-elevated);
}
.row {
  display: flex;
  align-items: baseline;
  gap: 0.5rem;
}
.row h2 {
  margin: 0;
  font-size: 1.05rem;
}
.status {
  font-size: 0.8rem;
  border-radius: 999px;
  padding: 0.05rem 0.5rem;
}
.status.on {
  color: var(--status-online);
  border: 1px solid var(--status-online);
}
.status.off {
  color: var(--status-offline);
  background: var(--surface-canvas);
}
.status.busy {
  color: var(--status-busy);
  border: 1px solid var(--status-busy);
}
.node {
  margin: 0.25rem 0;
  font-size: 0.85rem;
  opacity: 0.8;
}
.posture-ok,
.posture-warn {
  margin: 0.35rem 0;
  font-size: 0.85rem;
}
.posture-warn {
  border-left: 3px solid var(--status-busy);
  background: var(--surface-default);
  padding: 0.4rem 0.6rem;
  border-radius: 4px;
}
.facts {
  display: grid;
  gap: 0.25rem;
  margin: 0.5rem 0 0;
  font-size: 0.9rem;
}
.facts div {
  display: flex;
  gap: 0.5rem;
}
.facts dt {
  min-width: 9rem;
  opacity: 0.7;
}
.facts dd {
  margin: 0;
}
.muted {
  opacity: 0.65;
}
.actions {
  margin-top: 0.5rem;
}
.error {
  color: var(--status-error);
}
.tags {
  display: inline-flex;
  flex-wrap: wrap;
  gap: var(--space-1);
  margin-right: var(--space-1);
}
</style>
