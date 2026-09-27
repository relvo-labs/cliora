<script setup lang="ts">
import { computed, onMounted } from "vue";
import { RouterView, useRoute } from "vue-router";

import AuthGate, {
  type AuthGateReason,
} from "./components/layout/AuthGate.vue";
import { useAuthStore } from "./stores/auth";

const auth = useAuthStore();
const route = useRoute();

// Restore the signed-in profile after a reload when a token is still held.
onMounted(async () => {
  if (auth.isAuthenticated && !auth.user) {
    try {
      await auth.loadMe();
    } catch {
      auth.clearTokens();
    }
  }
});

// Why the protected page on screen may not be used right now, or null (#76).
// Only for a route that has resolved and is not public: before the first
// navigation there is nothing on screen, and the login page is the way out.
// The router guard covers a navigation made while signed out; this covers
// being signed out — or no longer knowing as whom — while no navigation is
// happening, or while one is slow or has failed.
const gate = computed<AuthGateReason | null>(() => {
  if (route.matched.length === 0 || route.meta.public) return null;
  if (!auth.isAuthenticated) return "signed-out";
  if (auth.discarding) return "switched";
  if (auth.identityPending) return "pending";
  return null;
});
</script>

<template>
  <!-- `inert` takes the page out of the focus order, pointer and keyboard
       input *and* the accessibility tree — which a veil drawn over it does
       not. `aria-hidden` repeats the last part for engines that predate
       `inert`. `display: contents`, so the wrapper adds no box and the shell's
       layout is exactly what it was. `|| undefined`, not `false`: where an
       engine has no `inert` property Vue writes the attribute as a string, and
       `inert="false"` is still inert. -->
  <div
    class="routed"
    :inert="gate !== null || undefined"
    :aria-hidden="gate !== null ? 'true' : undefined"
  >
    <RouterView />
  </div>
  <AuthGate :reason="gate" />
</template>

<style scoped>
.routed {
  display: contents;
}
</style>
