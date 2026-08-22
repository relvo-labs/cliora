<script setup lang="ts">
// Where a citation goes, and — as often — where it deliberately does not.
//
// `repo://` is rendered as copyable text rather than as a link, because Cliora has no
// repository browser. A link that pretends to work is worse than text: it costs the
// reader a click to find out it was never going anywhere.
import { computed, ref } from "vue";

import { isOpenable } from "../queries";

const props = defineProps<{ uri: string | null; title: string }>();

const openable = computed(() => isOpenable(props.uri));
const copied = ref(false);

async function copy(): Promise<void> {
  if (!props.uri) return;
  try {
    await navigator.clipboard.writeText(props.uri);
    copied.value = true;
    window.setTimeout(() => (copied.value = false), 1500);
  } catch {
    // A clipboard a browser refused is not an error worth a dialog: the text is on
    // screen and can be selected.
    copied.value = false;
  }
}
</script>

<template>
  <RouterLink v-if="openable" :to="uri!" class="citation citation--link">
    {{ title }}
  </RouterLink>
  <span v-else-if="uri" class="citation citation--text">
    <code>{{ uri }}</code>
    <button type="button" class="citation__copy" @click="copy">
      {{ copied ? "已複製" : "複製" }}
    </button>
  </span>
  <span v-else class="citation citation--text">{{ title }}</span>
</template>

<style scoped>
.citation {
  font-size: var(--font-sm);
}
.citation--link {
  color: var(--action-primary);
}
.citation--text code {
  font-family: var(--font-mono);
  color: var(--text-secondary);
  word-break: break-all;
}
.citation__copy {
  margin-inline-start: var(--space-2);
  border: none;
  background: none;
  color: var(--action-primary);
  cursor: pointer;
  font-size: var(--font-xs);
}
</style>
