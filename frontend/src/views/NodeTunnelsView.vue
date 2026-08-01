<script setup lang="ts">
// One node's port forwarding: prerequisites, effective policy, settings, tunnels (PG-11).
//
// The first block is the reason this page exists. With three configuration layers, "you
// cannot forward this port" has three possible causes and three different people who can fix
// it, so the page names the layer instead of only showing the outcome. Everything else here
// follows from properties of the provider that were measured rather than assumed (PG-01):
//
//  * the URL is assigned by the provider and **changes on every reconnect** on the free tier,
//    so it is always shown with when it last changed and a warning not to share it;
//  * the free tier embeds the node's public IP in the hostname, which is a disclosure the
//    page has to make before somebody hands the link out;
//  * "rotate password" is really "close and reopen", so its confirmation says the URL may
//    change — the mental model is an edit, the implementation is not;
//  * the one-time password appears in the creation dialog and nowhere else. There is
//    deliberately no copy affordance in the table: only the hash is stored, so a list that
//    offered one would be promising something it cannot deliver.

import { computed, onMounted, onUnmounted, ref } from "vue";
import { useRouter } from "vue-router";

import { ApiError } from "../api/client";
import {
  ACTION_INTEGRATION_MANAGE,
  ACTION_TUNNEL_MANAGE,
  type NodeTunnelPolicy,
  type TunnelDetail,
  type TunnelProtection,
  type TunnelSummary,
} from "../api/dto";
import AsyncState from "../components/common/AsyncState.vue";
import ConfirmDialog from "../components/common/ConfirmDialog.vue";
import ErrorNotice from "../components/common/ErrorNotice.vue";
import AppLayout from "../components/layout/AppLayout.vue";
import { useAsyncResource } from "../composables/useAsyncResource";
import { api, useAuthStore } from "../stores/auth";
import { errorGuidance } from "../utils/errorCatalog";
import { formatInstant, formatRelative } from "../utils/time";

const props = defineProps<{ id: string }>();

const auth = useAuthStore();
const router = useRouter();
const canManage = computed(() => auth.hasPermission(ACTION_TUNNEL_MANAGE));
const canManageIntegration = computed(() =>
  auth.hasPermission(ACTION_INTEGRATION_MANAGE),
);

const policy = ref<NodeTunnelPolicy | null>(null);
const tunnels = ref<TunnelSummary[]>([]);
const resource = useAsyncResource(async () => {
  const [loadedPolicy, loadedTunnels] = await Promise.all([
    api().getNodeTunnelPolicy(props.id),
    api().listTunnels({ node_id: props.id }),
  ]);
  policy.value = loadedPolicy;
  tunnels.value = loadedTunnels;
  syncSettings(loadedPolicy);
  return loadedPolicy;
});

// The integration being off is a state to render, not a failure: the user needs to know why
// the feature is absent, and an Admin needs the way to turn it on.
const integrationDisabled = computed(
  () =>
    resource.error.value instanceof ApiError &&
    resource.error.value.code === "TUNNEL_INTEGRATION_DISABLED",
);

const busy = ref(false);
const actionError = ref<unknown>(null);
const notice = ref("");

// --- per-node settings (writes node_tunnel_settings) ---
const nodeEnabled = ref(true);
const nodePorts = ref("");
const nodeMax = ref<number | null>(null);

function syncSettings(value: NodeTunnelPolicy): void {
  nodeEnabled.value = value.node_enabled;
  nodePorts.value = (value.node_allowed_ports ?? []).join(", ");
  nodeMax.value = value.node_max_tunnels;
}

// The platform-wide list is the ceiling this node's list may only narrow. Checking it here
// keeps the page from sending a request that must fail — the server still refuses it (D17),
// and this is only about not making the user find out by pressing save.
const globalPorts = computed(
  () => policy.value?.allowed_ports.join(", ") ?? "",
);
const settingsError = computed(() => {
  if (nodeMax.value !== null && nodeMax.value < 1) {
    return "隧道上限至少為 1。";
  }
  for (const spec of parseList(nodePorts.value)) {
    if (!/^\d{1,5}(-\d{1,5})?$/.test(spec)) {
      return `「${spec}」不是 port 或範圍（例如 5173 或 3000-3999）。`;
    }
    const [low] = spec.split("-").map(Number);
    if (low < 1024) {
      return "1024 以下的 port 永不轉發，任何一層設定都不能放寬。";
    }
  }
  return "";
});

// --- create form ---
const showCreate = ref(false);
const formPort = ref<number | null>(null);
const formLabel = ref("");
const formProtection = ref<TunnelProtection>("basic");
const formIps = ref("");
const formRewriteHost = ref(false);
const formAcknowledgePublic = ref(false);
const formAcknowledgeThirdParty = ref(false);
// Set when the server answers 422 with `requires_acknowledgement: third_party`, which is how
// the first tunnel on this node asks the creator to read where the traffic goes (D14).
const requiresThirdParty = ref(false);
const created = ref<TunnelDetail | null>(null);
const passwordCopied = ref(false);

const THIRD_PARTY_NOTES = [
  "這個 port 上的流量會經由服務商（Pinggy）的伺服器往返。",
  "服務商可以看到未加密的 HTTP 內容，包括 Cookie 與 Authorization 標頭。",
  "網址由服務商指派；免費方案的網址中會包含這台節點的公網 IP。",
  "僅適合預覽開發中的應用，不適合正式或含敏感資料的服務。",
];

const PROTECTION_LABELS: Record<TunnelProtection, string> = {
  basic: "密碼保護（服務商強制 HTTP Basic，帳密只顯示一次）",
  ipallow: "限制來源 IP",
  public: "不保護（任何拿到網址的人都能存取）",
};

const STATE_LABELS: Record<string, string> = {
  opening: "建立中",
  running: "執行中",
  unavailable: "節點離線",
  failed: "失敗",
  expired: "已到期",
  closed: "已關閉",
};

const confirmAction = ref<{
  kind: "close" | "rotate";
  tunnel: TunnelSummary;
} | null>(null);

const confirmMessage = computed(() => {
  if (confirmAction.value?.kind === "rotate") {
    return "這會重新建立隧道，因此網址可能改變，舊網址將失效。新的帳密只會顯示一次。";
  }
  return "關閉後服務商可能仍需數秒才停止回應：網址的有效性由服務商決定，平台無法讓它立即失效。";
});

function parseList(text: string): string[] {
  return text
    .split(",")
    .map((part) => part.trim())
    .filter((part) => part.length > 0);
}

// 15 seconds, and only while the page is visible: the free tier reassigns the URL about once
// an hour, which is not a frequency worth a push channel (04 §1.2).
let timer: number | null = null;

async function refresh(): Promise<void> {
  try {
    const [loadedPolicy, loadedTunnels] = await Promise.all([
      api().getNodeTunnelPolicy(props.id),
      api().listTunnels({ node_id: props.id }),
    ]);
    policy.value = loadedPolicy;
    tunnels.value = loadedTunnels;
  } catch {
    /* a transient failure keeps the last known state rather than blanking the page */
  }
}

function startPolling(): void {
  if (timer !== null || document.visibilityState !== "visible") {
    return;
  }
  timer = window.setInterval(refresh, 15000);
}

function stopPolling(): void {
  if (timer !== null) {
    window.clearInterval(timer);
    timer = null;
  }
}

function onVisibility(): void {
  if (document.visibilityState === "visible") {
    void refresh();
    startPolling();
  } else {
    stopPolling();
  }
}

onMounted(async () => {
  await resource.run();
  document.addEventListener("visibilitychange", onVisibility);
  startPolling();
});

onUnmounted(() => {
  stopPolling();
  document.removeEventListener("visibilitychange", onVisibility);
});

async function saveSettings(): Promise<void> {
  if (settingsError.value) {
    return;
  }
  busy.value = true;
  actionError.value = null;
  notice.value = "";
  try {
    const ports = parseList(nodePorts.value);
    const updated = await api().updateNodeTunnelSettings(props.id, {
      enabled: nodeEnabled.value,
      ...(ports.length > 0
        ? { allowed_ports: ports }
        : { clear_allowed_ports: true }),
      ...(nodeMax.value === null
        ? { clear_max_tunnels: true }
        : { max_tunnels: nodeMax.value }),
    });
    policy.value = updated;
    syncSettings(updated);
    notice.value = "此節點的埠轉發設定已儲存。";
  } catch (caught) {
    actionError.value = caught;
  } finally {
    busy.value = false;
  }
}

async function create(): Promise<void> {
  if (formPort.value === null) {
    return;
  }
  busy.value = true;
  actionError.value = null;
  notice.value = "";
  try {
    const detail = await api().createTunnel({
      node_id: props.id,
      port: formPort.value,
      protection: formProtection.value,
      label: formLabel.value || undefined,
      allowed_ips:
        formProtection.value === "ipallow"
          ? parseList(formIps.value)
          : undefined,
      rewrite_host: formRewriteHost.value,
      acknowledge_public: formAcknowledgePublic.value,
      acknowledge_third_party: formAcknowledgeThirdParty.value,
    });
    created.value = detail;
    showCreate.value = false;
    requiresThirdParty.value = false;
    formAcknowledgePublic.value = false;
    await refresh();
  } catch (caught) {
    // The 422 that asks for the first-time acknowledgement is not an error to show as one:
    // it is the server asking a question, and the form grows the four statements to answer.
    // Keyed on `details.requires_acknowledgement`, not on the message text, so improving the
    // wording server-side cannot turn this back into a dead end.
    if (
      caught instanceof ApiError &&
      caught.details?.requires_acknowledgement === "third_party"
    ) {
      requiresThirdParty.value = true;
    } else {
      actionError.value = caught;
    }
  } finally {
    busy.value = false;
  }
}

async function runConfirmed(): Promise<void> {
  const pending = confirmAction.value;
  if (!pending) {
    return;
  }
  busy.value = true;
  actionError.value = null;
  try {
    if (pending.kind === "close") {
      await api().closeTunnel(pending.tunnel.id);
      notice.value = "隧道已關閉。";
    } else {
      created.value = await api().rotateTunnelPassword(pending.tunnel.id);
      notice.value = "已以新帳密重新建立隧道；網址可能已改變。";
    }
    confirmAction.value = null;
    await refresh();
  } catch (caught) {
    actionError.value = caught;
    confirmAction.value = null;
  } finally {
    busy.value = false;
  }
}

async function extend(tunnel: TunnelSummary): Promise<void> {
  busy.value = true;
  actionError.value = null;
  try {
    await api().extendTunnel(tunnel.id);
    notice.value = "已延長平台側的存活時間（服務商自己的時限不受影響）。";
    await refresh();
  } catch (caught) {
    actionError.value = caught;
  } finally {
    busy.value = false;
  }
}

async function copy(text: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text);
    passwordCopied.value = true;
  } catch {
    passwordCopied.value = false;
  }
}

function stateLabel(state: string): string {
  return STATE_LABELS[state] ?? state;
}

function failureText(code: string | null): string {
  return code ? errorGuidance(code).nextStep : "";
}

const prereqRows = computed(() => {
  const detail = policy.value?.prereq_detail ?? {};
  return [
    { label: "ssh 用戶端", ok: detail.ssh_available === true },
    { label: "可連線到服務商（對外 443）", ok: detail.egress_ok === true },
    { label: "已釘選服務商主機金鑰", ok: detail.known_hosts_ok === true },
    {
      label: "本機未否決",
      ok: policy.value ? !policy.value.local_veto : false,
    },
  ];
});

// Which layer narrowed each value, so the page can point at the one the reader can change.
const portSource = computed(() => {
  if (!policy.value) return "";
  if (policy.value.local_allowed_ports?.length) {
    return "本機設定（/etc/agentd/config.yaml）也限制了範圍，最終為三層的交集";
  }
  if (policy.value.node_allowed_ports?.length) {
    return "由此節點的平台設定限制";
  }
  return "由整合設定的全域範圍決定";
});
const capSource = computed(() => {
  if (!policy.value) return "";
  const local = policy.value.local_max_tunnels;
  const node = policy.value.node_max_tunnels;
  if (local !== null && (node === null || local <= node)) {
    return "由本機設定限制（平台無法放寬）";
  }
  if (node !== null) {
    return "由此節點的平台設定限制";
  }
  return "由部署的每節點上限決定";
});
</script>

<template>
  <AppLayout>
    <button
      class="back"
      @click="router.push({ name: 'node-detail', params: { id } })"
    >
      ← 回到 Node
    </button>

    <header class="head">
      <div>
        <h1>埠轉發</h1>
        <p>把這台節點上的一個 port 經由服務商轉出去，用於預覽開發中的應用。</p>
      </div>
    </header>

    <AsyncState v-if="resource.state.value === 'loading'" state="loading">
      正在載入埠轉發設定…
    </AsyncState>
    <AsyncState v-else-if="integrationDisabled" state="empty">
      埠轉發整合尚未啟用，因此這台節點無法建立隧道。
      <RouterLink v-if="canManageIntegration" :to="{ name: 'integrations' }">
        前往整合設定啟用
      </RouterLink>
      <span v-else>請聯繫管理員在「整合設定」啟用並填入服務商憑證。</span>
    </AsyncState>
    <AsyncState
      v-else-if="resource.state.value === 'forbidden'"
      state="forbidden"
    >
      你沒有檢視埠轉發的權限（需要 tunnel.view）。
    </AsyncState>
    <ErrorNotice
      v-else-if="resource.state.value === 'error' || !policy"
      :error="resource.error.value"
      @retry="resource.run()"
    />

    <template v-else>
      <ErrorNotice
        v-if="actionError"
        :error="actionError"
        @retry="actionError = null"
      />
      <p v-if="notice" class="notice-line" role="status">{{ notice }}</p>

      <!-- (1) 先決條件與有效政策 -->
      <section class="panel">
        <h2>先決條件與有效政策</h2>
        <ul class="prereq">
          <li v-for="row in prereqRows" :key="row.label">
            <span :class="row.ok ? 'ok' : 'bad'">{{ row.ok ? "✓" : "✕" }}</span>
            {{ row.label }}
          </li>
        </ul>
        <p class="hint">
          <template v-if="policy.reported_at">
            以上為此節點於
            <time :title="formatInstant(policy.reported_at)">{{
              formatRelative(policy.reported_at)
            }}</time>
            的回報。對外連線的檢查每 5 分鐘一次，因此這個值天生會過時。
          </template>
          <template v-else>
            此節點尚未回報埠轉發能力——可能是 agentd 版本過舊。請升級該節點的
            agentd。
          </template>
        </p>

        <p v-if="policy.local_veto" class="inline-error" role="alert">
          此 Node 已在本機停用埠轉發（<code>/etc/agentd/config.yaml</code> 的
          <code>tunnel.enabled: false</code>）。平台無法覆寫，必須由該 Node
          的擁有者解除。
        </p>
        <p v-else-if="!policy.prereq_ok" class="inline-error" role="alert">
          先決條件未齊備，現在建立會失敗。請在該節點執行
          <code>agentd doctor</code>，它會指出缺少哪一項。
        </p>

        <dl>
          <div>
            <dt>可用的 port</dt>
            <dd>
              {{ policy.allowed_ports.join(", ") || "（無）" }}
              <span class="source">— {{ portSource }}</span>
            </dd>
          </div>
          <div>
            <dt>此節點的隧道上限</dt>
            <dd>
              {{ policy.live_tunnel_count }} / {{ policy.max_tunnels }}
              <span class="source">— {{ capSource }}</span>
            </dd>
          </div>
          <div>
            <dt>方案</dt>
            <dd>
              {{
                policy.plan_tier === "pro"
                  ? "付費（固定子網域）"
                  : "免費（60 分鐘、網址每次重連都會變、網址含本機公網 IP）"
              }}
            </dd>
          </div>
        </dl>
      </section>

      <!-- (2) 此節點的平台設定 -->
      <section class="panel">
        <h2>此節點的設定</h2>
        <p class="hint">
          這一層只能比整合設定更窄，也無法覆寫節點本機的否決。全域可用範圍：
          <code>{{ globalPorts || "1024-65535" }}</code
          >。
        </p>
        <div class="row">
          <label class="check">
            <input
              v-model="nodeEnabled"
              type="checkbox"
              :disabled="!canManage"
            />
            <span>此節點參與埠轉發</span>
          </label>
        </div>
        <div class="row">
          <label class="grow">
            <span>允許的 port 範圍（留空＝不額外收窄）</span>
            <input
              v-model="nodePorts"
              type="text"
              :disabled="!canManage"
              placeholder="例如 3000-3999, 5173"
            />
          </label>
          <label>
            <span>隧道上限（留空＝用部署預設）</span>
            <input
              v-model.number="nodeMax"
              type="number"
              min="1"
              max="100"
              :disabled="!canManage"
            />
          </label>
          <button
            type="button"
            class="primary"
            :disabled="busy || !canManage || settingsError !== ''"
            @click="saveSettings()"
          >
            儲存設定
          </button>
        </div>
        <p v-if="settingsError" class="inline-error" role="alert">
          {{ settingsError }}
        </p>
      </section>

      <!-- (3) 清單與建立 -->
      <section class="panel">
        <div class="panel-head">
          <h2>隧道</h2>
          <button
            v-if="canManage"
            type="button"
            class="primary"
            :disabled="!policy.enabled || !policy.prereq_ok"
            @click="showCreate = !showCreate"
          >
            {{ showCreate ? "取消" : "建立隧道" }}
          </button>
        </div>

        <form v-if="showCreate" class="create" @submit.prevent="create()">
          <div class="row">
            <label>
              <span
                >Port（{{
                  policy.allowed_ports.join(", ") || "無可用範圍"
                }}）</span
              >
              <input
                v-model.number="formPort"
                type="number"
                min="1024"
                max="65535"
                required
              />
            </label>
            <label>
              <span>標籤（選填）</span>
              <input v-model="formLabel" type="text" maxlength="128" />
            </label>
            <label>
              <span>保護方式</span>
              <select v-model="formProtection">
                <option
                  v-for="(label, value) in PROTECTION_LABELS"
                  :key="value"
                  :value="value"
                >
                  {{ label }}
                </option>
              </select>
            </label>
          </div>

          <label v-if="formProtection === 'ipallow'" class="grow-label">
            <span>允許的來源 IP／CIDR（以逗號分隔，最多 32 筆）</span>
            <input
              v-model="formIps"
              type="text"
              placeholder="203.0.113.4, 198.51.100.0/24"
            />
          </label>

          <label class="check">
            <input v-model="formRewriteHost" type="checkbox" />
            <span>
              改寫 Host 標頭為 localhost（Vite／Next
              等會擋外部網域的開發伺服器需要； 但這會讓 app
              自己產生的絕對網址指回 loopback）
            </span>
          </label>

          <!-- public 是逐條隧道的決定，所以每次選擇都要再確認一次。 -->
          <div v-if="formProtection === 'public'" class="warn">
            <p>
              不保護的隧道：任何拿到網址的人都能存取這個
              port，且平台無法回答「誰存取過」。
            </p>
            <label class="check">
              <input v-model="formAcknowledgePublic" type="checkbox" />
              <span>我了解並確認要建立不保護的隧道</span>
            </label>
          </div>

          <div v-if="requiresThirdParty" class="warn">
            <p>這是你在這台節點上的第一條隧道，請先確認：</p>
            <ul>
              <li v-for="line in THIRD_PARTY_NOTES" :key="line">{{ line }}</li>
            </ul>
            <label class="check">
              <input v-model="formAcknowledgeThirdParty" type="checkbox" />
              <span>我了解並同意上述內容</span>
            </label>
          </div>

          <button
            type="submit"
            class="primary"
            :disabled="
              busy ||
              formPort === null ||
              (formProtection === 'public' && !formAcknowledgePublic) ||
              (requiresThirdParty && !formAcknowledgeThirdParty)
            "
          >
            建立
          </button>
        </form>

        <AsyncState v-if="tunnels.length === 0" state="empty">
          這台節點目前沒有隧道。
        </AsyncState>
        <table v-else>
          <thead>
            <tr>
              <th>Port</th>
              <th>狀態</th>
              <th>保護</th>
              <th>網址</th>
              <th>平台到期</th>
              <th>服務商時限</th>
              <th>建立者</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="tunnel in tunnels" :key="tunnel.id">
              <td>
                {{ tunnel.port }}
                <div v-if="tunnel.label" class="muted">{{ tunnel.label }}</div>
              </td>
              <td>
                <span :class="['pill', tunnel.state]">{{
                  stateLabel(tunnel.state)
                }}</span>
                <div v-if="tunnel.state_error_code" class="muted">
                  {{ tunnel.state_error_code }} —
                  {{ failureText(tunnel.state_error_code) }}
                </div>
              </td>
              <td>
                {{ tunnel.protection }}
                <div v-if="tunnel.basic_auth_user" class="muted">
                  帳號 {{ tunnel.basic_auth_user }}
                </div>
              </td>
              <td>
                <template v-if="tunnel.url">
                  <!-- D6: a new window is the only presentation. `noopener` keeps the opened
                       page from reaching back into this tab through window.opener. -->
                  <a
                    :href="tunnel.url"
                    target="_blank"
                    rel="noopener noreferrer"
                    >{{ tunnel.url }}</a
                  >
                  <div class="muted">
                    網址由服務商指派，可能變更（已變更
                    {{ tunnel.url_change_count }} 次<template
                      v-if="tunnel.url_updated_at"
                      >，最後更新
                      <time :title="formatInstant(tunnel.url_updated_at)">{{
                        formatRelative(tunnel.url_updated_at)
                      }}</time></template
                    >）
                  </div>
                  <button type="button" class="link" @click="copy(tunnel.url)">
                    複製網址
                  </button>
                </template>
                <span v-else class="muted">尚未取得</span>
              </td>
              <td :title="formatInstant(tunnel.expires_at)">
                {{ formatRelative(tunnel.expires_at) }}
              </td>
              <td :title="formatInstant(tunnel.upstream_expires_at)">
                {{
                  tunnel.upstream_expires_at
                    ? formatRelative(tunnel.upstream_expires_at)
                    : "—"
                }}
              </td>
              <td>{{ tunnel.created_by_username ?? "—" }}</td>
              <td class="ops">
                <button
                  v-if="tunnel.capabilities.can_close"
                  type="button"
                  class="link"
                  :disabled="busy"
                  @click="extend(tunnel)"
                >
                  延長
                </button>
                <button
                  v-if="tunnel.capabilities.can_rotate"
                  type="button"
                  class="link"
                  :disabled="busy"
                  @click="confirmAction = { kind: 'rotate', tunnel }"
                >
                  換密碼
                </button>
                <button
                  v-if="tunnel.capabilities.can_close"
                  type="button"
                  class="link danger"
                  :disabled="busy"
                  @click="confirmAction = { kind: 'close', tunnel }"
                >
                  關閉
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </section>
    </template>

    <!-- The one place a password is ever shown. Closing this dialog is the last chance to
         copy it: only its hash is stored, so nothing can produce it again. -->
    <div v-if="created" class="backdrop" @click.self="created = null">
      <div
        class="dialog"
        role="dialog"
        aria-modal="true"
        aria-label="隧道已建立"
      >
        <h2>隧道已建立</h2>
        <dl>
          <div>
            <dt>網址</dt>
            <dd>
              <a
                v-if="created.url"
                :href="created.url"
                target="_blank"
                rel="noopener noreferrer"
                >{{ created.url }}</a
              >
              <span v-else>尚未取得</span>
            </dd>
          </div>
          <template v-if="created.basic_auth_password">
            <div>
              <dt>帳號</dt>
              <dd>{{ created.basic_auth_user }}</dd>
            </div>
            <div>
              <dt>密碼</dt>
              <dd>
                <code>{{ created.basic_auth_password }}</code>
              </dd>
            </div>
          </template>
        </dl>
        <p class="hint">
          <template v-if="created.basic_auth_password">
            這組帳密只會顯示這一次；平台只保存它的雜湊值。忘記了就用「換密碼」重新建立（網址會改變）。
          </template>
          網址由服務商指派，重連後可能改變；免費方案 60 分鐘後會換一組。
        </p>
        <div class="actions">
          <button
            v-if="created.basic_auth_password"
            type="button"
            class="ghost"
            @click="
              copy(`${created.basic_auth_user}:${created.basic_auth_password}`)
            "
          >
            {{ passwordCopied ? "已複製" : "複製帳密" }}
          </button>
          <button type="button" class="primary" @click="created = null">
            關閉
          </button>
        </div>
      </div>
    </div>

    <ConfirmDialog
      :open="confirmAction !== null"
      :title="confirmAction?.kind === 'rotate' ? '換密碼' : '關閉隧道'"
      :message="confirmMessage"
      :confirm-label="confirmAction?.kind === 'rotate' ? '重新建立' : '關閉'"
      danger
      :busy="busy"
      @confirm="runConfirmed()"
      @cancel="confirmAction = null"
    />
  </AppLayout>
</template>

<style scoped>
.back {
  margin-bottom: 16px;
  padding: 0;
  border: 0;
  background: none;
  color: var(--action-primary);
  font-weight: 600;
}
.head {
  margin-bottom: 20px;
}
.head h1 {
  margin: 0;
  font-size: 24px;
}
.head p {
  margin: 4px 0 0;
  color: var(--text-muted);
  font-size: 13px;
}
.panel {
  margin-bottom: 16px;
  padding: 18px;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  background: var(--surface-elevated);
}
.panel h2 {
  margin: 0 0 12px;
  font-size: 14px;
}
.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}
.panel-head h2 {
  margin: 0;
}
ul.prereq {
  margin: 0 0 10px;
  padding: 0;
  list-style: none;
  display: grid;
  gap: 6px;
  font-size: 13px;
}
ul.prereq .ok {
  color: #1e7b34;
  font-weight: 700;
}
ul.prereq .bad {
  color: var(--status-error);
  font-weight: 700;
}
dl {
  margin: 14px 0 0;
  display: grid;
  gap: 10px;
}
dl div {
  display: flex;
  justify-content: space-between;
  gap: 12px;
}
dt {
  color: var(--text-muted);
  font-size: 12px;
}
dd {
  margin: 0;
  font-size: 13px;
  text-align: right;
}
.source {
  color: var(--text-muted);
  font-size: 12px;
}
.row {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: 12px;
  margin-bottom: 12px;
}
.row label,
.grow-label {
  display: grid;
  gap: 4px;
  font-size: 12px;
}
.row label.grow,
.grow-label {
  flex: 1 1 320px;
}
.row label span,
.grow-label span {
  color: var(--text-muted);
}
.check {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  max-width: 72ch;
  font-size: 13px;
  line-height: 1.5;
}
input,
select {
  padding: 6px 8px;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  background: var(--surface-default);
  color: var(--text-primary);
  font-size: 13px;
}
input[type="text"] {
  min-width: 240px;
}
.primary {
  padding: 8px 14px;
  border: 0;
  border-radius: var(--radius-sm);
  background: var(--action-primary);
  color: var(--text-inverse);
  font-weight: 600;
}
.ghost {
  padding: 8px 14px;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  background: var(--surface-default);
  color: var(--text-secondary);
  font-weight: 600;
}
.create {
  display: grid;
  gap: 12px;
  margin-bottom: 16px;
  padding: 14px;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  justify-items: start;
}
.warn {
  display: grid;
  gap: 8px;
  padding: 12px;
  border: 1px solid var(--border-danger);
  border-radius: var(--radius-sm);
  font-size: 13px;
}
.warn p {
  margin: 0;
}
.warn ul {
  margin: 0;
  padding-left: 20px;
  display: grid;
  gap: 4px;
}
table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
th {
  text-align: left;
  padding: 8px;
  border-bottom: 1px solid var(--border-default);
  color: var(--text-muted);
  font-size: 12px;
  font-weight: 600;
}
td {
  padding: 10px 8px;
  border-bottom: 1px solid var(--border-default);
  vertical-align: top;
}
.muted {
  color: var(--text-muted);
  font-size: 12px;
}
.pill {
  padding: 2px 8px;
  border-radius: 999px;
  background: var(--surface-default);
  font-size: 12px;
  font-weight: 600;
}
.pill.running {
  background: #e6f4ea;
  color: #1e7b34;
}
.pill.failed,
.pill.unavailable {
  background: #f9eaea;
  color: var(--status-error);
}
.ops {
  display: flex;
  flex-direction: column;
  gap: 4px;
  align-items: flex-start;
}
.link {
  padding: 0;
  border: 0;
  background: none;
  color: var(--action-primary);
  font-size: 12px;
  font-weight: 600;
}
.link.danger {
  color: var(--status-error);
}
.hint {
  margin: 0;
  max-width: 72ch;
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.6;
}
.inline-error {
  margin: 8px 0 0;
  max-width: 72ch;
  color: var(--status-error);
  font-size: 12px;
  line-height: 1.6;
}
.notice-line {
  margin: 0 0 16px;
  padding: 10px 12px;
  border-radius: var(--radius-sm);
  background: #e6f4ea;
  color: #1e7b34;
  font-size: 13px;
}
.backdrop {
  position: fixed;
  inset: 0;
  z-index: 10;
  display: grid;
  place-items: center;
  background: rgb(15 20 25 / 45%);
}
.dialog {
  width: min(560px, 92vw);
  padding: 24px;
  border-radius: var(--radius-lg);
  background: var(--surface-elevated);
  box-shadow: 0 20px 60px rgb(15 20 25 / 25%);
}
.dialog h2 {
  margin: 0 0 12px;
  font-size: 16px;
}
.dialog .actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 16px;
}
</style>
