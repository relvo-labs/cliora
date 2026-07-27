<script setup lang="ts">
// Presents one failure the way `docs/error-catalog.md` specifies: what happened (the
// server's safe message), why (cause), what to do (next step), and the request id so
// the real detail can be found in the server log (P4-07).
//
// Retry is offered only where the catalog says it can work. Deciding that per call
// site is how a "Retry" button ends up on a permanent failure, which teaches users to
// ignore it everywhere else.

import { computed } from "vue";

import { ApiError } from "../../api/client";
import { errorGuidance } from "../../utils/errorCatalog";

// `retryable` is `boolean | null`, not an optional `boolean`, and that is deliberate.
// Vue casts an **absent Boolean prop to `false`**, so a plain `retryable?: boolean`
// makes "the caller said no" indistinguishable from "the caller said nothing" — and
// the catalog default could then never apply, silently hiding every retry control. A
// union type opts out of Boolean casting, so `null` really means "not specified".
const props = withDefaults(
  defineProps<{
    error: unknown;
    // Overrides the catalog when the caller genuinely has nothing to retry (a view
    // that has already navigated away, say).
    retryable?: boolean | null;
  }>(),
  { retryable: null },
);

const emit = defineEmits<{ retry: [] }>();

const apiError = computed(() =>
  props.error instanceof ApiError ? props.error : null,
);

// A network failure has no code and no server message; it is still a real state and
// must not render as an empty panel.
const code = computed(() => apiError.value?.code ?? "NETWORK_UNREACHABLE");
const message = computed(
  () => apiError.value?.message ?? "無法連線至 Central。",
);
const guidance = computed(() => errorGuidance(apiError.value?.code));
const showRetry = computed(() =>
  props.retryable === null ? guidance.value.retryable : props.retryable,
);
</script>

<template>
  <div class="notice" role="alert">
    <p class="headline">
      {{ message }}
      <code>{{ code }}</code>
    </p>
    <dl>
      <dt>原因</dt>
      <dd>{{ guidance.cause }}</dd>
      <dt>下一步</dt>
      <dd>{{ guidance.nextStep }}</dd>
    </dl>
    <p class="foot">
      <!-- Always shown when present: it is the only handle that ties this screen to
           the server-side log line holding the real detail. -->
      <span v-if="apiError?.requestId" class="rid"
        >request_id: <code>{{ apiError.requestId }}</code></span
      >
      <button
        v-if="showRetry"
        type="button"
        class="retry"
        @click="emit('retry')"
      >
        重試
      </button>
    </p>
  </div>
</template>

<style scoped>
.notice {
  padding: 14px 16px;
  border: 1px solid var(--border-danger);
  border-radius: var(--radius-md);
  background: var(--surface-elevated);
  font-size: 13px;
}
.headline {
  margin: 0 0 10px;
  font-weight: 600;
  color: var(--status-error);
}
.headline code,
.rid code {
  margin-left: 6px;
  color: var(--text-muted);
  font-size: 11px;
  font-weight: 400;
}
dl {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 4px 12px;
  margin: 0;
}
dt {
  color: var(--text-muted);
  font-size: 12px;
}
dd {
  margin: 0;
  color: var(--text-secondary);
}
.foot {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 12px 0 0;
}
.rid {
  color: var(--text-muted);
  font-size: 11px;
}
.retry {
  padding: 6px 12px;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  background: var(--surface-default);
  color: var(--text-secondary);
  font-weight: 600;
}
</style>
