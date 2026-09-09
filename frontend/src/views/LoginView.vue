<script setup lang="ts">
import { onMounted, ref } from "vue";
import { SquareTerminal } from "lucide-vue-next";
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
      <div class="brand">
        <span class="mark" aria-hidden="true"><SquareTerminal /></span>Cliora
      </div>
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
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-panel);
  background: var(--surface-default);
}
.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  font-weight: 700;
}
.brand .mark {
  display: grid;
  width: 30px;
  height: 30px;
  place-items: center;
  border-radius: 7px;
  color: var(--text-on-accent);
  background: var(--accent-strong);
}
h1 {
  margin: 8px 0 0;
  font-size: 22px;
}
.sub {
  margin: 0;
  color: var(--text-secondary);
  font-size: 13px;
}
label {
  display: grid;
  gap: 6px;
  font-size: 13px;
  color: var(--text-primary);
}
input {
  padding: 10px 12px;
  border: 1px solid var(--border-control);
  border-radius: var(--radius-control);
  background: var(--surface-raised);
}
.error {
  margin: 0;
  color: var(--status-error-fg);
  font-size: 13px;
}
.primary {
  margin-top: 4px;
  padding: 11px;
  border: 0;
  border-radius: var(--radius-control);
  background: var(--accent-strong);
  color: var(--text-on-accent);
  font-weight: 600;
}
/* A colour, not an opacity. Opacity dims the label along with everything
   else, so a disabled control stops being able to say what it is or why it is
   disabled — and "disabled keeps an understandable reason" is the rule
   (--text-disabled is measured at >= 3:1 on all three surfaces for this). */
.primary:disabled {
  background: var(--surface-raised);
  border: 1px solid var(--border-control);
  color: var(--text-disabled);
  cursor: not-allowed;
}
</style>
