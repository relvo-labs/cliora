<script setup lang="ts">
// Platform integration settings (PG-10, FR-TUNNEL-004, ADR 0022).
//
// One integration exists today (Pinggy port forwarding), and the page is laid out as a list
// with one row so a second one does not require rebuilding it — but there is no abstract
// "integration framework" here. The second one can ask for that when it arrives.
//
// Three things about this screen are security properties rather than styling:
//
//  * There is **no way to show the token**, because the browser never receives it. The
//    credential block renders a fingerprint and a timestamp; there is deliberately no eye
//    icon, because there would be nothing behind it (D19).
//  * With no encryption key on the deployment, the form is **replaced** rather than
//    disabled: an administrator must not fill in a credential that cannot be stored.
//  * Disabling stops new tunnels and does **not** close the ones already running. The
//    confirmation says so with the count, and closing them is a separate button that reports
//    each one — a switch that can half-fail must not look like a switch.

import { computed, onMounted, ref } from "vue";

import { ApiError } from "../api/client";
import {
  ACTION_INTEGRATION_MANAGE,
  type TunnelIntegration,
  type TunnelProtection,
  type TunnelSummary,
  type UpdateTunnelIntegrationInput,
} from "../api/dto";
import UiInlineNotice from "../components/ui/UiInlineNotice.vue";
import UiLoadingState from "../components/ui/UiLoadingState.vue";
import ConfirmDialog from "../components/common/ConfirmDialog.vue";
import ErrorNotice from "../components/common/ErrorNotice.vue";
import AppLayout from "../components/layout/AppLayout.vue";
import { useAsyncResource } from "../composables/useAsyncResource";
import { api, useAuthStore } from "../stores/auth";
import { formatInstant, formatRelative } from "../utils/time";

const auth = useAuthStore();
const canManage = computed(() => auth.hasPermission(ACTION_INTEGRATION_MANAGE));

const resource = useAsyncResource(() => api().getTunnelIntegration());
const settings = computed<TunnelIntegration | null>(() => resource.data.value);

const busy = ref(false);
const actionError = ref<unknown>(null);
const notice = ref("");

// The four statements of the third-party acknowledgement (D14, first of two places). They are
// listed rather than summarized because each one is a separate fact somebody may not have
// known, and the last is the one people assume the platform handles for them.
const ACKNOWLEDGEMENTS = [
  "轉發的流量會經由服務商（Pinggy）的伺服器往返。",
  "服務商可以看到未加密的 HTTP 內容，包括 Cookie 與 Authorization 標頭。",
  "因此這個功能僅適合預覽開發中的應用，不適合正式或含敏感資料的服務。",
  "服務商的訂閱與帳號由你自己持有；平台只保管你貼上的憑證。",
];
const acknowledged = ref(false);

const credentialInput = ref("");
const planDraft = ref<"free" | "pro">("free");
const budgetDraft = ref(8);
const protectionDraft = ref<TunnelProtection>("basic");
const ttlHoursDraft = ref(4);
const portsDraft = ref("");

const confirmDisable = ref(false);
const liveTunnels = ref<TunnelSummary[]>([]);
const closeResults = ref<{ label: string; ok: boolean; detail: string }[]>([]);

const PROTECTION_LABELS: Record<TunnelProtection, string> = {
  basic: "密碼保護（服務商強制 HTTP Basic）",
  ipallow: "限制來源 IP",
  public: "不保護（任何拿到網址的人都能存取）",
};

// A token that has never been stored cannot be validated by the server yet, so the form says
// what will be accepted before the request is made. The rule is not cosmetic: this value is
// concatenated into ssh's `<token>@<host>` argument on the node, where `+` selects a tunnel
// type and `@` selects the host.
const credentialInvalid = computed(
  () =>
    credentialInput.value.length > 0 &&
    !/^[A-Za-z0-9]{8,128}$/.test(credentialInput.value),
);
const planNeedsCredential = computed(
  () => planDraft.value === "pro" && !settings.value?.credential.configured,
);

function syncDrafts(value: TunnelIntegration): void {
  planDraft.value = value.plan_tier;
  budgetDraft.value = value.concurrent_budget;
  protectionDraft.value = value.default_protection;
  ttlHoursDraft.value = Math.round(value.default_ttl_seconds / 3600);
  portsDraft.value = (value.allowed_ports ?? []).join(", ");
}

async function load(): Promise<void> {
  await resource.run();
  if (settings.value) {
    syncDrafts(settings.value);
  }
}

onMounted(load);

function parsePorts(text: string): string[] {
  return text
    .split(",")
    .map((part) => part.trim())
    .filter((part) => part.length > 0);
}

async function apply(
  patch: UpdateTunnelIntegrationInput,
): Promise<TunnelIntegration | null> {
  busy.value = true;
  actionError.value = null;
  notice.value = "";
  try {
    const updated = await api().updateTunnelIntegration(patch);
    resource.data.value = updated;
    syncDrafts(updated);
    return updated;
  } catch (caught) {
    actionError.value = caught;
    return null;
  } finally {
    busy.value = false;
  }
}

async function enable(): Promise<void> {
  const updated = await apply({ enabled: true, acknowledge: true });
  if (updated) {
    notice.value = "埠轉發整合已啟用。";
    acknowledged.value = false;
  }
}

async function askDisable(): Promise<void> {
  // Fetch the live list first: the confirmation has to state how many tunnels keep running,
  // and afterwards the page offers to close exactly those.
  try {
    liveTunnels.value = await api().listTunnels();
  } catch {
    liveTunnels.value = [];
  }
  confirmDisable.value = true;
}

async function disable(): Promise<void> {
  const updated = await apply({ enabled: false });
  confirmDisable.value = false;
  if (updated) {
    notice.value =
      updated.active_tunnel_count > 0
        ? `已停止建立新隧道。目前仍有 ${updated.active_tunnel_count} 條既有隧道在執行，將於到期後結束。`
        : "埠轉發整合已停用。";
  }
}

// Deliberately one request per tunnel with a per-tunnel result. Some of these will fail — a
// tunnel on an offline node cannot be told to close — and a single "closed everything"
// message would be a claim nobody checked.
async function closeAll(): Promise<void> {
  busy.value = true;
  closeResults.value = [];
  for (const tunnel of liveTunnels.value) {
    const label = `${tunnel.node_name ?? tunnel.node_id} :${tunnel.port}`;
    try {
      await api().closeTunnel(tunnel.id);
      closeResults.value.push({ label, ok: true, detail: "已關閉" });
    } catch (caught) {
      closeResults.value.push({
        label,
        ok: false,
        detail: caught instanceof ApiError ? caught.message : "關閉失敗",
      });
    }
  }
  liveTunnels.value = [];
  busy.value = false;
  await load();
}

async function saveCredential(): Promise<void> {
  if (credentialInvalid.value || credentialInput.value.length === 0) {
    return;
  }
  busy.value = true;
  actionError.value = null;
  notice.value = "";
  try {
    const updated = await api().setTunnelCredential({
      token: credentialInput.value,
      plan_tier: planDraft.value,
    });
    resource.data.value = updated;
    syncDrafts(updated);
    // Cleared immediately: the value is of no further use to this page, and leaving it in a
    // bound input keeps it in memory and in the DOM for as long as the tab is open.
    credentialInput.value = "";
    notice.value = `憑證已儲存（指紋 ${updated.credential.fingerprint}）。`;
  } catch (caught) {
    actionError.value = caught;
  } finally {
    busy.value = false;
  }
}

async function clearCredential(): Promise<void> {
  busy.value = true;
  actionError.value = null;
  try {
    const updated = await api().clearTunnelCredential();
    resource.data.value = updated;
    syncDrafts(updated);
    notice.value = "憑證已清除；方案已回到免費版。";
  } catch (caught) {
    actionError.value = caught;
  } finally {
    busy.value = false;
  }
}

async function saveDefaults(): Promise<void> {
  const ports = parsePorts(portsDraft.value);
  const updated = await apply({
    plan_tier: planDraft.value,
    concurrent_budget: budgetDraft.value,
    default_protection: protectionDraft.value,
    default_ttl_seconds: ttlHoursDraft.value * 3600,
    ...(ports.length > 0
      ? { allowed_ports: ports }
      : { clear_allowed_ports: true }),
  });
  if (updated) {
    notice.value = "預設值已儲存。";
  }
}
</script>

<template>
  <AppLayout>
    <header class="head">
      <div>
        <h1>整合設定</h1>
        <p>平台層級的第三方整合。目前只有一項：埠轉發（Pinggy）。</p>
      </div>
    </header>

    <UiLoadingState
      v-if="resource.state.value === 'loading'"
      label="正在載入整合設定"
    />
    <UiInlineNotice
      v-else-if="resource.state.value === 'forbidden'"
      tone="error"
      title="無法存取"
      >只有具備 integration.manage
      的管理者可以檢視或變更整合設定。</UiInlineNotice
    >
    <ErrorNotice
      v-else-if="resource.state.value === 'error' || !settings"
      :error="resource.error.value"
      @retry="load()"
    />

    <template v-else>
      <ErrorNotice
        v-if="actionError"
        :error="actionError"
        @retry="actionError = null"
      />
      <p v-if="notice" class="notice-line" role="status">{{ notice }}</p>

      <!-- 1. 狀態 -->
      <section class="panel">
        <h2>埠轉發（Pinggy）</h2>

        <!-- The whole form is replaced, not disabled: filling in a credential that cannot be
             stored is worse than being told the environment cannot store one. -->
        <UiInlineNotice
          v-if="!settings.secret_key_available"
          tone="error"
          title="載入失敗"
          >此環境未設定憑證加密金鑰，因此無法保存服務商憑證，埠轉發整合無法啟用。
          請部署管理員設定 <code>CLIORA_SECRET_ENCRYPTION_KEY</code>（例如
          <code>openssl rand -base64 32</code>），重啟 Central
          後再回到此頁。</UiInlineNotice
        >

        <template v-else>
          <dl class="status">
            <div>
              <dt>狀態</dt>
              <dd>
                <span :class="['pill', settings.enabled ? 'on' : 'off']">{{
                  settings.enabled ? "已啟用" : "已停用"
                }}</span>
              </dd>
            </div>
            <div>
              <dt>目前存活的隧道</dt>
              <dd>
                {{ settings.active_tunnel_count }} /
                {{ settings.concurrent_budget }}
              </dd>
            </div>
            <div>
              <dt>服務商</dt>
              <dd>{{ settings.provider }}</dd>
            </div>
          </dl>

          <!-- 5. 啟用前的確認（D14 第一處）。停用時不再顯示，因為 acknowledged_at 已存在。 -->
          <div v-if="!settings.enabled" class="enable">
            <template v-if="!settings.acknowledged_at">
              <p class="ack-title">啟用前請確認以下四點：</p>
              <ul class="ack">
                <li v-for="line in ACKNOWLEDGEMENTS" :key="line">{{ line }}</li>
              </ul>
              <label class="check">
                <input v-model="acknowledged" type="checkbox" />
                <span>我了解並同意上述內容</span>
              </label>
            </template>
            <button
              type="button"
              class="primary"
              :disabled="
                busy ||
                (!settings.acknowledged_at && !acknowledged) ||
                !canManage
              "
              @click="enable()"
            >
              啟用埠轉發
            </button>
          </div>
          <div v-else class="enable">
            <button
              type="button"
              class="ghost"
              :disabled="busy || !canManage"
              @click="askDisable()"
            >
              停用埠轉發
            </button>
            <p class="hint">停用只會擋住新建；既有隧道會繼續執行至到期。</p>
          </div>

          <!-- 停用後的第二段動作：把「擋住新的」與「收掉舊的」分開，因為第二件事可能部分失敗。 -->
          <div
            v-if="!settings.enabled && settings.active_tunnel_count > 0"
            class="leftovers"
          >
            <p>
              整合已停用，但仍有
              {{ settings.active_tunnel_count }}
              條既有隧道在執行（將於到期後結束）。
            </p>
            <button
              type="button"
              class="danger"
              :disabled="busy"
              @click="askDisable().then(closeAll)"
            >
              一併關閉全部
            </button>
          </div>
          <ul v-if="closeResults.length" class="results">
            <li v-for="row in closeResults" :key="row.label">
              <span :class="row.ok ? 'ok' : 'bad'">{{
                row.ok ? "✓" : "✕"
              }}</span>
              {{ row.label }} — {{ row.detail }}
            </li>
          </ul>
        </template>
      </section>

      <!-- 2. 憑證 -->
      <section v-if="settings.secret_key_available" class="panel">
        <h2>服務商憑證</h2>
        <p v-if="settings.credential.configured" class="credential-state">
          已設定 · 指紋
          <code>{{ settings.credential.fingerprint }}</code>
          <span v-if="settings.credential.updated_at">
            · 更新於
            <time :title="formatInstant(settings.credential.updated_at)">{{
              formatRelative(settings.credential.updated_at)
            }}</time>
          </span>
        </p>
        <p v-else class="credential-state muted">尚未設定憑證。</p>
        <p class="hint">
          憑證只能寫入，不能讀出：平台加密保存，任何 API
          都不會回傳它，因此此頁只顯示指紋。免費模式可以不設定憑證。
        </p>
        <div class="row">
          <label>
            <span>貼上服務商 token</span>
            <input
              v-model="credentialInput"
              type="password"
              autocomplete="off"
              spellcheck="false"
              placeholder="僅接受英數字，8–128 字元"
            />
          </label>
          <button
            type="button"
            class="primary"
            :disabled="
              busy || credentialInput.length === 0 || credentialInvalid
            "
            @click="saveCredential()"
          >
            儲存憑證
          </button>
          <button
            v-if="settings.credential.configured"
            type="button"
            class="ghost"
            :disabled="busy"
            @click="clearCredential()"
          >
            清除憑證
          </button>
        </div>
        <p v-if="credentialInvalid" class="inline-error" role="alert">
          token 只接受英數字（8–128 字元）。這不是格式潔癖：它會被組進節點上的
          ssh 連線目的地，含
          <code>+</code> 或 <code>@</code> 的值會改變隧道型別或連線對象。
        </p>
      </section>

      <!-- 3. 方案 + 4. 預設值 -->
      <section v-if="settings.secret_key_available" class="panel">
        <h2>方案與預設值</h2>
        <div class="row">
          <label>
            <span>方案</span>
            <select v-model="planDraft">
              <option value="free">免費（free）</option>
              <option value="pro">付費（pro）</option>
            </select>
          </label>
          <p class="hint plan-hint">
            免費：隧道 60 分鐘後由服務商結束，重連後
            <strong>網址會變</strong>，且網址中會包含該節點的公網
            IP。付費：固定子網域、無 60 分鐘上限。
          </p>
        </div>
        <p v-if="planNeedsCredential" class="inline-error" role="alert">
          選擇付費方案前必須先設定憑證，否則服務商會改發一條匿名的免費隧道——那是一個必然失敗的組合。
        </p>

        <div class="row">
          <label>
            <span>併發預算（1–100）</span>
            <input
              v-model.number="budgetDraft"
              type="number"
              min="1"
              max="100"
            />
          </label>
          <p class="hint">
            這是<strong>整個平台同時存活的隧道數</strong>（目前
            {{ settings.active_tunnel_count }} /
            {{ settings.concurrent_budget }}）。
            請依你的方案填寫：超出方案的上限時，新的隧道會踢掉舊的，而不是排隊。
            每台節點的上限不在這裡，而在各節點的埠轉發頁。
          </p>
        </div>

        <div class="row">
          <label>
            <span>預設保護方式</span>
            <select v-model="protectionDraft">
              <option
                v-for="(label, value) in PROTECTION_LABELS"
                :key="value"
                :value="value"
              >
                {{ label }}
              </option>
            </select>
          </label>
          <label>
            <span>預設存活時間（小時）</span>
            <input
              v-model.number="ttlHoursDraft"
              type="number"
              min="1"
              max="24"
            />
          </label>
        </div>

        <div class="row">
          <label class="grow">
            <span>全域允許的 port 範圍</span>
            <input
              v-model="portsDraft"
              type="text"
              placeholder="例如 3000-3999, 5173（留空＝不額外限制，1024 以下永不轉發）"
            />
          </label>
        </div>
        <button
          type="button"
          class="primary"
          :disabled="busy || planNeedsCredential"
          @click="saveDefaults()"
        >
          儲存
        </button>
      </section>
    </template>

    <ConfirmDialog
      :open="confirmDisable"
      title="停用埠轉發"
      :message="
        (settings?.active_tunnel_count ?? 0) > 0
          ? `將停止建立新隧道；目前 ${settings?.active_tunnel_count} 條既有隧道會繼續執行至到期，需另外一併關閉。`
          : '將停止建立新隧道。既有隧道會繼續執行至到期。'
      "
      confirm-label="停用"
      danger
      :busy="busy"
      @confirm="disable()"
      @cancel="confirmDisable = false"
    />
  </AppLayout>
</template>

<style scoped>
.head {
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
.panel {
  margin-bottom: 16px;
  padding: 18px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-panel);
  background: var(--surface-default);
}
.panel h2 {
  margin: 0 0 12px;
  font-size: 14px;
}
dl.status {
  margin: 0 0 16px;
  display: grid;
  gap: 10px;
}
dl.status div {
  display: flex;
  justify-content: space-between;
  gap: 12px;
}
dt {
  color: var(--text-secondary);
  font-size: 12px;
}
dd {
  margin: 0;
  font-size: 13px;
}
.pill {
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
}
.pill.on {
  background: var(--status-success-bg);
  color: var(--status-success-fg);
}
.pill.off {
  background: var(--surface-raised);
  color: var(--text-secondary);
}
.enable {
  display: grid;
  gap: 10px;
  justify-items: start;
  padding-top: 14px;
  border-top: 1px solid var(--border-control);
}
.ack-title {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
}
ul.ack {
  margin: 0;
  padding-left: 20px;
  display: grid;
  gap: 6px;
  font-size: 13px;
  color: var(--text-primary);
}
.check {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
}
.leftovers {
  margin-top: 14px;
  padding: 12px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-panel);
  display: grid;
  gap: 10px;
  justify-items: start;
  font-size: 13px;
}
.leftovers p {
  margin: 0;
}
ul.results {
  margin: 12px 0 0;
  padding: 0;
  list-style: none;
  display: grid;
  gap: 6px;
  font-size: 13px;
}
ul.results .ok {
  color: var(--status-success-fg);
}
ul.results .bad {
  color: var(--status-error-fg);
}
.row {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: 12px;
  margin-bottom: 14px;
}
.row label {
  display: grid;
  gap: 4px;
  font-size: 12px;
}
.row label.grow {
  flex: 1 1 320px;
}
.row label span {
  color: var(--text-secondary);
}
input,
select {
  padding: 6px 8px;
  border: 1px solid var(--border-control);
  border-radius: var(--radius-control);
  background: var(--surface-raised);
  color: var(--text-primary);
  font-size: 13px;
}
input[type="text"],
input[type="password"] {
  min-width: 280px;
}
.primary {
  padding: 8px 14px;
  border: 0;
  border-radius: var(--radius-control);
  background: var(--accent-strong);
  color: var(--text-on-accent);
  font-weight: 600;
}
.ghost,
.danger {
  padding: 8px 14px;
  border: 1px solid var(--border-control);
  border-radius: var(--radius-control);
  background: var(--surface-raised);
  color: var(--text-primary);
  font-weight: 600;
}
.danger {
  border-color: var(--danger-bg);
  color: var(--status-error-fg);
}
.hint {
  margin: 0;
  max-width: 62ch;
  color: var(--text-secondary);
  font-size: 12px;
  line-height: 1.6;
}
.plan-hint {
  flex: 1 1 320px;
}
.credential-state {
  margin: 0 0 8px;
  font-size: 13px;
}
.credential-state.muted {
  color: var(--text-secondary);
}
.inline-error {
  margin: 8px 0 0;
  max-width: 62ch;
  color: var(--status-error-fg);
  font-size: 12px;
  line-height: 1.6;
}
.notice-line {
  margin: 0 0 16px;
  padding: 10px 12px;
  border-radius: var(--radius-panel);
  background: var(--status-success-bg);
  color: var(--status-success-fg);
  font-size: 13px;
}
</style>
