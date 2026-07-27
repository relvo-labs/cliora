<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import { ApiError } from "../api/client";
import { useAuthStore } from "../stores/auth";

const auth = useAuthStore();
const route = useRoute();
const router = useRouter();

const username = ref("");
const password = ref("");
const error = ref("");
const loading = ref(false);
const usernameField = ref<HTMLInputElement | null>(null);

onMounted(() => usernameField.value?.focus());

function safeRedirect(): string {
  const target = route.query.redirect;
  // Only same-origin absolute paths; never protocol-relative (//host) targets.
  if (
    typeof target === "string" &&
    target.startsWith("/") &&
    !target.startsWith("//")
  ) {
    return target;
  }
  // The landing page (P4-08); `/` redirects here too.
  return "/dashboard";
}

async function submit(): Promise<void> {
  if (loading.value) {
    return;
  }
  loading.value = true;
  error.value = "";
  try {
    await auth.login(username.value, password.value);
    await router.push(safeRedirect());
  } catch (caught) {
    // Never reveal whether the account exists (FR-AUTH-001).
    error.value =
      caught instanceof ApiError
        ? "Invalid username or password."
        : "Unable to sign in. Please try again.";
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <div class="login">
    <form class="card" @submit.prevent="submit">
      <div class="brand"><span aria-hidden="true">◫</span>Cliora</div>
      <h1>Sign in</h1>
      <p class="sub">Access the node control plane.</p>

      <label>
        Username
        <input
          ref="usernameField"
          v-model="username"
          name="username"
          autocomplete="username"
          required
        />
      </label>
      <label>
        Password
        <input
          v-model="password"
          name="password"
          type="password"
          autocomplete="current-password"
          required
        />
      </label>

      <p v-if="error" class="error" role="alert">{{ error }}</p>

      <button class="primary" type="submit" :disabled="loading">
        {{ loading ? "Signing in…" : "Sign in" }}
      </button>
    </form>
  </div>
</template>

<style scoped>
.login {
  min-height: 100vh;
  display: grid;
  place-items: center;
  background: var(--surface-canvas);
  padding: 24px;
}
.card {
  width: min(380px, 100%);
  display: grid;
  gap: 14px;
  padding: 32px;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  background: var(--surface-elevated);
}
.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  font-weight: 700;
}
.brand span {
  display: grid;
  width: 30px;
  height: 30px;
  place-items: center;
  border-radius: 7px;
  color: var(--text-inverse);
  background: var(--action-primary);
}
h1 {
  margin: 8px 0 0;
  font-size: 22px;
}
.sub {
  margin: 0;
  color: var(--text-muted);
  font-size: 13px;
}
label {
  display: grid;
  gap: 6px;
  font-size: 13px;
  color: var(--text-secondary);
}
input {
  padding: 10px 12px;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  background: var(--surface-default);
}
.error {
  margin: 0;
  color: var(--status-error);
  font-size: 13px;
}
.primary {
  margin-top: 4px;
  padding: 11px;
  border: 0;
  border-radius: var(--radius-sm);
  background: var(--action-primary);
  color: var(--text-inverse);
  font-weight: 600;
}
.primary:disabled {
  opacity: 0.7;
  cursor: not-allowed;
}
</style>
