<script setup lang="ts">
import {
  computed,
  defineAsyncComponent,
  nextTick,
  onBeforeUnmount,
  onMounted,
  ref,
  watch,
} from "vue";
import { PanelRight } from "lucide-vue-next";

import { ApiError } from "../api/client";
import type { NodeDetail, SessionDetail } from "../api/dto";
import AppLayout from "../components/layout/AppLayout.vue";
import ConfirmDialog from "../components/common/ConfirmDialog.vue";
import ErrorNotice from "../components/common/ErrorNotice.vue";
import FileBrowser from "../components/file/FileBrowser.vue";
import FileTree from "../components/file/FileTree.vue";
import SessionHeader from "../components/session/SessionHeader.vue";
import StatusBar from "../components/session/StatusBar.vue";
import WorkspaceTabs from "../components/session/WorkspaceTabs.vue";
import TerminalFontControl from "../components/session/TerminalFontControl.vue";
import UiButton from "../components/ui/UiButton.vue";
import UiIconButton from "../components/ui/UiIconButton.vue";
import UiInlineNotice from "../components/ui/UiInlineNotice.vue";
import UiLoadingState from "../components/ui/UiLoadingState.vue";
import UiToolbar from "../components/ui/UiToolbar.vue";

// Monaco is a large dependency and only the preview needs it, so the pane (and
// with it the whole editor bundle) loads on the first file the user opens.
const PreviewPane = defineAsyncComponent(
  () => import("../components/file/PreviewPane.vue"),
);
import { useAsyncResource } from "../composables/useAsyncResource";
import { useBreakpoint } from "../composables/useBreakpoint";
import { useFileDownload } from "../composables/useFileDownload";
import { useFileUpload, suggestRename } from "../composables/useFileUpload";
import { useImageDrop } from "../composables/useImageDrop";
import type { BrowserPlace } from "../composables/useFileBrowser";
import { useFocusTrap } from "../composables/useFocusTrap";
import { useTerminalSession } from "../composables/useTerminalSession";
import { api, useAuthStore } from "../stores/auth";
import {
  INSPECTOR_MAX,
  INSPECTOR_MIN,
  usePreferencesStore,
} from "../stores/preferences";
import { useFilesStore } from "../stores/files";
import { useNodesStore } from "../stores/nodes";
import { useSessionsStore } from "../stores/sessions";

const props = defineProps<{ id: string }>();
const auth = useAuthStore();
const sessions = useSessionsStore();
// Reached directly for one thing only: refreshing the directory an upload landed
// in. The tree owns its own loading; this is the one event it cannot see.
const filesStore = useFilesStore();
const nodes = useNodesStore();
const preferences = usePreferencesStore();

// Capabilities come from the session payload, computed server-side from the role
// *and* ownership (ADR 0016) — a Developer may see a colleague's session but not
// terminate or take it over, which a role-only check cannot express. Until the
// session loads, assume nothing.
const capabilities = computed(() => session.value?.capabilities);
const canTerminate = computed(() => capabilities.value?.can_terminate === true);
const canTakeover = computed(() => capabilities.value?.can_takeover === true);
const canBrowseFiles = computed(
  () => capabilities.value?.can_browse_files === true,
);
// Whether a TERMINAL tab exists at all. The server already combined the action,
// ownership and the node's own veto into this flag; recombining it here with
// `hasPermission()` would show the tab on a colleague's session and only fail
// when it was pressed.
const canOpenShell = computed(
  () => capabilities.value?.can_open_shell === true,
);

// A session in a terminal state has no daemon-side workspace to browse.
const TERMINAL_STATUSES = new Set(["exited", "failed", "terminated"]);

// Ended, by either witness (#76 review). The payload's status is only as fresh
// as the last fetch; the terminal socket's `terminal.exited` /
// `session.stopped` is usually the first — and often the only — news that the
// session is over, and no refetch follows it. Either one is enough. The
// socket's `exited` is sticky for the session it belongs to (no reconnect is
// scheduled after it) and a switch to another id reconnects, which leaves it.
const sessionEnded = computed(
  () =>
    terminal.status.value === "exited" ||
    (session.value !== null && TERMINAL_STATUSES.has(session.value.status)),
);

// The file panel keys off the session id; a null id (or a dead session) means it
// binds nothing and issues no request.
//
// Only a live session the *latest* fetch confirmed (#76). `sessions.current`
// outlives a failed refetch — a 403 leaves the previous payload in place — so
// matching the id alone would keep the files store bound, and its listing
// cached, for a session the server just refused. A terminal status unbinds for
// the same reason: the tree, the phone browser and the preview all read this
// one value, and the preview in particular is not mounted beside the browser on
// a phone, so it cannot rely on the browser noticing. Unbinding wipes the store
// and closes the preview (see the watcher before the session-switch one).
//
// And only while this tab is signed in as the user it was opened for: the file
// cache is keyed by session id alone, so it must not outlive the user it was
// fetched for. The auth-loss handler wipes the store and leaves the route;
// unbinding here as well means nothing in this view can ask for it again in
// the meantime.
//
// An *unconfirmed* identity (a cross-tab token swap, `/me` outstanding) does
// not unbind — unbinding wipes, and `/me` may yet name the same user, in which
// case the page comes back exactly as it was. It is covered and made inert by
// `App.vue` instead, and the handler aborts in-flight file work.
const filesSessionId = computed(() =>
  auth.isAuthenticated &&
  !auth.discarding &&
  resource.state.value === "success" &&
  session.value?.id === props.id &&
  !sessionEnded.value
    ? props.id
    : null,
);

// Workspace root label: the folder name only. The node's absolute workspace path
// never reaches the tree (P3 no-absolute-path rule).
const workspaceLabel = computed(() => {
  const path = session.value?.workspace ?? "";
  const parts = path.split("/").filter(Boolean);
  return parts.length ? parts[parts.length - 1] : "workspace";
});

const filesDisabledReason = computed(() =>
  session.value && sessionEnded.value
    ? "Session 已結束，檔案瀏覽不再可用。"
    : undefined,
);

// The file currently open in the preview pane. Cleared when the tree clears
// (session switch) so no previous session's content stays on screen. There is
// at most one preview at a time, so at most one `[filename]` tab (WT-03, D2).
const previewPath = ref<string | null>(null);

// Centre-pane tab selection. `cli` always exists; `preview` only while a file
// is open, so a closed preview always falls back to the terminal.
type CentreTab = "cli" | "preview" | "terminal";
const activeTab = ref<CentreTab>("cli");

const tabs = computed(() => [
  { id: "cli", label: "CLI" },
  ...(previewPath.value
    ? [
        {
          id: "preview",
          // Basename only. The full workspace-relative path goes in the
          // tooltip; a node absolute path never reaches the browser (P3).
          label: previewPath.value.split("/").pop() ?? previewPath.value,
          title: previewPath.value,
          closable: true,
        },
      ]
    : []),
  ...(canOpenShell.value
    ? [
        {
          id: "terminal",
          label: "TERMINAL",
          title: "此 Node 上的系統終端機",
          closable: shellSession.value !== null,
        },
      ]
    : []),
]);

function openPreview(relPath: string): void {
  previewPath.value = relPath;
  activeTab.value = "preview";
  if (isNarrow.value) {
    mobileMode.value = "preview";
    pushPreviewHistory();
  }
}

function closePreview(): void {
  previewPath.value = null;
  activeTab.value = "cli";
  if (isNarrow.value) {
    // Back to the list it was opened from, not to the terminal: preview is a
    // substate of files.
    mobileMode.value = "files";
    resumeBrowser();
    popPreviewHistory();
  }
}

// Where the phone's file list was when a preview opened: folder, scroll and
// the row, so closing the preview puts the user back there with focus on
// that row (plan/29 MS-16, plan/31/05 BP-06 §0). The list is not mounted
// beside a full-screen preview, so the place is held here in between — in
// memory only, never in the URL or the history entry. It belongs to one
// session and one user, and is forgotten with them.
let browserPlace: BrowserPlace | null = null;
let panelScrollTop = 0;
const browserResume = ref<BrowserPlace | null>(null);
function rememberPlace(place: BrowserPlace): void {
  browserPlace = place;
  panelScrollTop = filePanel.value?.scrollTop ?? 0;
}
function resumeBrowser(): void {
  browserResume.value = browserPlace;
}
function onBrowserResumed(): void {
  // The rail scrolls too on a phone; it is this view's element, so this view
  // restores it, after the list has rendered its rows.
  if (browserResume.value && filePanel.value) {
    filePanel.value.scrollTop = panelScrollTop;
  }
  browserResume.value = null;
}
function forgetPlace(): void {
  browserPlace = null;
  browserResume.value = null;
}

// The back gesture, without putting a workspace-relative path in history
// (plan/29 MS-D-02/MS-08).
//
// A fullscreen preview that the system Back button exits the *session* from is
// the single most likely mis-tap on a phone. The fix is one history entry with
// no state and the same URL, popped again when the preview closes by any other
// route, so opening and closing ten files leaves the stack exactly as it was.
// The path itself is never written anywhere: not the URL, not the entry's
// state, not storage (addendum §1/§7).
let previewHistoryDepth = 0;
function pushPreviewHistory(): void {
  if (typeof window === "undefined" || previewHistoryDepth > 0) return;
  window.history.pushState(null, "", window.location.href);
  previewHistoryDepth += 1;
}
function popPreviewHistory(): void {
  if (typeof window === "undefined" || previewHistoryDepth === 0) return;
  previewHistoryDepth -= 1;
  window.history.back();
}
function onPopState(): void {
  // Only meaningful while we are the ones who pushed. Decrement first: `back()`
  // already happened, so calling `popPreviewHistory` from here would pop a
  // second entry and leave the route.
  if (previewHistoryDepth === 0) return;
  previewHistoryDepth = 0;
  previewPath.value = null;
  activeTab.value = "cli";
  mobileMode.value = "files";
  resumeBrowser();
}

function closeTab(id: string): void {
  if (id === "preview") closePreview();
  if (id === "terminal") void closeShell();
}

// Re-measure on the way into either terminal: while a panel is hidden its host
// measures 0x0, so the composable deliberately refuses to fit it.
watch(activeTab, async (tab) => {
  if (tab === "cli") {
    await nextTick();
    terminal.fit();
    terminal.focus();
    return;
  }
  if (tab === "terminal") {
    await openShellTab();
  }
});

// --- Terminals while the user is not confirmed (#76) -----------------------
//
// Signed out, or signed in as someone `/me` has not confirmed yet: neither
// terminal may send a byte. `App.vue` already makes the page inert, which stops
// the keyboard reaching xterm; this stops the socket existing at all.
//
// `disconnect()` closes the socket, but the composable's own close handler then
// schedules a reconnect, and a reconnect is only a new ticket away. So the
// ticket is what is gated: every (re)connect of either terminal asks this
// function, and while the identity is unconfirmed it refuses without calling
// Central. The composable backs off and keeps asking; nothing reaches the
// relay. A ticket requested *before* the suspension and answered after it is
// refused too, by the epoch check. No transport code changes: this is the seam
// the composable was given a ticket provider for.
//
// When the same user is confirmed again, both reconnect at once with fresh
// tickets (and a fresh authorization check). A different user never resumes
// here: the page is left and unmounted, which disposes both.
//
// The same seam fences the *session* a ticket is for (#76 review 4). The route
// component is reused when `/sessions/:id` changes, and the composable has no
// notion of a superseded connect: an attach request for session A answered
// after the switch to B would open a socket to A under B's page, and the B view
// would type into it. So each terminal gets its own provider that knows which
// session is current for it, and a ticket is handed over only if, when it
// arrives, it is still for that session *and* is the latest one that terminal
// asked for.
//
// A request that fails either check is abandoned, not refused: its promise
// never settles. A refusal means "try again soon" to the composable — it would
// schedule a reconnect, and that reconnect closes whatever socket is current,
// which for a superseded request is the good one. Leaving it unanswered opens
// nothing and schedules nothing; the newer request (or the route change that
// made it stale) owns the terminal from here. The ticket Central already minted
// for it is single-use and short-lived, and simply expires.
let identityEpoch = 0;
const abandoned = (): Promise<never> => new Promise<never>(() => {});
function fencedTicket(
  isCurrent: (sessionId: string) => boolean,
): (sessionId: string) => Promise<string> {
  let latest = 0;
  return async (sessionId) => {
    const request = ++latest;
    const stale = () => request !== latest || !isCurrent(sessionId);
    // Not current before anything is asked: Central is not even called.
    if (stale()) return abandoned();
    const epoch = identityEpoch;
    if (!auth.identityConfirmed) throw new Error("terminal suspended");
    let ticket: string;
    try {
      ticket = (await api().attachSession(sessionId)).ticket;
    } catch (caught) {
      // A superseded request's failure is not the terminal's failure either.
      if (stale()) return abandoned();
      throw caught;
    }
    if (stale()) return abandoned();
    if (epoch !== identityEpoch || !auth.identityConfirmed) {
      throw new Error("terminal suspended");
    }
    return ticket;
  };
}
// The main CLI: the route's session, and only once the latest fetch confirmed
// that very id (a session whose payload failed to load gets no ticket either).
const cliTicket = fencedTicket(
  (sessionId) => sessionId === props.id && workspaceLive.value,
);
// The system terminal: the shell this page opened, while it is open. Closing
// it (by tab, unload, or route change) clears it first, so a reconnect for a
// shell that is being terminated never asks Central for a ticket.
const shellTicket = fencedTicket(
  (sessionId) => sessionId === shellSession.value?.id,
);
let terminalsSuspended = !auth.identityConfirmed;
watch(
  () => auth.identityConfirmed,
  (confirmed) => {
    if (!confirmed && !terminalsSuspended) {
      terminalsSuspended = true;
      identityEpoch += 1;
      // An ended session's terminal is left as it is: disconnecting would turn
      // `exited` into `disconnected` and rebind the files of a dead session.
      if (terminal.status.value !== "exited") terminal.disconnect();
      if (shellSession.value) shellTerminal.disconnect();
    } else if (confirmed && terminalsSuspended) {
      terminalsSuspended = false;
      if (terminal.status.value !== "exited") terminal.retry();
      if (shellSession.value) shellTerminal.retry();
    }
  },
  // Synchronous: suspended inside the very call that cleared or replaced the
  // tokens, not on the next render.
  { flush: "sync" },
);

// --- System terminal (FR-SHELL-001) ---------------------------------------
//
// A second, independent instance of the same composable: the shell is an
// ordinary session over the same relay, so nothing about the transport differs.
const shellTerminal = useTerminalSession(shellTicket, {
  themeId: preferences.renderedTheme,
});
const shellSession = ref<SessionDetail | null>(null);
const shellHost = ref<HTMLElement | null>(null);
const shellState = ref<"idle" | "starting" | "ready" | "error">("idle");
const shellError = ref("");

watch(
  shellHost,
  (element) => {
    if (element) shellTerminal.mount(element);
  },
  { immediate: true },
);

// Who a shell being opened belongs to (#76 review 5). The shell's id is only
// known once `openShell` answers, so a way out taken while that request is out
// — an in-place route change, unmount, unload, losing the user — finds nothing
// for `closeShell` to close. Each of those moves this generation instead, and
// an answer that arrives for an earlier one is an orphan: it is terminated
// through the ordinary API and never becomes this page's shell. Without this
// the late answer installed session A's shell under B's page, and the shell
// ticket fence, which trusts `shellSession`, let it connect.
let shellOwner = 0;
function disownPendingShell(): void {
  shellOwner += 1;
}

// Losing the user — signed out, or `/me` naming someone else — is a way out of
// this page too, even before the auth-loss handler's navigation unmounts it:
// a shell still being opened is no longer anyone's here (#76 review 5). A
// merely *unconfirmed* identity is not: the page may come back as it was, and
// the suspension above already keeps the shell from connecting meanwhile.
watch(
  () => auth.isAuthenticated && !auth.discarding,
  (ownUser) => {
    if (!ownUser) disownPendingShell();
  },
  { flush: "sync" },
);

// Started on first use, not on page load: a shell nobody opened would still
// consume a slot against the node and user session caps (D8).
async function openShellTab(): Promise<void> {
  if (shellState.value === "starting") return;
  if (shellSession.value) {
    await nextTick();
    shellTerminal.fit();
    shellTerminal.focus();
    return;
  }
  const owner = shellOwner;
  const parentId = props.id;
  const owned = () => owner === shellOwner;
  shellState.value = "starting";
  shellError.value = "";
  try {
    // The panel was just revealed by `v-show`; it has no layout until the DOM
    // updates, and an unmeasurable host reports nothing. Opening at a hardcoded
    // 24×80 and letting the first fit correct it made bash redraw its prompt at
    // a different width in front of the user (plan/09 LY-04).
    await nextTick();
    if (!owned()) return;
    const size = shellTerminal.proposeSize() ?? { rows: 24, columns: 80 };
    const created = await api().openShell(parentId, size);
    if (!owned()) {
      // Best effort, like `closeShell`: the parent binding and the idle
      // timeout still collect it if this is refused (after a sign-out, say).
      api()
        .terminateSession(created.id)
        .catch(() => {});
      return;
    }
    shellSession.value = created;
    shellState.value = "ready";
    await nextTick();
    // Closed during that tick: `closeShell` already terminated it.
    if (!owned() || shellSession.value?.id !== created.id) return;
    void shellTerminal.connect(created.id);
  } catch (caught) {
    // A stale request's failure belongs to a page that is gone.
    if (!owned()) return;
    shellState.value = "error";
    shellError.value =
      caught instanceof ApiError ? caught.message : "無法開啟系統終端機。";
  }
}

// Closing the tab ends the session on the node. The server-side parent binding
// and idle timeout are the backstop for the cases the browser cannot report
// (a crash, a lost network), not a substitute for asking.
async function closeShell(): Promise<void> {
  const open = shellSession.value;
  shellSession.value = null;
  shellState.value = "idle";
  shellTerminal.disconnect();
  if (activeTab.value === "terminal") activeTab.value = "cli";
  if (!open) return;
  try {
    await api().terminateSession(open.id);
  } catch {
    // Best effort: the parent binding and the idle timeout still collect it.
  }
}

// AC-08 has two halves and only the first was implemented: "closing the terminal
// **or leaving the Session workspace** ends the system terminal". Leaving covers
// three different exits, and each needs its own hook — a shell that survives any of
// them is one nobody is watching, and the next visit could not even see it to close
// it (the tab's close affordance keys off local state, which the exit just threw
// away).
//
// 1. Navigating inside the app (Back, the sidebar): the component unmounts.
onBeforeUnmount(() => {
  disownPendingShell();
  void closeShell();
});

// 2. Reload, tab close, or leaving the origin: no unmount runs and an ordinary
//    fetch would be cancelled with the document, so this one is `keepalive` and
//    fire-and-forget. `pagehide` rather than `beforeunload`: it also fires when the
//    page is discarded on mobile, and it does not risk a confirmation prompt.
//    The local state is reset too, not just the request sent: `pagehide` also fires
//    when the page is put in the back/forward cache, and a restored page that still
//    believed it had this terminal would show its dead scrollback.
function terminateShellOnUnload(): void {
  disownPendingShell();
  const open = shellSession.value;
  if (!open) return;
  shellSession.value = null;
  shellState.value = "idle";
  shellTerminal.disconnect();
  api().terminateSessionOnUnload(open.id);
}
window.addEventListener("pagehide", terminateShellOnUnload);
onBeforeUnmount(() =>
  window.removeEventListener("pagehide", terminateShellOnUnload),
);

const host = ref<HTMLElement | null>(null);
// The session the terminate dialog names, captured when it opened (#76 review
// 5). The dialog used to show `session?.name` and confirm `props.id`, which an
// in-place route change pulls apart: it could name A while terminating B. Now
// it shows and terminates the one session it was opened for, is closed when the
// route id changes, and a confirmation is refused unless the route still is
// that session.
const terminateTarget = ref<{ id: string; name: string } | null>(null);
function askTerminate(): void {
  if (!workspaceLive.value || !session.value) return;
  terminateTarget.value = { id: session.value.id, name: session.value.name };
}
const actionError = ref("");
const busy = ref(false);

const resource = useAsyncResource<SessionDetail>(async () => {
  const detail = await sessions.fetchSession(props.id);
  // Posture is fetched alongside, not awaited into the critical path's failure
  // modes: a node read that fails must not make the workspace unopenable.
  void loadNodePosture(detail.node_id);
  return detail;
});

// The composable owns the xterm + socket; it mints a fresh single-use ws-ticket
// on every (re)connect via the API client.
//
// The theme and font size are passed in rather than read from a store inside
// the composable, so it stays testable without Pinia — the same reason the
// ticket provider is injected.
const terminal = useTerminalSession(cliTicket, {
  themeId: preferences.renderedTheme,
  fontSize: preferences.terminalFontSize,
});

const session = computed(() => sessions.current);

// The workspace on screen is the route's session, loaded by the latest fetch.
// False from the very tick `/sessions/:id` changes in place — `sessions.current`
// still holds the session that was left until the new one arrives — and while
// any fetch is outstanding or failed. While false the veil covers the page and
// everything under it is inert (#76 review 4): a veil is only paint, and the
// old session's terminal, header actions and file panel stayed focusable and
// typeable behind it.
const workspaceLive = computed(
  () => resource.state.value === "success" && session.value?.id === props.id,
);
// Bound on every sibling of the veil. `inert` takes a subtree out of the
// focus order, pointer and keyboard input and the accessibility tree;
// `aria-hidden` repeats the last part for engines that predate it. An absent
// key rather than `false`, as in `App.vue`: where an engine has no `inert`
// property Vue writes the attribute as a string, and `inert="false"` is inert.
const behindVeil = computed(() =>
  workspaceLive.value ? {} : { inert: true, "aria-hidden": "true" as const },
);

// 這台 Node 的執行姿態（ADR 0023）。使用者按下 Enter 之前，資訊要在他眼前 —— 不是藏在
// Node 詳情頁裡。額外一次請求、且失敗不影響工作區：拿不到姿態時什麼都不顯示，
// 因為顯示一個猜的姿態比不顯示更糟。Viewer 也持有 node.view，所以每個能開這個工作區的
// 人都拿得到。
// 1024-1439px collapses the work header to one row. Measured, not preferred:
// the CLI panel is 542px at 1024x768 and 14px/1.2 gives 28 rows there, under
// plan/09's floor of 30. One row recovers 24px — about one row — and the
// user-adjustable font size covers the rest (13px/1.2 gives 30 at that size).
// The widths are no longer written here (plan/29 MS-01/MS-05). This file used to
// hold two of the three that had drifted apart — `< 1024` in script and a
// `@media (max-width: 1100px)` that hid the rail outright. Between 1024 and
// 1100px the panel was therefore in the DOM, `display: none`, and had no
// control to open it; measured at seven widths in plan/29 09-…md §4.1. The
// media query is gone: `[data-files-hidden]` already collapses the grid from
// the same state the drawer button reads, so the width rule was a second,
// disagreeing source for a decision that was already being made correctly.
const { isNarrow, isTablet, belowWide } = useBreakpoint();
// Every width below 1440, narrow included (plan/29 MS-06). It used to start at
// 768, so a phone got the *uncompressed* two-row header — the widest layout on
// the narrowest screen. Node posture is no longer part of what the compact form
// collapses, so extending it down costs nothing ADR 0023 cares about.
const compactHeader = belowWide;

// The file column has three modes, not two. Below 1024px it is an overlay
// drawer with a button on the tab strip; at 1024px and up it is a resizable
// column. What this replaces was `display: none` below 1100px with no opening
// control at all — the file tree simply ceased to exist, which is the shape the
// shared design foundation names as forbidden ("不將功能直接隱藏").
// Only the tablet range keeps the overlay drawer. Below 768px the file browser
// is a *mode* rather than a panel that floats over the terminal: an overlay on
// a 390px screen covers the thing it is supposed to sit beside, so it is a
// mode wearing an overlay's costume (plan/29 MS-07).
const filesAreDrawer = isTablet;
const filesOpen = ref(false);

// The narrow-viewport mode. Three values, and the first one is `cli`, not
// `terminal`, on purpose: in this file `terminal` already means the system
// shell, whose lifecycle is the opposite of the main CLI's — the shell dies on
// close, the CLI only detaches (ADR 0021 vs ADR 0012/0013). The mobile addendum
// called this mode `terminal`; it is renamed here rather than inherited,
// because the one thing worse than two names for one concept is one name for
// two (plan/29 05-…md §0).
//
// `preview` is a substate of `files`, not a fourth top-level place: closing it
// returns to the file list, which is where it was opened from.
type MobileMode = "cli" | "files" | "preview";
const mobileMode = ref<MobileMode>("cli");

// Visible means "occupying space or overlaying": a closed drawer is neither,
// and on a phone the file browser is visible exactly when it is the mode.
const filesVisible = computed(() =>
  isNarrow.value
    ? mobileMode.value === "files"
    : !filesAreDrawer.value || filesOpen.value,
);

const filePanel = ref<HTMLElement>();
const drawerButton = ref<{ $el: HTMLElement } | null>(null);

// Escape closes the drawer and returns focus to the button that opened it —
// the same contract the dialog has, from the same composable. A drawer that
// traps focus and then loses it on close leaves the next Tab starting from the
// top of the document.
useFocusTrap(
  filePanel,
  computed(() => filesAreDrawer.value && filesOpen.value),
  { onEscape: () => (filesOpen.value = false) },
);

// Pointer drag. The width is clamped and persisted by the store, so the bounds
// live in one place rather than being repeated by every caller.
let resizeFrom = 0;
let resizeStart = 0;
function onResizeMove(event: PointerEvent): void {
  // Dragging left widens: the handle is on the panel's left edge.
  preferences.setInspectorWidth(resizeStart + (resizeFrom - event.clientX));
}
function endResize(): void {
  window.removeEventListener("pointermove", onResizeMove);
  window.removeEventListener("pointerup", endResize);
}
function startResize(event: PointerEvent): void {
  resizeFrom = event.clientX;
  resizeStart = preferences.inspectorWidth;
  window.addEventListener("pointermove", onResizeMove);
  window.addEventListener("pointerup", endResize);
}
// Arrow keys move it too, in 16px steps, with Home/End for the bounds.
function onResizeKey(event: KeyboardEvent): void {
  const step = 16;
  if (event.key === "ArrowLeft") {
    preferences.setInspectorWidth(preferences.inspectorWidth + step);
  } else if (event.key === "ArrowRight") {
    preferences.setInspectorWidth(preferences.inspectorWidth - step);
  } else if (event.key === "Home") {
    preferences.setInspectorWidth(INSPECTOR_MIN);
  } else if (event.key === "End") {
    preferences.setInspectorWidth(INSPECTOR_MAX);
  } else {
    return;
  }
  event.preventDefault();
}

const nodePosture = ref<NodeDetail | null>(null);
async function loadNodePosture(nodeId: string): Promise<void> {
  try {
    nodePosture.value = await nodes.fetchNode(nodeId);
  } catch {
    nodePosture.value = null;
  }
}
const sandboxBypassed = computed(() => {
  const runtime = session.value?.runtime;
  if (!runtime || !nodePosture.value) return false;
  return (
    nodePosture.value.runtimes.find((rt) => rt.runtime === runtime)
      ?.sandbox_bypass === true
  );
});
const privilegedNode = computed(
  () => nodePosture.value?.privileged_terminal === true,
);

// Mounting follows the host element, not the lifecycle hook. `onMounted` fires
// once, so any render that replaced the host — a failed load followed by Retry,
// or a tab panel being rebuilt — left xterm attached to a detached node with
// nobody to put it back (WT-02).
// --- Image drop (WF-07, ADR 0024) -----------------------------------------

const imageDrop = useImageDrop((file, onProgress, signal) =>
  api().uploadImage(props.id, file, { onProgress, signal }),
);
const dragActive = ref(false);
const pickerInput = ref<HTMLInputElement | null>(null);

// Three conditions, all server-derived except the last. `can_upload_files`
// already combines the action with ownership; `image_upload` is the node's own
// report (ADR 0024 W4) — without it the console would offer a button that always
// fails. The writer condition is separate because it is *temporary*.
const canUploadImages = computed(
  () =>
    capabilities.value?.can_upload_files === true &&
    nodePosture.value?.image_upload === true,
);
const isWriter = computed(() => terminal.role.value === "writer");

// --- General file upload (FU-06, ADR 0026) --------------------------------
//
// Same permission as image drop, different node flag. That pairing is the whole
// posture model: `can_upload_files` answers "may this user", and the node answers
// "may this machine" — twice, because accepting a screenshot into .cliora/ and
// accepting an arbitrary file anywhere in the workspace are different-sized grants
// (ADR 0026 §9).
//
// And unlike image drop there is deliberately no writer condition: that path ends
// by typing into the terminal, so it needs the write lock. This one only touches
// the filesystem, so two people can upload at once.
const canUploadFiles = computed(
  () =>
    capabilities.value?.can_upload_files === true &&
    nodePosture.value?.file_upload === true,
);

const fileUpload = useFileUpload(
  (directory, filename, file, onProgress, signal) =>
    api().uploadFile(props.id, directory, filename, file, {
      onProgress,
      signal,
    }),
);
const uploadRefusal = ref("");

async function uploadFiles(files: File[], directory: string): Promise<void> {
  if (!canUploadFiles.value) return;
  uploadRefusal.value = "";
  const outcome = await fileUpload.submit(files, directory);
  // One refresh per batch, and only for directories that actually gained a file:
  // three uploads should not make the tree jump three times.
  for (const dir of outcome.touched) {
    void filesStore.refreshDir(dir);
  }
}

// --- File download (FD-06, ADR 0028) --------------------------------------
//
// Two conditions, mirroring the two upload paths above and derived the same way:
// `can_browse_files` answers "may this user" — download reuses `file.browse`
// rather than adding an action, so a Viewer may download and that is deliberate
// (ADR 0028 §5) — and `file_download` answers "may this machine", separately from
// the two upload flags, because accepting a file is not agreeing to hand one back.
//
// No writer condition, for the same reason the file-upload path has none: this
// touches the filesystem and not the terminal, so it needs no write lock.
const canDownloadFiles = computed(
  () =>
    capabilities.value?.can_browse_files === true &&
    nodePosture.value?.file_download === true,
);

const fileDownload = useFileDownload((path, signal) =>
  api().downloadFile(props.id, path, { signal }),
);

function downloadFile(relPath: string): void {
  if (!canDownloadFiles.value) return;
  void fileDownload.start(relPath);
}

function renameAndRetry(id: string): void {
  const item = fileUpload.items.value.find((entry) => entry.id === id);
  if (!item) return;
  const suggestion = suggestRename(item.name);
  // A prompt rather than an inline editor: this is the recovery path for a
  // collision, and the alternative is a form that has to live inside a list row.
  const next = window.prompt("以新檔名重新上傳：", suggestion);
  if (!next) return;
  void fileUpload.retryAs(id, next).then((outcome) => {
    for (const dir of outcome.touched) void filesStore.refreshDir(dir);
  });
}

// The browser's default action for an unhandled file drop is to navigate to the
// file. Two elements accept drops (the terminal panel for images, the file tree
// for files); everything else in this view has to swallow them, or a near-miss
// loses the whole console.
function swallowStrayDrop(event: DragEvent): void {
  event.preventDefault();
}

async function dropImage(file: File): Promise<void> {
  if (!canUploadImages.value) return;
  const storedPath = await imageDrop.submit(file);
  if (!storedPath) return;
  // Type the path, with a trailing space and no Enter: the user usually still
  // has something to say about the image (ADR 0024 sec 2).
  if (terminal.typeText(`${storedPath} `)) {
    activeTab.value = "cli";
    terminal.focus();
  }
}

function onTerminalPaste(event: ClipboardEvent): void {
  const file = imageDrop.handlePaste(event);
  if (file) void dropImage(file);
}

function onTerminalDrop(event: DragEvent): void {
  dragActive.value = false;
  const file = imageDrop.handleDrop(event);
  if (file) void dropImage(file);
}

function onDragOver(event: DragEvent): void {
  if (!canUploadImages.value || !isWriter.value) return;
  // Without preventDefault the browser never fires `drop`.
  event.preventDefault();
  dragActive.value = true;
}

function onPicked(event: Event): void {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  // Reset first, so choosing the same file twice in a row still fires change.
  input.value = "";
  if (file) void dropImage(file);
}

watch(
  host,
  (element) => {
    if (element) terminal.mount(element);
  },
  { immediate: true },
);

// The one owner of "load this route's session, then connect its CLI" (#76
// review 5). Mount, an in-place route change and the veil's Retry all come
// through here, so a load that succeeds — on whichever attempt — is followed by
// exactly one `connect`, and a load that fails is followed by none. Connecting
// after a failed load used to leave a request the ticket fence never answers
// (the workspace is not live), and a later successful Retry, which only
// refetched, then had nothing to start the terminal: it sat at `connecting`,
// which offers no reconnect.
async function loadSession(): Promise<void> {
  const id = props.id;
  await resource.run();
  // Superseded while loading (A → B → C): the later load connects.
  if (props.id !== id || !workspaceLive.value) return;
  void terminal.connect(id);
}

onMounted(() => {
  void loadSession();
});

// The preview lives only as long as the binding it was opened under (#76).
//
// When the binding drops *in place* — the session ended, or a refetch failed —
// the preview closes through the ordinary route: the pane unmounts, which aborts
// an in-flight read and disposes every Monaco model, and on a phone the user is
// returned to the file panel, which now says why. That route pops the one
// same-URL entry this view pushed, and only that one.
//
// When the *route* changed, the entry is disowned instead, exactly as the
// session-switch watcher below does: calling `history.back()` in the middle of
// a navigation is how a router ends up somewhere neither it nor the user chose.
// Both sources are watched together so that the two cases cannot be told apart
// by which watcher happened to run first.
//
// Losing the user — signed out, or `/me` naming someone else — is the second
// kind: the auth-loss handler is already navigating away, so the entry is
// disowned too, and the phone leaves the preview mode so nothing is left
// behind the gate.
watch(
  [
    () => props.id,
    filesSessionId,
    () => auth.isAuthenticated && !auth.discarding,
  ],
  ([id, files, ownUser], [previousId, previousFiles]) => {
    if (!previewPath.value || files === previousFiles) return;
    if (id !== previousId || !ownUser) {
      forgetPlace();
      previewHistoryDepth = 0;
      previewPath.value = null;
      activeTab.value = "cli";
      if (!ownUser) mobileMode.value = "cli";
      return;
    }
    if (files === null) closePreview();
  },
);

// Switching to another session id re-attaches cleanly (dispose is handled by the
// composable's scope teardown on unmount; here we just reconnect).
watch(
  () => props.id,
  async (next, prev) => {
    if (next && next !== prev) {
      // 3. The third way out of a workspace: the route param changes and this
      //    component is *reused*, so neither unmount nor pagehide fires. Without
      //    this the previous session's shell stayed alive, and worse, its id stayed
      //    in `shellSession` — the TERMINAL tab here would then show the terminal
      //    of the session the user just left.
      // Mobile state belongs to the session that was left, and it is cleared
      // *before* anything for the new one runs (plan/29 MS-08 condition 2).
      // The pushed history entry is disowned rather than popped: popping here
      // would fight the navigation that is already in progress.
      forgetPlace();
      previewHistoryDepth = 0;
      previewPath.value = null;
      activeTab.value = "cli";
      mobileMode.value = "cli";
      // The previous session's CLI stops here, before the first await (#76
      // review 4). What follows waits on the network twice — the shell's
      // termination and B's payload — and all that time A's socket was open
      // under a page that already says B: a focused xterm kept sending
      // keystrokes to A. Closing it synchronously leaves nothing to carry
      // them. The composable will try to reconnect it; `cliTicket` abandons
      // that without asking Central, because A is no longer the route. The
      // page itself goes inert in the same tick (`workspaceLive`). The
      // shell is closed synchronously too: `closeShell` disconnects before
      // its own first await.
      terminal.disconnect();
      disownPendingShell();
      terminateTarget.value = null;
      await closeShell();
      if (props.id !== next) return;
      await loadSession();
    }
  },
);

// Re-measure when the phone's mode brings the terminal back into view, and when
// the screen rotates (plan/29 MS-09).
//
// A hidden host measures 0x0, and the composable refuses to fit it — correctly,
// because the alternative is sending a nonsense rows/cols pair to the daemon.
// The consequence is that something has to fit it once it is visible again, and
// the existing `activeTab` watcher does not fire when only the mode changed.
//
// Nothing here relaxes the contract underneath: the composable still clamps to
// 2-300 x 2-500, still sends only a size that actually changed, and still
// refuses to send at all as a viewer.
watch(mobileMode, async (mode) => {
  if (mode !== "cli") return;
  await nextTick();
  terminal.fit();
});

function onOrientationChange(): void {
  // Same debounce the composable already uses for window resizes rather than a
  // second timing scheme: rotation is a resize that announces itself early, and
  // the layout has not settled when the event fires.
  window.setTimeout(() => terminal.fit(), 100);
}

// `popstate` is only listened to while this view is mounted, and the handler
// ignores events it did not cause.
onMounted(() => {
  window.addEventListener("popstate", onPopState);
  window.addEventListener("orientationchange", onOrientationChange);
});
onBeforeUnmount(() => {
  window.removeEventListener("popstate", onPopState);
  window.removeEventListener("orientationchange", onOrientationChange);
  // Disowned, not popped: unmount happens during a navigation, and calling
  // `history.back()` inside one is how a router ends up somewhere neither it
  // nor the user chose. The entry is same-URL, so what remains is one extra
  // Back press on the way out — the residual is recorded as MS-OM-07 rather
  // than hidden.
  previewHistoryDepth = 0;
});

// Recolour in place when the theme changes. Three consumers, one source: the
// CLI terminal, the system terminal and Monaco. `terminal.options.theme = ...`
// repaints without touching the buffer, and `monaco.editor.setTheme` is global
// and needs neither a new editor nor a new model, so the scroll position,
// folding state and find matches all survive (`FR-TERM-001.AC-15`).
//
// Rebuilding either one here would break the promise this whole ticket rests
// on: switching theme must not interrupt work.
watch(
  // `renderedTheme`, not `theme`: on a narrow viewport the painted palette is
  // pocket regardless of what the user chose, and the terminal has to be told
  // the same thing the stylesheet was (plan/29 MS-20).
  () => preferences.renderedTheme,
  (id) => {
    terminal.applyTheme(id);
    shellTerminal.applyTheme(id);
    // Monaco is deliberately absent from this list. Importing its setup here
    // would pull the whole editor bundle into this view's module graph, which
    // is exactly what the async PreviewPane exists to avoid — the workspace
    // would load Monaco even for a user who never opens a file. PreviewPane
    // owns Monaco, so it owns Monaco's theme.
  },
);

// A font-size change alters the cell size, so rows and columns change and the
// daemon has to be told. It goes through the composable's own fit path, which
// still refuses to send a 0x0 from a hidden panel.
watch(
  () => preferences.terminalFontSize,
  (size) => {
    terminal.setFontSize(size);
    shellTerminal.setFontSize(size);
  },
);

async function confirmTerminate(): Promise<void> {
  const target = terminateTarget.value;
  if (!target || target.id !== props.id || !workspaceLive.value) {
    terminateTarget.value = null;
    return;
  }
  busy.value = true;
  actionError.value = "";
  try {
    await sessions.terminate(target.id);
    if (props.id === target.id) {
      terminateTarget.value = null;
    } else if (resource.data.value?.id === props.id) {
      // The route moved on while the request was out. The store keeps the
      // terminated payload as `current`; the page now belongs to another
      // session, whose own payload is put back (or, still loading, lands
      // when it arrives).
      sessions.current = resource.data.value;
    }
  } catch (caught) {
    if (props.id === target.id) {
      actionError.value =
        caught instanceof ApiError ? caught.message : "Terminate failed.";
    }
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <!-- fill: this page is a fixed layout that owns the viewport. The terminal's
       height comes from the shell, so nothing here re-derives it (plan/09 D1). -->
  <AppLayout fill>
    <!-- The workspace container is never unmounted: the terminal host lives
         inside it, and xterm cannot survive its container being replaced.
         Loading / forbidden / error therefore render as an overlay on top
         rather than instead of it (WT-02). -->
    <div class="workspace">
      <!-- Everything but the veil carries `behindVeil`: inert whenever the
           veil is up — in particular from the tick the route id changes in
           place until the new session has loaded, while this still shows the
           one that was left (#76 review 4). -->
      <SessionHeader
        v-if="session"
        v-bind="behindVeil"
        :name="session.name"
        :node-name="nodePosture?.name"
        :runtime="session.runtime"
        :workspace="session.workspace"
        :sandbox-bypassed="sandboxBypassed"
        :privileged-node="privilegedNode"
        :can-takeover="canTakeover"
        :is-viewer="terminal.role.value === 'viewer'"
        :can-retry="terminal.canRetry.value"
        :can-terminate="canTerminate"
        :busy="busy"
        :compact="compactHeader"
        @takeover="terminal.takeover()"
        @reconnect="terminal.retry()"
        @terminate="askTerminate()"
      />

      <!-- Notices, not toasts. A failure that removes itself is a failure the
           user may never have read, and the gap banner in particular is
           explaining why output is missing — it has to stay while the gap
           does. -->
      <div
        v-if="actionError || terminal.gap.value"
        v-bind="behindVeil"
        class="notices"
      >
        <UiInlineNotice
          v-if="actionError"
          tone="error"
          :message="actionError"
        />
        <UiInlineNotice
          v-if="terminal.gap.value"
          tone="warning"
          message="顯示最新輸出片段（先前歷史已截斷）。"
        />
      </div>

      <!-- The phone's two top-level places, directly visible rather than
           behind a menu (plan/29 MS-07). It is a tablist because that is what
           it is: two panels, one shown at a time, and the files tab controls
           the panel the drawer button controls at wider widths — so the "the
           file panel is reachable at every width" invariant holds through the
           same attribute. Hidden under preview, which is fullscreen. -->
      <nav
        v-if="isNarrow && session && mobileMode !== 'preview'"
        v-bind="behindVeil"
        class="modes"
        role="tablist"
        aria-label="工作區"
      >
        <button
          type="button"
          role="tab"
          :aria-selected="mobileMode === 'cli'"
          aria-controls="panel-cli"
          @click="mobileMode = 'cli'"
        >
          終端機
        </button>
        <button
          type="button"
          role="tab"
          :aria-selected="mobileMode === 'files'"
          aria-controls="file-panel"
          @click="mobileMode = 'files'"
        >
          檔案
        </button>
      </nav>

      <div
        v-bind="behindVeil"
        class="grid"
        :style="{ '--inspector-width': `${preferences.inspectorWidth}px` }"
        :data-files-hidden="filesVisible ? undefined : ''"
        :data-drawer="filesAreDrawer ? '' : undefined"
        :data-mobile="isNarrow ? '' : undefined"
        @dragover="swallowStrayDrop"
        @drop="swallowStrayDrop"
      >
        <div class="center">
          <WorkspaceTabs
            :tabs="tabs"
            :active="activeTab"
            @select="(id) => (activeTab = id as CentreTab)"
            @close="closeTab"
          >
            <template #end>
              <!-- The drawer's opening control. What this replaces was a
                   `display: none` on the tree below 1100px with no way at all
                   to bring it back, which is the one shape the shared
                   foundation names as forbidden. -->
              <UiIconButton
                v-if="filesAreDrawer && session"
                ref="drawerButton"
                variant="on-terminal"
                :label="filesOpen ? '關閉檔案欄' : '開啟檔案欄'"
                :expanded="filesOpen"
                controls="file-panel"
                @click="filesOpen = !filesOpen"
              >
                <PanelRight />
              </UiIconButton>
            </template>
          </WorkspaceTabs>
          <div class="panes">
            <!-- The terminal panel is hidden, never unmounted: unmounting it
               would tear down a live WebSocket and an xterm buffer that the
               user expects to find unchanged when they come back (D4). -->
            <section
              v-show="activeTab === 'cli'"
              id="panel-cli"
              class="pane terminal-pane"
              role="tabpanel"
              aria-labelledby="tab-cli"
              :data-drag="dragActive || undefined"
              @dragover="onDragOver"
              @dragleave="dragActive = false"
              @drop="onTerminalDrop"
            >
              <!-- Image drop bar. Only rendered when the permission AND the node
                 both allow it: a control that can never work is worse than no
                 control, because the user spends time guessing why (ADR 0024). -->
              <!-- Behaviour untouched (ADR 0024): the same display condition,
                   the same accepted types, the same refusal text and the same
                   writer gate. What changed is that it is a toolbar sitting on
                   the terminal surface rather than a bare flex row, so its text
                   uses --text-on-terminal instead of the panel text colour —
                   which in a light theme would be near-black on a dark
                   terminal. -->
              <UiToolbar
                v-if="canUploadImages"
                class="drop-bar"
                label="圖片投放"
                on-terminal
              >
                <UiButton
                  variant="secondary"
                  :disabled="!isWriter || imageDrop.state.value === 'uploading'"
                  :disabled-reason="
                    isWriter ? '上傳中…' : '取得寫入權後可投放圖片'
                  "
                  @click="pickerInput?.click()"
                >
                  投放圖片
                </UiButton>
                <input
                  ref="pickerInput"
                  type="file"
                  class="visually-hidden"
                  accept="image/png,image/jpeg,image/gif,image/webp"
                  @change="onPicked"
                />
                <span
                  v-if="imageDrop.state.value === 'uploading'"
                  class="drop-status"
                  role="status"
                >
                  上傳中 {{ Math.round(imageDrop.progress.value * 100) }}%
                </span>
                <template v-else-if="imageDrop.state.value === 'done'">
                  <img
                    v-if="imageDrop.current.value"
                    :src="imageDrop.current.value.previewUrl"
                    class="thumb"
                    alt=""
                  />
                  <span class="drop-status" role="status">
                    已加入 {{ imageDrop.current.value?.label }} →
                    <code>{{ imageDrop.current.value?.storedPath }}</code>
                  </span>
                  <button type="button" class="link" @click="imageDrop.clear()">
                    收起
                  </button>
                </template>
                <span
                  v-else-if="imageDrop.state.value === 'error'"
                  class="drop-status bad"
                  role="alert"
                >
                  {{ imageDrop.errorMessage.value }}
                </span>
                <span v-else class="drop-hint">
                  可貼上（Ctrl+V）、拖放，或按上方按鈕選檔
                </span>
              </UiToolbar>
              <div
                ref="host"
                class="terminal-host"
                aria-label="Interactive CLI terminal"
                @paste.capture="onTerminalPaste"
              />
            </section>

            <!-- System terminal. Same hide-don't-unmount rule as the CLI panel: it
               holds a live WebSocket to a session on the node. -->
            <section
              v-if="canOpenShell"
              v-show="activeTab === 'terminal'"
              id="panel-terminal"
              class="pane terminal-pane"
              role="tabpanel"
              aria-labelledby="tab-terminal"
            >
              <p class="shell-notice" role="note">
                系統終端機：直接操作此 Node 的 shell，<strong
                  >不受 workspace 路徑限制</strong
                >。指令內容不會被記錄。<template v-if="privilegedNode">
                  此 Node <strong>可經 sudo 取得 root</strong>（ADR
                  0023）。</template
                >
              </p>
              <div
                ref="shellHost"
                class="terminal-host"
                aria-label="System terminal"
              />
              <p class="terminal-hint">
                滾輪可往上檢視先前輸出（按 <kbd>q</kbd> 回到即時輸出）·
                選取文字請按住 <kbd>Shift</kbd> 拖曳
              </p>
              <p
                v-if="shellState === 'starting'"
                class="shell-status"
                role="status"
              >
                正在開啟系統終端機…
              </p>
              <p
                v-else-if="shellState === 'error'"
                class="shell-status bad"
                role="alert"
              >
                {{ shellError }}
                <button class="link" type="button" @click="openShellTab()">
                  重試
                </button>
              </p>
            </section>

            <!-- The preview is mounted only while a file is open: closing it must
               dispose Monaco and its models, and unmounting costs nothing here
               because there is no connection behind it. -->
            <section
              v-if="previewPath"
              v-show="activeTab === 'preview'"
              id="panel-preview"
              class="pane"
              role="tabpanel"
              aria-labelledby="tab-preview"
            >
              <PreviewPane
                :session-id="filesSessionId"
                :rel-path="previewPath"
                :can-download="canDownloadFiles"
                :downloading="fileDownload.activePath.value === previewPath"
                @download="downloadFile"
                @close="closePreview"
              />
              <!-- Kept until dismissed, the same rule the upload list follows:
                   an error that disappears on its own is an error nobody read. -->
              <p
                v-if="fileDownload.errorMessage.value"
                class="upload-refusal"
                role="alert"
              >
                {{ fileDownload.errorMessage.value }}
                <button
                  type="button"
                  class="link"
                  @click="fileDownload.clearError()"
                >
                  關閉
                </button>
              </p>
            </section>
          </div>
        </div>

        <!-- Keyboard-operable as well as draggable. A resize that only a mouse
             can perform is a feature only a mouse user has. -->
        <button
          v-if="filesVisible && !filesAreDrawer"
          type="button"
          class="resizer"
          role="separator"
          aria-orientation="vertical"
          aria-label="調整檔案欄寬度"
          :aria-valuenow="preferences.inspectorWidth"
          :aria-valuemin="INSPECTOR_MIN"
          :aria-valuemax="INSPECTOR_MAX"
          @pointerdown="startResize"
          @keydown="onResizeKey"
        />

        <div
          v-if="filesAreDrawer && filesOpen"
          class="drawer-scrim"
          @click="filesOpen = false"
        />
        <aside
          v-if="session && filesVisible"
          id="file-panel"
          ref="filePanel"
          class="rail"
        >
          <!-- One level at a time on a phone, the full tree elsewhere. Same
               store, same session binding, same abort/wipe — only the
               presentation differs (plan/29 MS-14). -->
          <FileBrowser
            v-if="isNarrow"
            :session-id="filesSessionId"
            :root-label="workspaceLabel"
            :can-browse="canBrowseFiles"
            :disabled-reason="filesDisabledReason"
            :resume="browserResume"
            @open="openPreview"
            @remember="rememberPlace"
            @resumed="onBrowserResumed"
          />
          <FileTree
            v-else
            :session-id="filesSessionId"
            :root-label="workspaceLabel"
            :can-browse="canBrowseFiles"
            :can-upload="canUploadFiles"
            :disabled-reason="filesDisabledReason"
            @open="openPreview"
            @clear="closePreview"
            @upload="uploadFiles"
            @upload-refused="(message: string) => (uploadRefusal = message)"
          />

          <!-- Upload list. Kept until dismissed when anything failed: an error
               that disappears on its own is an error nobody read. -->
          <p v-if="uploadRefusal" class="upload-refusal" role="alert">
            {{ uploadRefusal }}
          </p>
          <p
            v-if="fileUpload.batchRefusal.value"
            class="upload-refusal"
            role="alert"
          >
            {{ fileUpload.batchRefusal.value }}
          </p>
          <ul
            v-if="fileUpload.items.value.length"
            class="uploads"
            aria-label="上傳進度"
          >
            <li
              v-for="item in fileUpload.items.value"
              :key="item.id"
              :data-state="item.state"
            >
              <span class="up-name" :title="item.name">{{ item.name }}</span>
              <span class="up-dir">→ {{ item.directory }}/</span>
              <span v-if="item.state === 'uploading'" class="up-state">
                {{ Math.round(item.progress * 100) }}%
              </span>
              <span v-else-if="item.state === 'queued'" class="up-state">
                等待中
              </span>
              <span v-else-if="item.state === 'done'" class="up-state ok">
                已上傳
              </span>
              <template v-else>
                <span class="up-state bad">{{ item.errorMessage }}</span>
                <button
                  v-if="item.errorCode === 'FILE_EXISTS'"
                  type="button"
                  class="link"
                  @click="renameAndRetry(item.id)"
                >
                  改名重試
                </button>
              </template>
            </li>
          </ul>
          <p
            v-if="fileUpload.items.value.some((i) => i.state === 'error')"
            class="upload-note"
          >
            上傳只會新增檔案，不會覆寫也不會刪除；要取代或刪除請在該 Node 上以
            終端機處理。
            <button type="button" class="link" @click="fileUpload.clear()">
              清除清單
            </button>
          </p>
        </aside>
      </div>

      <!-- The status bar is the workspace's last row, not a shell row: its
           three facts only exist on a page that has a session (style.md §9 was
           revised to say so). It renders even under the veil — a blank status
           bar behind a failure reads as "everything is fine back here". -->
      <StatusBar
        v-bind="behindVeil"
        :session-status="session?.status"
        :connection="terminal.status.value"
        :role="terminal.role.value"
        :load-error="resource.state.value === 'error'"
      >
        <!-- Terminal font size only. The theme used to sit here too, but a
             theme is a global preference and a copy of it beside a
             terminal-specific control made it look page-scoped; it lives in
             personal settings now. Font size stays because it is genuinely
             about this terminal, and because at 1024x768 it is how the row
             count is recovered. -->
        <template #preferences>
          <TerminalFontControl />
        </template>
      </StatusBar>

      <!-- Signed out, or not sure as whom, is not this veil's job: `App.vue`
           makes the whole page inert behind `AuthGate` (#76). -->
      <div v-if="!workspaceLive" class="veil">
        <!-- Three different situations, three different components. What was
             here printed the state's internal name on screen for all three.
             A route change that has not started its fetch yet (the old
             shell is still being closed) is loading too: the previous
             fetch's `success` is not about this id. -->
        <UiLoadingState
          v-if="
            resource.state.value === 'loading' ||
            resource.state.value === 'success'
          "
          label="正在載入 Session"
        />
        <UiInlineNotice
          v-else-if="resource.state.value === 'forbidden'"
          tone="error"
          title="無法存取此 Session"
          message="你的角色沒有檢視這個 Session 的權限。UI 隱藏不能取代伺服器授權：即使入口可見，伺服器仍會拒絕。"
        />
        <!-- ErrorNotice keeps the four-part shape from the error catalogue:
             what happened, why, what to do, and the request id that ties this
             screen to the server log line. -->
        <ErrorNotice
          v-else
          :error="resource.error.value"
          @retry="loadSession()"
        />
      </div>
    </div>

    <ConfirmDialog
      :open="terminateTarget !== null"
      :busy="busy"
      danger
      title="終止此 Session？"
      confirm-label="確認終止"
      @confirm="confirmTerminate"
      @cancel="terminateTarget = null"
    >
      <!-- The name is shown and marked up as a name. A `message: string` prop
           could only concatenate it into prose, where it reads as part of the
           sentence rather than as the thing about to be stopped. -->
      <p>
        將終止 <code>{{ terminateTarget?.name }}</code
        >，此 Node 上的 CLI 程序會被停止。已產生的輸出不會保留。
      </p>
    </ConfirmDialog>
  </AppLayout>
</template>

<style scoped>
/* The height comes from AppLayout's fill mode — deliberately not recomputed
 * here. The previous `calc(100vh - header - 48px)` was 16px taller than the
 * space main actually offered, which is why this page always had a small page
 * scrollbar (plan/09 D1). */
.workspace {
  position: relative;
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}
.notices {
  display: grid;
  gap: 6px;
  margin-bottom: 8px;
  flex-shrink: 0;
}
/* The file column's width is a preference, clamped by the tokens rather than by
   numbers repeated here (220-360px). It used to be a hard-coded 300px that
   vanished entirely below 1100px — with no way to get it back, which is the
   shape the shared foundation forbids. */
.grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto var(--inspector-width);
  gap: 0;
  flex: 1;
  min-height: 0;
}
.grid[data-files-hidden] {
  grid-template-columns: minmax(0, 1fr);
}
/* Tab bar plus exactly one visible panel. The selected panel gets the whole
   centre column: splitting it left both halves too small to work in (WT-03). */
/* Tab bar plus exactly one visible panel, as a flex column rather than a row
   template: the panels are conditional, and a two-row template hands the 1fr to
   whichever child happens to land in it (plan/09 D3). The panels stack in one
   flex slot via `.panes`. */
.center {
  display: flex;
  flex-direction: column;
  min-height: 0;
  min-width: 0;
  border: 1px solid var(--border-subtle);
  border-right: 0;
  border-radius: var(--radius-panel) 0 0 var(--radius-panel);
  overflow: hidden;
  background: var(--terminal-background);
}
.grid[data-files-hidden] .center {
  border-right: 1px solid var(--border-subtle);
  border-radius: var(--radius-panel);
}
/* One flex slot holding every panel, so a hidden panel costs no space and no
   panel is unmounted to hide it. */
.panes {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  min-width: 0;
}
/* No absolute positioning needed: only one panel is ever visible, and `v-show`
   hides the others with an inline `display: none` that wins over this rule. So
   the visible one is simply the flex child that grows. */
.pane {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  min-width: 0;
}
.rail {
  border: 1px solid var(--border-subtle);
  border-left: 0;
  border-radius: 0 var(--radius-panel) var(--radius-panel) 0;
  background: var(--surface-default);
  padding: 10px;
  overflow: auto;
  min-width: 0;
}
/* Drag handle. Keyboard-operable as well as draggable: `role="separator"` with
   `aria-valuenow` and the arrow keys, because a mouse-only resize is a
   mouse-only feature. */
.resizer {
  width: 6px;
  cursor: col-resize;
  border: 0;
  padding: 0;
  background: var(--border-subtle);
}
.resizer:hover,
.resizer:focus-visible {
  background: var(--accent-primary);
}
/* 768-1023px and below: an overlay drawer, and the toolbar has a button that
   opens it. `position: fixed; inset` rather than any viewport height unit —
   plan/09 D1 keeps viewport height in the app shell alone. */
.grid[data-drawer] .rail {
  position: fixed;
  inset: 0 0 0 auto;
  z-index: 18;
  width: min(320px, 88vw);
  border-radius: 0;
  border-left: 1px solid var(--border-subtle);
  box-shadow: var(--shadow-overlay);
}
.drawer-scrim {
  position: fixed;
  inset: 0;
  z-index: 17;
  background: var(--surface-scrim);
}
.rail h2 {
  margin: 0 0 8px;
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--text-secondary);
}
/* A column, not a row template. The template this replaces
 * (`auto minmax(0,1fr) auto`) assumed three children — true for the system
 * terminal, but the CLI panel has one, so auto-placement put the terminal host
 * in the leading `auto` row and its height became "whatever xterm already is".
 * With xterm's default 24 rows that self-stabilised: the host measured exactly
 * the terminal it contained, so FitAddon kept proposing 24 rows at every window
 * size, and the CLI sat at roughly half the pane forever.
 *
 * flex removes the assumption instead of correcting the count: only the host
 * grows, and adding or removing a notice cannot change that (plan/09 D3). */
.terminal-pane {
  display: flex;
  flex-direction: column;
  background: var(--terminal-background);
  border-radius: var(--radius-panel);
  overflow: hidden;
}
/* All three are conditional or short: present or not, they must not affect who
   gets the slack. */
.shell-notice,
.shell-status,
.terminal-hint {
  flex: 0 0 auto;
}
/* Scrolling and selecting both changed behaviour with the tmux mouse mode that
   made scrolling work at all (ADR 0023): the wheel now drives tmux copy mode, and
   drag-select belongs to tmux unless Shift is held. Neither is discoverable, so
   the two sentences live under the terminal rather than in a release note nobody
   re-reads. Note it is Shift+*drag*, not Shift+wheel — xterm.js ignores a wheel
   event with Shift held. */
.terminal-hint {
  margin: 0;
  padding: 4px 10px 6px;
  color: var(--text-on-terminal-dim);
  font-size: 11px;
}
.terminal-hint kbd {
  padding: 0 3px;
  border: 1px solid var(--border-on-terminal);
  border-radius: 3px;
  font-family: inherit;
}
/* 不是裝飾：使用者要能分辨自己在哪一種邊界裡（ADR 0021 §4、ADR 0023 D10）。 */
.posture {
  padding: 1px 6px;
  border-radius: var(--radius-pill);
  background: var(--status-warning-bg);
  color: var(--status-warning-fg);
  font-size: 11px;
}
/* Not decoration: the user has to be able to tell which security boundary they
   are inside (ADR 0021 §4). */
.shell-notice {
  margin: 0;
  padding: 6px 10px;
  background: var(--status-warning-bg);
  color: var(--status-warning-fg);
  font-size: 11px;
}
.shell-status {
  margin: 0;
  padding: 6px 10px;
  color: var(--text-on-terminal-dim);
  font-size: 12px;
}
.shell-status.bad {
  color: var(--status-error-fg);
}
/* Covers the workspace while it cannot be used, without unmounting it. */
.veil {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  background: var(--surface-raised);
}
/* No `height: 100%`: inside a flex column it feeds flex-basis, so the host would
 * ask for the whole pane while the notice asks for its own height, and shrinking
 * would decide the outcome. `flex: 1` says the one true thing — take what is
 * left. `min-height: 0` lets it shrink below xterm's rendered height, without
 * which the pane, not the host, would be what overflows. */
.drop-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 0 0 auto;
  padding: 4px 6px;
  font-size: 11px;
  color: var(--text-secondary);
}
.drop-bar .thumb {
  height: 24px;
  width: auto;
  max-width: 48px;
  border-radius: var(--radius-panel);
  object-fit: cover;
}
.drop-status code {
  font-family:
    JetBrains Mono,
    ui-monospace,
    monospace;
}
.drop-status.bad {
  color: var(--status-error-fg);
}
.drop-hint {
  color: var(--text-secondary);
}
.terminal-pane[data-drag] {
  outline: 2px dashed var(--accent-strong);
  outline-offset: -4px;
}
.visually-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
}
.terminal-host {
  flex: 1 1 auto;
  min-height: 0;
  width: 100%;
}
/* Upload list (FU-06). Every row carries text for its state as well as position,
 * because colour alone is not a state signal (style.md). */
.uploads {
  flex: 0 0 auto;
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 11px;
}
.uploads li {
  display: flex;
  align-items: baseline;
  gap: 6px;
  padding: 2px 4px;
  border-radius: var(--radius-panel);
  background: var(--surface-raised);
}
.uploads li[data-state="error"] {
  border: 1px solid var(--status-error-fg);
}
.up-name {
  font-family:
    JetBrains Mono,
    ui-monospace,
    monospace;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.up-dir {
  color: var(--text-secondary);
  white-space: nowrap;
}
.up-state {
  margin-inline-start: auto;
  color: var(--text-primary);
  white-space: nowrap;
}
.up-state.ok {
  color: var(--status-success-fg);
}
.up-state.bad {
  color: var(--status-error-fg);
  white-space: normal;
}
.upload-refusal {
  flex: 0 0 auto;
  margin: 0;
  font-size: 11px;
  color: var(--status-error-fg);
}
.upload-note {
  flex: 0 0 auto;
  margin: 0;
  font-size: 11px;
  color: var(--text-secondary);
}

.link {
  border: 0;
  background: none;
  color: var(--accent-strong);
  font-weight: 600;
}

/* Narrow: two modes, one column, no overlay (plan/29 MS-07). */
.modes {
  display: flex;
  gap: 4px;
  padding: 4px;
  margin-bottom: 8px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-control);
  background: var(--surface-raised);
}
.modes button {
  flex: 1;
  min-height: var(--density-touch);
  border: 0;
  border-radius: calc(var(--radius-control) - 2px);
  background: none;
  color: var(--text-secondary);
  font: inherit;
  font-weight: 600;
}
.modes button[aria-selected="true"] {
  background: var(--surface-default);
  color: var(--text-primary);
}
/* One column, and the resizer is meaningless without two. */
.grid[data-mobile] {
  grid-template-columns: minmax(0, 1fr);
}
.grid[data-mobile] .resizer {
  display: none;
}
/* In files mode the rail *is* the column. Not an overlay: an overlay at 390px
   covers the thing it is supposed to sit beside, which makes it a mode with
   extra steps. */
.grid[data-mobile] .rail {
  width: auto;
  border-left: 0;
  border-radius: var(--radius-panel);
}
/* Files mode hides the centre rather than unmounting it: the terminal keeps its
   socket and its buffer, which is the same reason the panels inside it use
   v-show (D4). */
.grid[data-mobile]:not([data-files-hidden]) .center {
  display: none;
}
</style>
