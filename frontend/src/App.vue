<script setup lang="ts">
import { onMounted } from "vue";
import { RouterView } from "vue-router";

import { useAuthStore } from "./stores/auth";

const auth = useAuthStore();

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
</script>

<template>
  <RouterView />
</template>
