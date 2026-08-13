<script setup lang="ts">
import { onMounted, ref } from "vue";
import AsyncState from "../components/common/AsyncState.vue";
import StatusBadge from "../components/common/StatusBadge.vue";
import BaseBadge from "../components/ui/BaseBadge.vue";
import DataTable from "../components/ui/DataTable.vue";
import DeliveryBadge from "../components/ui/DeliveryBadge.vue";
import EmptyState from "../components/ui/EmptyState.vue";
import PageHead from "../components/ui/PageHead.vue";
import RiskBadge from "../components/ui/RiskBadge.vue";
import RunBadge from "../components/ui/RunBadge.vue";
import SourceBadge from "../components/ui/SourceBadge.vue";
import StageBadge from "../components/ui/StageBadge.vue";
import UiCard from "../components/ui/UiCard.vue";
import {
  deliveryLabels,
  riskLabels,
  runStatuses,
  sourceLabels,
  taskStages,
} from "../components/ui/labels";
import { useToast } from "../components/ui/useToast";

const states = [
  "idle",
  "loading",
  "success",
  "empty",
  "stale",
  "offline",
  "forbidden",
  "partial",
  "error",
] as const;
const infrastructureStatuses = [
  "connected",
  "reconnecting",
  "disconnected",
  "exited",
  "gap",
];
const tokenGroups = [
  {
    label: "Task stage",
    tokens: taskStages.map((value) => `--stage-${value}`),
  },
  {
    label: "Run",
    tokens: [
      "--run-queued",
      "--run-running",
      "--run-waiting",
      "--run-succeeded",
      "--run-failed",
      "--run-lost",
    ],
  },
  {
    label: "Risk",
    tokens: Object.keys(riskLabels).map((value) => `--risk-${value}`),
  },
  {
    label: "Evidence source",
    tokens: ["--source-machine", "--source-platform", "--source-agent"],
  },
] as const;
const values = ref<Record<string, string>>({});
const toast = useToast();

onMounted(() => {
  const style = getComputedStyle(document.documentElement);
  values.value = Object.fromEntries(
    tokenGroups.flatMap((group) =>
      group.tokens.map((token) => [
        token,
        style.getPropertyValue(token).trim(),
      ]),
    ),
  );
});
</script>

<template>
  <section class="showcase">
    <PageHead>
      <template #title>Semantic token showcase</template>
      <template #subtitle>
        V1 infrastructure health and V2 work vocabulary are deliberately
        separate. Every state keeps a textual label and visible focus treatment.
      </template>
    </PageHead>

    <UiCard>
      <template #header>三種「進行中」</template>
      <div class="compare" data-three-running>
        <div><span>Session 進行中</span><StatusBadge status="online" /></div>
        <div><span>Task 進行中</span><StageBadge stage="implementing" /></div>
        <div><span>Run 執行中</span><RunBadge status="running" /></div>
      </div>
    </UiCard>

    <UiCard>
      <template #header>兩組徽章的邊界</template>
      <div class="boundary">
        <div>
          <h2>基礎設施健康度 · StatusBadge</h2>
          <div class="row">
            <StatusBadge
              v-for="status in infrastructureStatuses"
              :key="status"
              :status="status"
            />
          </div>
        </div>
        <div>
          <h2>工作語彙 · ui/*Badge</h2>
          <div class="row">
            <StageBadge stage="ready" />
            <RunBadge status="waiting_for_input" />
            <RiskBadge risk="high" />
            <DeliveryBadge delivery="artifact" />
            <SourceBadge :source="Object.keys(sourceLabels)[0]" />
          </div>
        </div>
      </div>
    </UiCard>

    <UiCard>
      <template #header>V2 色票</template>
      <DataTable>
        <thead>
          <tr>
            <th>Group</th>
            <th>Token</th>
            <th>Swatch</th>
            <th>Value</th>
          </tr>
        </thead>
        <tbody v-for="group in tokenGroups" :key="group.label">
          <tr v-for="(token, index) in group.tokens" :key="token">
            <td>{{ index === 0 ? group.label : "" }}</td>
            <td>
              <code>{{ token }}</code>
            </td>
            <td>
              <span
                class="swatch"
                :style="{ backgroundColor: values[token] }"
              ></span>
            </td>
            <td>
              <code>{{ values[token] || "…" }}</code>
            </td>
          </tr>
        </tbody>
      </DataTable>
    </UiCard>

    <UiCard>
      <template #header>徽章一覽</template>
      <h2>Stages</h2>
      <div class="row">
        <StageBadge v-for="value in taskStages" :key="value" :stage="value" />
      </div>
      <h2>Runs</h2>
      <div class="row">
        <RunBadge v-for="value in runStatuses" :key="value" :status="value" />
      </div>
      <h2>Risk</h2>
      <div class="row">
        <RiskBadge
          v-for="value in Object.keys(riskLabels)"
          :key="value"
          :risk="value"
        />
      </div>
      <h2>Delivery</h2>
      <div class="row">
        <DeliveryBadge
          v-for="value in Object.keys(deliveryLabels)"
          :key="value"
          :delivery="value"
        />
      </div>
      <h2>Evidence source</h2>
      <div class="row">
        <SourceBadge
          v-for="value in Object.keys(sourceLabels)"
          :key="value"
          :source="value"
        />
      </div>
      <h2>Base fallback</h2>
      <BaseBadge variant="quiet">未知值</BaseBadge>
    </UiCard>

    <UiCard>
      <template #header>版面與回饋原語</template>
      <EmptyState>
        範例空狀態：內容尚未建立。
        <template #action><button class="ghost">安全的下一步</button></template>
      </EmptyState>
      <button
        class="ghost"
        @click="toast.push({ kind: 'success', title: 'ToastHost 正常運作' })"
      >
        顯示 toast
      </button>
    </UiCard>

    <UiCard>
      <template #header>Async states</template>
      <div class="grid">
        <AsyncState v-for="state in states" :key="state" :state="state" />
      </div>
    </UiCard>
  </section>
</template>

<style scoped>
.showcase {
  display: grid;
  max-width: 1180px;
  gap: var(--space-4);
  padding: var(--space-6);
}
.row {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}
.compare,
.boundary {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--space-3);
}
.compare > div {
  display: grid;
  gap: var(--space-2);
  padding: var(--space-3);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
}
.boundary {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}
h2 {
  margin: var(--space-3) 0 var(--space-2);
  color: var(--text-secondary);
  font-size: var(--font-sm);
}
.swatch {
  display: inline-block;
  width: 56px;
  height: 22px;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
}
code {
  font-family: var(--font-mono);
  font-size: var(--font-xs);
}
.grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--space-2);
}
@media (max-width: 850px) {
  .compare,
  .boundary,
  .grid {
    grid-template-columns: 1fr;
  }
}
</style>
