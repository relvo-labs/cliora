<script setup lang="ts">
// Where a project's code lives (AR-10, ADR 0031 §5).
//
// **Three fields, never a URL**, and the form is shaped that way on purpose rather
// than for tidiness. A "paste your repository URL" box receives
// `https://user:token@github.com/…` on its first day, and that token then lives in the
// database, in `git remote -v`, in the reflog and in error messages. Split into
// scheme / host / path, a credential is **unrepresentable** rather than filtered out —
// and the same shape holds all the way down: the server stores three columns, and the
// wire pattern accepts only a literal `git@` on ssh.
//
// This is also the page a dispatch refusal points at: `PROJECT_NO_REPOSITORY` carries
// a `settings_hint`, because "missing configuration" without saying where is a message
// nobody can act on.
import { onMounted, ref } from "vue";

import { ApiError } from "../../api/client";
import type { ProjectRepository } from "../../api/dto";
import { api } from "../../stores/auth";
import { formatRelative } from "../../utils/time";
import UiButton from "../ui/UiButton.vue";

const props = defineProps<{ projectId: string; canManage: boolean }>();

const repositories = ref<ProjectRepository[]>([]);

/** Relative, not absolute. "3 分鐘前" answers "is sync alive"; a timestamp makes the
 *  reader do the subtraction, and the question here is always about the gap. */
const relative = (iso: string | null): string => formatRelative(iso);
const available = ref(true);
const error = ref<string | null>(null);
const adding = ref(false);

const scheme = ref<"https" | "ssh">("https");
const host = ref("");
const path = ref("");
const defaultBranch = ref("main");

async function load(): Promise<void> {
  try {
    repositories.value = await api().listProjectRepositories(props.projectId);
    available.value = true;
  } catch (caught) {
    // 404 means a flag is off, which is not an error to show.
    if (caught instanceof ApiError && caught.status === 404) {
      available.value = false;
      return;
    }
    error.value =
      caught instanceof Error ? caught.message : "Could not load repositories.";
  }
}

onMounted(() => void load());

async function create(): Promise<void> {
  error.value = null;
  try {
    await api().createProjectRepository(props.projectId, {
      scheme: scheme.value,
      host: host.value.trim(),
      path: path.value.trim().replace(/^\/+|\/+$/g, ""),
      default_branch: defaultBranch.value.trim(),
    });
    adding.value = false;
    host.value = "";
    path.value = "";
    defaultBranch.value = "main";
    await load();
  } catch (caught) {
    // Shown verbatim: the host-allowlist refusal names the host, and the path and
    // branch refusals say exactly which rule they broke.
    error.value =
      caught instanceof Error
        ? caught.message
        : "Could not register the repository.";
  }
}

async function remove(repository: ProjectRepository): Promise<void> {
  error.value = null;
  try {
    await api().deleteProjectRepository(props.projectId, repository.id);
    await load();
  } catch (caught) {
    error.value =
      caught instanceof Error
        ? caught.message
        : "Could not remove the repository.";
  }
}
</script>

<template>
  <div v-if="available">
    <div class="section-head">
      <div>
        <h2>Repositories</h2>
        <span>Canonical code sources available to Agent runs.</span>
      </div>
      <UiButton
        v-if="canManage"
        size="sm"
        :variant="adding ? 'ghost' : 'secondary'"
        @click="adding = !adding"
      >
        {{ adding ? "取消" : "登記 repository" }}
      </UiButton>
    </div>

    <p class="hint">
      Agent 會自己把程式碼拉到它專屬的目錄，所以平台必須知道程式碼在哪裡。
      這不是卡片上的欄位能回答的——它是專案設定。
    </p>

    <p v-if="error" class="error">{{ error }}</p>

    <p v-if="!repositories.length" class="muted">
      還沒有登記任何 repository。需要程式碼的卡片派不出去。
    </p>
    <ul v-else class="repos">
      <li v-for="repository in repositories" :key="repository.id">
        <div class="row">
          <code>{{ repository.url }}</code>
          <span class="muted">預設分支 {{ repository.default_branch }}</span>
          <button v-if="canManage" class="link" @click="remove(repository)">
            移除
          </button>
        </div>
        <!-- **Provider sync's state, and it is here rather than on a dashboard for one
             reason**: a repository that stopped being read looks exactly like one where
             nothing has been merged. This is the only place that difference is visible,
             which is why `provider_sync_error` is a stored column at all (ADR 0043 §5). -->
        <p
          v-if="repository.provider_sync_stopped"
          class="sync stopped"
          :data-repo-sync="repository.id"
        >
          <strong>已停止同步</strong>
          連續三次讀取失敗。{{ repository.provider_sync_error }}
          修正憑證之後會在下一輪重新開始。
        </p>
        <p
          v-else-if="repository.provider_sync_error"
          class="sync failing"
          :data-repo-sync="repository.id"
        >
          最近一次同步失敗：{{ repository.provider_sync_error }}
        </p>
        <p
          v-else-if="repository.provider_synced_at"
          class="sync ok"
          :data-repo-sync="repository.id"
        >
          上次同步
          <time :datetime="repository.provider_synced_at">{{
            relative(repository.provider_synced_at)
          }}</time>
          <template v-if="repository.next_provider_sync_at">
            ・下次
            <time :datetime="repository.next_provider_sync_at">{{
              relative(repository.next_provider_sync_at)
            }}</time>
          </template>
        </p>
        <p v-else class="sync muted" :data-repo-sync="repository.id">
          尚未同步過
        </p>
      </li>
    </ul>

    <!-- Three inputs, and deliberately no fourth that accepts a whole URL. -->
    <form v-if="adding && canManage" class="form" @submit.prevent="create()">
      <label>
        通訊協定
        <select v-model="scheme">
          <option value="https">https</option>
          <option value="ssh">ssh</option>
        </select>
      </label>
      <label>
        主機
        <input v-model="host" placeholder="github.com" required />
      </label>
      <label>
        路徑
        <input v-model="path" placeholder="Lei-k/Traqora" required />
      </label>
      <label>
        預設分支
        <input v-model="defaultBranch" placeholder="main" required />
      </label>
      <p class="hint">
        這裡沒有「貼上完整網址」的欄位，而那是刻意的：一個接受網址的表單第一天就會
        收到夾帶憑證的網址，而那枚憑證會進資料庫、進
        <code>git remote -v</code>、
        進錯誤訊息。拆成三欄之後它<strong>無法被表示</strong>。
      </p>
      <UiButton variant="primary" type="submit">登記</UiButton>
    </form>
  </div>
</template>

<style scoped>
.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
}
.section-head > div {
  display: grid;
  gap: 2px;
}
.section-head h2 {
  margin: 0;
  color: var(--text-primary);
  font-size: var(--font-sm);
}
.section-head span {
  color: var(--text-muted);
  font-size: var(--font-xs);
}
.hint {
  max-width: 78ch;
  margin: var(--space-3) 0 0;
  color: var(--text-muted);
  font-size: var(--font-xs);
  line-height: 1.55;
}
.error {
  color: var(--status-error);
}
/* Three states, three treatments, and **none of them is colour alone** (`research/style.md`
   §顏色以外的辨識線索): each carries its own words, and the stopped one leads with a bold
   label rather than relying on the red. */
.sync {
  margin: 2px 0 0;
  font-size: 12px;
  color: var(--text-muted);
}
.sync.failing {
  color: var(--status-busy);
}
.sync.stopped {
  color: var(--status-error);
}
.repos {
  list-style: none;
  margin: var(--space-3) calc(-1 * var(--space-4)) calc(-1 * var(--space-4));
  padding: 0;
  display: grid;
  font-size: var(--font-sm);
}
.repos li {
  display: flex;
  gap: var(--space-3);
  align-items: center;
  min-height: 46px;
  padding: var(--space-2) var(--space-4);
  border-top: 1px solid var(--border-default);
}
.repos code {
  color: var(--text-primary);
  font-family: var(--font-mono);
  font-size: var(--font-sm);
  font-weight: 600;
}
.repos .link {
  margin-left: auto;
}
.form {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-3);
  margin-top: var(--space-4);
  padding: var(--space-4);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  background: var(--surface-default);
}
.form label {
  display: grid;
  gap: var(--space-1);
  color: var(--text-secondary);
  font-size: var(--font-xs);
  font-weight: 600;
}
.form input,
.form select {
  min-height: 36px;
  padding: 0 var(--space-3);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  color: var(--text-primary);
  background: var(--surface-elevated);
}
.form .hint {
  grid-column: 1 / -1;
  margin: 0;
}
.form > button {
  justify-self: start;
}
.muted {
  color: var(--text-muted);
  font-size: var(--font-xs);
}
@media (max-width: 700px) {
  .form {
    grid-template-columns: 1fr;
  }
  .repos li {
    align-items: flex-start;
    flex-direction: column;
  }
  .repos .link {
    margin-left: 0;
  }
}
</style>
