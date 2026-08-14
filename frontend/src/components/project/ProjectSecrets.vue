<script setup lang="ts">
// A project's secrets (SC-08, ADR 0032).
//
// Four things on this page are decisions rather than layout, and each one is here
// because it would otherwise be quietly undone:
//
//  * **There is no "show value" and no "copy".** Not because it would be hard — because
//    no API returns a value, and a button implying otherwise would teach that the
//    platform keeps a readable copy somewhere.
//  * **The master-key warning is on the page**, not in a runbook. A database backup
//    cannot restore a secret without the key, and the moment somebody needs to know
//    that is before they type one in.
//  * **Deleting says what it does not do.** Cliora does not know what that token is
//    called at GitHub, so "deleted" must not read as "revoked".
//  * **The allowlist and the secrets are two lists, shown as two.** A name can be
//    allowed and not yet created — a card may declare it, and dispatch will say so.
import { computed, onMounted, ref } from "vue";

import { ApiError } from "../../api/client";
import type { ProjectSecret, SecretKind } from "../../api/dto";
import { api } from "../../stores/auth";
import EmptyState from "../ui/EmptyState.vue";
import UiButton from "../ui/UiButton.vue";
import { formatInstant } from "../../utils/time";

const props = defineProps<{
  projectId: string;
  /** Whether this deployment delivers git credentials at all. Off by default: at this
   *  stage git authentication is the node owner's manual configuration (2026-08-13
   *  ruling). The two git kinds are then **disabled and explained**, never hidden —
   *  hiding them turns "can this platform manage git credentials" into a question
   *  somebody has to ask a person. */
  gitDeliveryEnabled?: boolean;
}>();

const secrets = ref<ProjectSecret[]>([]);
const loading = ref(true);
const error = ref<string | null>(null);

const adding = ref(false);
const name = ref("");
const kind = ref<SecretKind>("env");
const value = ref("");
const rotating = ref<ProjectSecret | null>(null);
const confirmingDelete = ref<ProjectSecret | null>(null);
const busy = ref(false);

const gitEnabled = computed(() => props.gitDeliveryEnabled === true);

const KIND_LABELS: Record<SecretKind, string> = {
  env: "env — 一般環境變數，會進 Agent 的執行環境",
  git_pat: "git_pat — Git 的 personal access token",
  git_ssh_key: "git_ssh_key — Git 的 SSH 私鑰",
  provider_token: "provider_token — 平台建立合併請求時使用（不下放到節點）",
};

async function load(): Promise<void> {
  loading.value = true;
  error.value = null;
  try {
    secrets.value = await api().listSecrets(props.projectId);
  } catch (err) {
    error.value =
      err instanceof ApiError ? err.message : "Could not load the secrets.";
  } finally {
    loading.value = false;
  }
}

onMounted(load);

function reset(): void {
  adding.value = false;
  rotating.value = null;
  name.value = "";
  kind.value = "env";
  value.value = "";
}

async function submit(): Promise<void> {
  busy.value = true;
  error.value = null;
  try {
    if (rotating.value) {
      await api().rotateSecret(props.projectId, rotating.value.id, value.value);
    } else {
      await api().createSecret(props.projectId, {
        name: name.value.trim(),
        kind: kind.value,
        value: value.value,
      });
    }
    reset();
    await load();
  } catch (err) {
    // Shown verbatim: every refusal here names the thing to change — a reserved name,
    // a kind this deployment does not deliver, a value larger than a secret should be.
    error.value =
      err instanceof ApiError ? err.message : "Could not save the secret.";
  } finally {
    busy.value = false;
  }
}

async function remove(): Promise<void> {
  if (!confirmingDelete.value) return;
  busy.value = true;
  try {
    await api().deleteSecret(props.projectId, confirmingDelete.value.id);
    confirmingDelete.value = null;
    await load();
  } catch (err) {
    error.value =
      err instanceof ApiError ? err.message : "Could not delete the secret.";
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <section class="secrets">
    <header>
      <h3>機密</h3>
      <UiButton
        v-if="!adding && !rotating"
        variant="secondary"
        @click="adding = true"
        >＋ 新增機密</UiButton
      >
    </header>

    <!-- On the page, not in a runbook. A database backup cannot restore a secret
         without the master key, and the moment to know that is before typing one in. -->
    <p class="warn">
      ⚠
      主金鑰遺失時，這裡的所有機密都<strong>不可復原</strong>，只能全部重建。請把金鑰與資料庫備份分開保管。
    </p>

    <p v-if="error" class="error">{{ error }}</p>

    <p v-if="loading" class="muted">載入中…</p>
    <EmptyState v-else-if="!secrets.length && !adding">
      這個專案還沒有任何機密。
    </EmptyState>
    <table v-else-if="secrets.length" class="rows">
      <thead>
        <tr>
          <th>名稱</th>
          <th>類型</th>
          <th>最後使用</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="secret in secrets" :key="secret.id">
          <td>
            <code>{{ secret.name }}</code>
          </td>
          <td class="muted">{{ secret.kind }}</td>
          <!-- The most useful column: it separates a live credential from one nothing
               has touched. "Never used" is quiet rather than alarming — a secret
               created a minute ago has not been used either. -->
          <td class="muted">
            {{
              secret.last_used_at
                ? formatInstant(secret.last_used_at)
                : "從未使用"
            }}
          </td>
          <td class="actions">
            <UiButton
              variant="ghost"
              @click="
                rotating = secret;
                value = '';
              "
              >輪替</UiButton
            >
            <UiButton variant="ghost" @click="confirmingDelete = secret"
              >刪除</UiButton
            >
          </td>
        </tr>
      </tbody>
    </table>

    <form v-if="adding || rotating" class="form" @submit.prevent="submit">
      <template v-if="!rotating">
        <label>
          <span>名稱</span>
          <input v-model="name" placeholder="GITHUB_TOKEN" required />
          <small class="muted"
            >大寫字母、數字與底線；它會變成一個環境變數。</small
          >
        </label>
        <label>
          <span>類型</span>
          <select v-model="kind">
            <option value="env">{{ KIND_LABELS.env }}</option>
            <!-- ⊘ rather than hidden: disabling with a reason answers both "can this
                 platform do it" and "why not here" (2026-08-13 ruling). -->
            <option value="git_pat" :disabled="!gitEnabled">
              {{ KIND_LABELS.git_pat
              }}{{ gitEnabled ? "" : " ⊘ 此部署未啟用平台管理的 git 憑證" }}
            </option>
            <option value="git_ssh_key" :disabled="!gitEnabled">
              {{ KIND_LABELS.git_ssh_key
              }}{{ gitEnabled ? "" : " ⊘ 此部署未啟用平台管理的 git 憑證" }}
            </option>
            <option value="provider_token">
              {{ KIND_LABELS.provider_token }}
            </option>
          </select>
        </label>
      </template>
      <p v-else class="muted">
        輪替 <code>{{ rotating.name }}</code> —— 只覆寫值，名稱與類型不變。
      </p>

      <label>
        <span>值</span>
        <input v-model="value" type="password" required />
        <small class="muted">送出後即不可見。沒有任何介面能把它讀回來。</small>
      </label>

      <!-- The per-kind guidance, and the numbers in it are measured rather than
           adjectives (M-SC-1): an ed25519 key is 399 bytes and an RSA-4096 one is
           3 369, which is 41% of a single secret's whole budget. -->
      <p v-if="kind === 'git_pat'" class="hint">
        最小權限：<code>Contents: Read and write</code>；若同一枚要開 PR 再加
        <code>Pull requests: Read and write</code>。<strong
          >指定 repository 而不是 all</strong
        >，並<strong>設定到期日</strong>。
      </p>
      <p v-else-if="kind === 'git_ssh_key'" class="hint">
        貼上私鑰全文（含 <code>-----BEGIN</code>）。<strong
          >建議用 ed25519</strong
        >：它是 399 bytes，而 RSA-4096 是 3 369 bytes，佔掉單一機密預算的四成。
      </p>
      <p v-else-if="kind === 'provider_token'" class="hint">
        本階段<strong>不會下放它</strong>；它的用途是開 PR（V2.4）。
      </p>
      <p v-else class="hint">
        這個值會出現在 Agent 的執行環境裡。<strong
          >git 憑證請不要用這個類型</strong
        >——那會讓 Agent 拿到平台的憑證。
      </p>

      <div class="actions">
        <UiButton type="submit" :disabled="busy">儲存</UiButton>
        <UiButton variant="ghost" type="button" @click="reset">取消</UiButton>
      </div>
    </form>

    <div v-if="confirmingDelete" class="confirm">
      <p>
        刪除 <code>{{ confirmingDelete.name }}</code
        >？
      </p>
      <!-- Without this sentence, "deleted" reads as "revoked" — and Cliora does not
           know what that token is called at its provider. -->
      <p class="warn">
        刪除只讓平台<strong>不再下放</strong>這枚機密。<strong>請另外到來源系統（GitHub／npm…）撤銷它。</strong>進行中的執行不受影響。
      </p>
      <div class="actions">
        <UiButton :disabled="busy" @click="remove">刪除</UiButton>
        <UiButton variant="ghost" @click="confirmingDelete = null"
          >取消</UiButton
        >
      </div>
    </div>
  </section>
</template>

<style scoped>
.secrets {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
}

h3 {
  margin: 0;
  font-size: var(--font-md);
  color: var(--text-primary);
}

.warn {
  margin: 0;
  padding: var(--space-2) var(--space-3);
  border-left: 3px solid var(--risk-medium);
  background: var(--surface-canvas);
  color: var(--text-secondary);
  font-size: var(--font-sm);
}

.error {
  margin: 0;
  color: var(--status-error);
  font-size: var(--font-sm);
}

.muted {
  color: var(--text-muted);
  font-size: var(--font-sm);
}

.rows {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--font-sm);
}

.rows th {
  text-align: left;
  color: var(--text-muted);
  font-weight: 500;
  padding-bottom: var(--space-1);
}

.rows td {
  padding: var(--space-2) 0;
  border-top: 1px solid var(--border-default);
  vertical-align: top;
}

.form {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding: var(--space-3);
  background: var(--surface-canvas);
  border-radius: var(--radius-md);
}

.form label {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  font-size: var(--font-sm);
  color: var(--text-secondary);
}

.hint {
  margin: 0;
  color: var(--text-secondary);
  font-size: var(--font-sm);
}

.actions {
  display: flex;
  gap: var(--space-2);
}

.confirm {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding: var(--space-3);
  border: 1px solid var(--status-error);
  border-radius: var(--radius-md);
}
</style>
