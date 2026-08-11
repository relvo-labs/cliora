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

const props = defineProps<{ projectId: string; canManage: boolean }>();

const repositories = ref<ProjectRepository[]>([]);
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
      <h2>Repositories</h2>
      <button v-if="canManage" class="ghost" @click="adding = !adding">
        {{ adding ? "取消" : "登記 repository" }}
      </button>
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
        <code>{{ repository.url }}</code>
        <span class="muted">預設分支 {{ repository.default_branch }}</span>
        <button v-if="canManage" class="link" @click="remove(repository)">
          移除
        </button>
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
      <button class="primary" type="submit">登記</button>
    </form>
  </div>
</template>

<style scoped>
.section-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 1rem;
}
.hint {
  font-size: 0.85rem;
  opacity: 0.8;
}
.error {
  color: #b3261e;
}
.repos {
  list-style: none;
  padding: 0;
  display: grid;
  gap: 0.3rem;
  font-size: 0.9rem;
}
.repos li {
  display: flex;
  gap: 0.6rem;
  align-items: baseline;
}
.form {
  display: grid;
  gap: 0.5rem;
  max-width: 32rem;
  margin-top: 0.5rem;
}
.form label {
  display: grid;
  gap: 0.2rem;
  font-size: 0.85rem;
}
.muted {
  opacity: 0.65;
}
</style>
