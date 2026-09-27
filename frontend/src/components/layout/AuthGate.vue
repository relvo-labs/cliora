<script lang="ts">
export type AuthGateReason = "signed-out" | "pending" | "switched";
</script>

<script setup lang="ts">
// The cover over a protected page whose signed-in user is gone or unknown
// (#76).
//
// Three situations, all ending in the same rule: what is on the page belonged
// to a user this tab can no longer vouch for, so nobody may read it, focus it
// or type into it until that changes.
//
//   * `signed-out` — the tokens are gone (Logout, another tab, a refused
//     refresh). The auth-loss handler is navigating to the login page.
//   * `pending`    — another tab installed a token pair and `/me` has not yet
//     said whose it is. It may well be the same user after a refresh there.
//   * `switched`   — `/me` said it is someone else; the page is being left.
//
// The page behind is made `inert` by `App.vue` (out of the focus order *and*
// the accessibility tree, which a visual veil alone is not). This is the one
// thing left in either, so it is a modal dialog that takes focus, and it is
// opaque: a translucent scrim over a file listing is still a file listing.
//
// Its action is a plain link, not a router call. The reason this dialog can
// still be on screen is that a navigation did not happen — a route chunk that
// failed to load, a refused navigation — and a link that loads the page afresh
// works whether or not the router does.

import { computed, ref, useId } from "vue";
import { useRoute, useRouter } from "vue-router";

import { useFocusTrap } from "../../composables/useFocusTrap";

const props = defineProps<{ reason: AuthGateReason | null }>();

const route = useRoute();
const router = useRouter();
const panel = ref<HTMLElement>();
const titleId = useId();
const bodyId = useId();

const open = computed(() => props.reason !== null);

// No Escape: there is nothing behind this that the user may go back to.
useFocusTrap(panel, open);

const copy = computed(() => {
  switch (props.reason) {
    case "pending":
      return {
        title: "正在確認登入身分",
        body: "這個瀏覽器的登入在另一個分頁有了變更。確認是同一位使用者之前，這個頁面先隱藏，終端機暫停。",
        action: "重新載入頁面",
        href: route.fullPath,
      };
    case "switched":
      return {
        title: "已切換為另一位使用者",
        body: "這個頁面屬於先前登入的使用者，已清除並停用。",
        action: "重新載入",
        href: router.resolve({ name: "dashboard" }).href,
      };
    default:
      return {
        title: "已登出",
        body: "登入已失效，這個頁面已停用。",
        action: "前往登入",
        href: router.resolve({
          name: "login",
          query: { redirect: route.fullPath },
        }).href,
      };
  }
});
</script>

<template>
  <div v-if="open" class="gate">
    <div
      ref="panel"
      class="panel"
      role="alertdialog"
      aria-modal="true"
      :aria-labelledby="titleId"
      :aria-describedby="bodyId"
      :data-reason="reason"
      tabindex="-1"
    >
      <h2 :id="titleId">{{ copy.title }}</h2>
      <p :id="bodyId">{{ copy.body }}</p>
      <a class="action" :href="copy.href" data-action="auth-gate">
        {{ copy.action }}
      </a>
    </div>
  </div>
</template>

<style scoped>
/* Opaque on purpose, and above every other layer (the highest elsewhere is 50):
   it covers content, it does not dim it. */
.gate {
  position: fixed;
  inset: 0;
  z-index: 60;
  display: grid;
  place-items: center;
  padding: 16px;
  background: var(--surface-default);
}
.panel {
  width: 100%;
  max-width: 440px;
  max-height: 100%;
  overflow: auto;
  padding: 24px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-dialog);
  background: var(--surface-raised);
  box-shadow: var(--shadow-overlay);
}
.panel:focus-visible {
  outline: 2px solid var(--focus-ring);
  outline-offset: 2px;
}
h2 {
  margin: 0 0 10px;
  font-size: 17px;
  color: var(--text-primary);
}
p {
  margin: 0 0 16px;
  font-size: 13px;
  color: var(--text-secondary);
}
/* The primary button's own pair (UiButton `.primary`), on a link: the action
   has to be a real navigation, not a router call. */
.action {
  display: inline-flex;
  align-items: center;
  min-height: var(--density-touch);
  padding: 0 14px;
  border-radius: var(--radius-control);
  background: var(--accent-strong);
  color: var(--text-on-accent);
  font-size: 13px;
  font-weight: 600;
  text-decoration: none;
}
.action:hover {
  background: var(--accent-hover);
}
.action:focus-visible {
  outline: 2px solid var(--focus-ring);
  outline-offset: 2px;
}
</style>
