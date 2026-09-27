// The workspace's terminal while this tab's user is gone or unconfirmed (#76).
//
// Unlike the other workspace suites, this one runs the *real*
// `useTerminalSession`: only xterm (it needs a canvas) and the WebSocket are
// replaced. The claim under test is about bytes on a socket — "after the user
// is lost nothing can be typed into the session" — and a mocked composable can
// only say that a method was called, not that no socket could carry input.
//
// The page is mounted under the real `App.vue`, whose gate makes a protected
// page inert, behind the real guard and auth-loss handler.

import { enableAutoUnmount, flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  createMemoryHistory,
  createRouter,
  type RouteComponent,
  type Router,
} from "vue-router";

import { ApiError } from "../api/client";
import type { FileEntry, SessionDetail } from "../api/dto";

// --- xterm: record the input callback so a case can type ------------------
const { terminals } = vi.hoisted(() => ({
  terminals: [] as Array<{
    onData: ReturnType<typeof vi.fn>;
    focus: ReturnType<typeof vi.fn>;
  }>,
}));
vi.mock("@xterm/xterm", () => {
  class MockTerminal {
    rows = 24;
    cols = 80;
    element = globalThis.document?.createElement("div");
    options = {};
    loadAddon = vi.fn();
    open = vi.fn();
    focus = vi.fn();
    write = vi.fn();
    dispose = vi.fn();
    onData = vi.fn();
    onBinary = vi.fn();
    constructor() {
      terminals.push(this as never);
    }
  }
  return { Terminal: MockTerminal };
});
vi.mock("@xterm/addon-fit", () => ({
  FitAddon: vi.fn(() => ({ fit: vi.fn(), proposeDimensions: vi.fn() })),
}));
vi.mock("@xterm/addon-search", () => ({ SearchAddon: vi.fn(() => ({})) }));
vi.mock("@xterm/addon-web-links", () => ({ WebLinksAddon: vi.fn(() => ({})) }));

// --- WebSocket: every instance recorded, lifecycle driven by hand ---------
const sockets: MockSocket[] = [];
class MockSocket {
  static readonly OPEN = 1;
  static readonly CLOSED = 3;
  readyState = 0;
  binaryType = "blob";
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: unknown }) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: (() => void) | null = null;
  sent: unknown[] = [];
  constructor(public url: string) {
    sockets.push(this);
  }
  send(data: unknown) {
    this.sent.push(data);
  }
  close() {
    if (this.readyState === MockSocket.CLOSED) return;
    this.readyState = MockSocket.CLOSED;
    this.onclose?.();
  }
  open() {
    this.readyState = MockSocket.OPEN;
    this.onopen?.();
  }
  emit(data: unknown) {
    this.onmessage?.({ data });
  }
}
class MockObserver {
  observe = vi.fn();
  disconnect = vi.fn();
}

import App from "../App.vue";
import * as router from "../router";
import * as auth from "../stores/auth";
import SessionWorkspaceView from "./SessionWorkspaceView.vue";

const ID = "44444444-4444-4444-8444-444444444444";
const USER_A = {
  id: "user-a",
  username: "alice",
  display_name: "Alice",
  role: "Developer",
  permissions: [],
};

function session(id: string = ID): SessionDetail {
  return {
    id,
    node_id: "11111111-1111-1111-1111-111111111111",
    user_id: "22222222-2222-2222-2222-222222222222",
    name: "refactor-api",
    runtime: "claude",
    workspace: "/srv/work/api",
    status: "running",
    rows: 24,
    columns: 80,
    started_at: "2026-07-31T00:00:00Z",
    last_activity_at: "2026-07-31T00:01:00Z",
    exit_code: null,
    error_message: null,
    capabilities: {
      can_terminate: true,
      can_takeover: true,
      can_browse_files: true,
      can_upload_files: false,
      can_open_shell: false,
    },
  } as SessionDetail;
}

const README = {
  name: "README.md",
  rel_path: "README.md",
  type: "file",
  size: 12,
  modified_at: "2026-09-27T00:00:00Z",
  hidden: false,
  symlink: false,
  excluded: false,
  expandable: false,
} as FileEntry;

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => (resolve = r));
  return { promise, resolve };
}

function stubApi() {
  const calls = {
    attachSession: vi.fn(async () => ({ ticket: "t" })),
    listFileTree: vi.fn(async () => ({
      path: ".",
      truncated: false,
      entries: [README],
    })),
  };
  vi.spyOn(auth, "api").mockReturnValue({
    getSession: vi.fn(async () => session()),
    getNode: vi.fn(async () => {
      throw new ApiError("NOT_FOUND", "no", 404, "r");
    }),
    terminateSession: vi.fn(async () => ({})),
    terminateSessionOnUnload: vi.fn(),
    ...calls,
  } as never);
  return calls;
}

const cleanups: Array<() => void> = [];

async function render(
  login: RouteComponent | (() => Promise<RouteComponent>) = {
    template: '<p class="login-page">login</p>',
  },
): Promise<{ wrapper: ReturnType<typeof mount>; appRouter: Router }> {
  const appRouter = createRouter({
    history: createMemoryHistory(),
    routes: [
      {
        path: "/login",
        name: "login",
        component: login,
        meta: { public: true },
      },
      {
        path: "/dashboard",
        name: "dashboard",
        component: { template: "<p>dashboard</p>" },
      },
      {
        path: "/sessions/:id",
        name: "session-workspace",
        component: SessionWorkspaceView,
        props: true,
      },
    ],
  });
  router.registerGuards(appRouter);
  cleanups.push(router.installAuthLossHandler(appRouter));
  appRouter.push(`/sessions/${ID}`);
  await appRouter.isReady();
  const wrapper = mount(App, {
    attachTo: document.body,
    global: {
      plugins: [appRouter],
      stubs: { AppLayout: { template: "<div><slot /></div>" } },
    },
  });
  await flushPromises();
  return { wrapper, appRouter };
}

/** The live socket, opened, with this tab holding the write lock. */
async function connectedAsWriter(): Promise<MockSocket> {
  await vi.waitFor(() => expect(sockets).toHaveLength(1));
  const socket = sockets[0];
  socket.open();
  socket.emit(
    JSON.stringify({ type: "terminal.role", payload: { role: "writer" } }),
  );
  return socket;
}

/** What xterm calls when the user types. */
function type(text: string): void {
  const onData = terminals[0].onData.mock.calls[0][0] as (d: string) => void;
  onData(text);
}

function inputFrames(socket: MockSocket): number {
  // Binary frames are keystrokes; JSON control text (resize) is not input.
  return socket.sent.filter((frame) => typeof frame !== "string").length;
}

/** Longer than the first reconnect back-off (1s). */
function pastFirstRetry(): Promise<void> {
  return new Promise((r) => setTimeout(r, 1_200));
}

async function expectInertAndFocused(
  wrapper: ReturnType<typeof mount>,
): Promise<void> {
  const dialog = wrapper.get('[role="alertdialog"]');
  const routed = wrapper.get(".routed");
  expect(routed.attributes("inert")).toBeDefined();
  expect(routed.attributes("aria-hidden")).toBe("true");
  expect(routed.find(".terminal-host").exists()).toBe(true);
  await vi.waitFor(() =>
    expect(dialog.element.contains(document.activeElement)).toBe(true),
  );
}

enableAutoUnmount(afterEach);

beforeEach(() => {
  setActivePinia(createPinia());
  localStorage.clear();
  auth.useAuthStore().setTokens({
    access_token: "a-access",
    refresh_token: "a-refresh",
    token_type: "bearer",
  });
  auth.useAuthStore().user = USER_A;
  vi.stubGlobal("WebSocket", MockSocket);
  vi.stubGlobal("ResizeObserver", MockObserver);
  sockets.length = 0;
  terminals.length = 0;
});
afterEach(() => {
  while (cleanups.length) cleanups.pop()!();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe("SessionWorkspaceView — 失去使用者後終端機不能再送出任何輸入（#76）", () => {
  it("登出：socket 立即關閉，打字不送出，也不會重新連線，並離開到登入頁", async () => {
    const api = stubApi();
    const { appRouter } = await render();
    const socket = await connectedAsWriter();
    type("ls");
    expect(inputFrames(socket)).toBe(1);

    auth.useAuthStore().clearTokens();
    // Synchronous with the tokens going, before any render.
    expect(socket.readyState).toBe(MockSocket.CLOSED);
    type("rm -rf .");
    expect(inputFrames(socket)).toBe(1);

    await flushPromises();
    await pastFirstRetry();
    expect(sockets).toHaveLength(1);
    expect(api.attachSession).toHaveBeenCalledTimes(1);
    expect(appRouter.currentRoute.value.name).toBe("login");
  });

  it("前往登入頁的導覽失敗：頁面維持 inert、終端機維持停止，對話框提供可用的登入連結", async () => {
    const api = stubApi();
    const { wrapper, appRouter } = await render(() =>
      Promise.reject(new Error("chunk failed to load")),
    );
    const socket = await connectedAsWriter();

    auth.useAuthStore().clearTokens();
    await flushPromises();
    await vi.waitFor(() =>
      expect(wrapper.find('[role="alertdialog"]').exists()).toBe(true),
    );

    // Still on the workspace — the navigation failed — and still locked.
    expect(appRouter.currentRoute.value.name).toBe("session-workspace");
    await expectInertAndFocused(wrapper);
    const link = wrapper.get('[data-action="auth-gate"]');
    expect(link.element.tagName).toBe("A");
    expect(link.attributes("href")).toBe(`/login?redirect=/sessions/${ID}`);

    type("whoami");
    expect(inputFrames(socket)).toBe(0);
    await pastFirstRetry();
    expect(sockets).toHaveLength(1);
    expect(api.attachSession).toHaveBeenCalledTimes(1);
    // And it stays that way.
    expect(wrapper.get(".routed").attributes("inert")).toBeDefined();
  });

  it("身分未確認（另一個分頁換了 token）：停止並 inert；/me 確認同一人後以新 ticket 重新連線", async () => {
    const api = stubApi();
    // The storage sync asks `/me` through its own module's client, which the
    // `api` spy does not reach, so `/me` is answered at `fetch`.
    const held = deferred<void>();
    const me = vi.fn(async () => {
      await held.promise;
      return new Response(JSON.stringify(USER_A), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });
    vi.stubGlobal("fetch", me);
    auth._resetApiClient();
    cleanups.push(() => auth._resetApiClient());
    cleanups.push(auth.installAuthStorageSync());
    const { wrapper } = await render();
    const socket = await connectedAsWriter();

    localStorage.setItem("cliora.access_token", "x-access");
    window.dispatchEvent(
      new StorageEvent("storage", { key: "cliora.access_token" }),
    );
    expect(socket.readyState).toBe(MockSocket.CLOSED);
    await flushPromises();
    await expectInertAndFocused(wrapper);
    expect(wrapper.get('[role="alertdialog"]').attributes("data-reason")).toBe(
      "pending",
    );

    type("id");
    expect(inputFrames(socket)).toBe(0);
    await pastFirstRetry();
    // The composable tried to reconnect; the ticket was refused without
    // asking Central, so no socket was opened.
    expect(api.attachSession).toHaveBeenCalledTimes(1);
    expect(sockets).toHaveLength(1);

    expect(me).toHaveBeenCalledTimes(1);
    held.resolve();
    await flushPromises();
    await vi.waitFor(() => expect(sockets).toHaveLength(2));
    expect(api.attachSession).toHaveBeenCalledTimes(2);
    expect(wrapper.find('[role="alertdialog"]').exists()).toBe(false);
    expect(wrapper.get(".routed").attributes("inert")).toBeUndefined();
  });
});

// --- Changing /sessions/:id in place (#76 review 4) -------------------------
//
// The route component is reused, so nothing unmounts: whatever session A left
// behind has to be stopped by the view itself, before it waits for anything
// about session B. Two ways A can still carry input meant for B: its open
// socket, and an attach request for A answered after the switch.

const OTHER = "55555555-5555-4555-8555-555555555555";

/** Session and attach responses per id; any id can be held until released. */
function stubSwitchApi() {
  const heldSession = new Map<string, ReturnType<typeof deferred<void>>>();
  const heldAttach = new Map<string, ReturnType<typeof deferred<void>>>();
  const failing = new Set<string>();
  const attachSession = vi.fn(async (id: string) => {
    await heldAttach.get(id)?.promise;
    return { ticket: `ticket-${id}` };
  });
  vi.spyOn(auth, "api").mockReturnValue({
    getSession: vi.fn(async (id: string) => {
      await heldSession.get(id)?.promise;
      if (failing.delete(id)) {
        throw new ApiError("UPSTREAM_BROKE", "no", 502, "r");
      }
      return session(id);
    }),
    getNode: vi.fn(async () => {
      throw new ApiError("NOT_FOUND", "no", 404, "r");
    }),
    terminateSession: vi.fn(async () => ({})),
    terminateSessionOnUnload: vi.fn(),
    listFileTree: vi.fn(async () => ({
      path: ".",
      truncated: false,
      entries: [README],
    })),
    attachSession,
  } as never);
  return {
    attachSession,
    holdSession(id: string) {
      const gate = deferred<void>();
      heldSession.set(id, gate);
      return () => gate.resolve();
    },
    /** The next fetch of this session fails with a retryable error. */
    failSessionOnce(id: string) {
      failing.add(id);
    },
    holdAttach(id: string) {
      const gate = deferred<void>();
      heldAttach.set(id, gate);
      return () => gate.resolve();
    },
    attachesFor(id: string): number {
      return attachSession.mock.calls.filter(([asked]) => asked === id).length;
    },
  };
}

function socketsFor(id: string): MockSocket[] {
  return sockets.filter((socket) =>
    socket.url.includes(`/ws/sessions/${id}/terminal`),
  );
}

describe("SessionWorkspaceView — 原地切換 session：舊 session 的終端機不能再收到輸入（#76）", () => {
  it("B 的 session 還在載入：A 的 socket 在第一個 await 之前就關閉，打字不送給 A，舊工作區 inert，A 不會重新連線", async () => {
    const api = stubSwitchApi();
    const { wrapper, appRouter } = await render();
    const a = await connectedAsWriter();
    type("ls");
    expect(inputFrames(a)).toBe(1);

    const releaseB = api.holdSession(OTHER);
    await appRouter.push(`/sessions/${OTHER}`);
    // Nothing about B has answered yet: this is the window the user can type
    // into.
    expect(a.readyState).toBe(MockSocket.CLOSED);
    type("rm -rf .");
    expect(inputFrames(a)).toBe(1);
    // The workspace that still shows A is out of the focus order and the
    // accessibility tree, not merely drawn over.
    const grid = wrapper.get(".grid");
    expect(grid.attributes("inert")).toBeDefined();
    expect(grid.attributes("aria-hidden")).toBe("true");

    // A's close schedules the composable's reconnect; it must not get a
    // ticket for the session that was left, nor open a socket.
    await pastFirstRetry();
    expect(api.attachesFor(ID)).toBe(1);
    expect(sockets).toHaveLength(1);

    releaseB();
    await flushPromises();
    await vi.waitFor(() => expect(socketsFor(OTHER)).toHaveLength(1));
    const b = socketsFor(OTHER)[0];
    b.open();
    b.emit(
      JSON.stringify({ type: "terminal.role", payload: { role: "writer" } }),
    );
    expect(wrapper.get(".grid").attributes("inert")).toBeUndefined();
    type("pwd");
    expect(inputFrames(b)).toBe(1);
    expect(inputFrames(a)).toBe(1);

    // And no reconnect storm on B afterwards.
    await pastFirstRetry();
    expect(sockets).toHaveLength(2);
    expect(b.readyState).toBe(MockSocket.OPEN);
    expect(api.attachesFor(OTHER)).toBe(1);
  });

  it("A 的 ticket 在 B 連上之後才回來：不開 A 的 socket，B 維持連線", async () => {
    const api = stubSwitchApi();
    const releaseA = api.holdAttach(ID);
    const { appRouter } = await render();
    await vi.waitFor(() => expect(api.attachesFor(ID)).toBe(1));
    expect(sockets).toHaveLength(0);

    await appRouter.push(`/sessions/${OTHER}`);
    await flushPromises();
    await vi.waitFor(() => expect(socketsFor(OTHER)).toHaveLength(1));
    const b = socketsFor(OTHER)[0];
    b.open();

    releaseA();
    await flushPromises();
    expect(socketsFor(ID)).toHaveLength(0);

    await pastFirstRetry();
    expect(socketsFor(ID)).toHaveLength(0);
    expect(sockets).toHaveLength(1);
    expect(b.readyState).toBe(MockSocket.OPEN);
    expect(api.attachesFor(OTHER)).toBe(1);
  });

  it("A 的 ticket 比 B 的先回來：不開 A 的 socket，只連上 B", async () => {
    const api = stubSwitchApi();
    const releaseA = api.holdAttach(ID);
    const releaseAttachB = api.holdAttach(OTHER);
    const { appRouter } = await render();
    await vi.waitFor(() => expect(api.attachesFor(ID)).toBe(1));

    await appRouter.push(`/sessions/${OTHER}`);
    await flushPromises();
    await vi.waitFor(() => expect(api.attachesFor(OTHER)).toBe(1));

    releaseA();
    await flushPromises();
    expect(sockets).toHaveLength(0);

    releaseAttachB();
    await flushPromises();
    await vi.waitFor(() => expect(sockets).toHaveLength(1));
    expect(socketsFor(OTHER)).toHaveLength(1);
    const b = socketsFor(OTHER)[0];
    b.open();

    await pastFirstRetry();
    expect(socketsFor(ID)).toHaveLength(0);
    expect(sockets).toHaveLength(1);
    expect(b.readyState).toBe(MockSocket.OPEN);
  });

  it("A 的 ticket 在 B 的 session 還在載入時回來：不開 A 的 socket", async () => {
    const api = stubSwitchApi();
    const releaseA = api.holdAttach(ID);
    const { appRouter } = await render();
    await vi.waitFor(() => expect(api.attachesFor(ID)).toBe(1));

    const releaseB = api.holdSession(OTHER);
    await appRouter.push(`/sessions/${OTHER}`);
    releaseA();
    await flushPromises();
    expect(sockets).toHaveLength(0);

    releaseB();
    await flushPromises();
    await vi.waitFor(() => expect(sockets).toHaveLength(1));
    expect(socketsFor(OTHER)).toHaveLength(1);
    expect(socketsFor(ID)).toHaveLength(0);
  });
});

// --- A failed session fetch, then Retry (#76 review 5) ----------------------
//
// The CLI connects after a *successful* load of the route's session, whichever
// path produced it: mount, an in-place route change, or the veil's Retry.
// Exactly once: one socket for the session, none for anything else.

async function retryFromVeil(wrapper: ReturnType<typeof mount>): Promise<void> {
  await wrapper.get(".veil button.retry").trigger("click");
  await flushPromises();
}

describe("SessionWorkspaceView — session 載入失敗後重試：CLI 只連線一次（#76）", () => {
  it("A 已連線，切到 B 失敗後重試成功：只開一個 B 的 socket", async () => {
    const api = stubSwitchApi();
    const { wrapper, appRouter } = await render();
    const a = await connectedAsWriter();

    api.failSessionOnce(OTHER);
    await appRouter.push(`/sessions/${OTHER}`);
    await flushPromises();
    expect(a.readyState).toBe(MockSocket.CLOSED);
    expect(wrapper.get(".grid").attributes("inert")).toBeDefined();
    expect(api.attachesFor(OTHER)).toBe(0);

    await retryFromVeil(wrapper);
    await vi.waitFor(() => expect(socketsFor(OTHER)).toHaveLength(1));
    socketsFor(OTHER)[0].open();
    expect(wrapper.get(".grid").attributes("inert")).toBeUndefined();

    await pastFirstRetry();
    expect(socketsFor(OTHER)).toHaveLength(1);
    expect(socketsFor(OTHER)[0].readyState).toBe(MockSocket.OPEN);
    expect(api.attachesFor(OTHER)).toBe(1);
    expect(sockets).toHaveLength(2);
  });

  it("A 從未開出 socket（ticket 還在路上），切到 B 失敗後重試成功：只開一個 B 的 socket，A 的 ticket 遲到也不開", async () => {
    const api = stubSwitchApi();
    const releaseA = api.holdAttach(ID);
    const { wrapper, appRouter } = await render();
    await vi.waitFor(() => expect(api.attachesFor(ID)).toBe(1));

    api.failSessionOnce(OTHER);
    await appRouter.push(`/sessions/${OTHER}`);
    await flushPromises();

    await retryFromVeil(wrapper);
    await vi.waitFor(() => expect(socketsFor(OTHER)).toHaveLength(1));
    socketsFor(OTHER)[0].open();
    releaseA();
    await flushPromises();

    await pastFirstRetry();
    expect(socketsFor(ID)).toHaveLength(0);
    expect(socketsFor(OTHER)).toHaveLength(1);
    expect(socketsFor(OTHER)[0].readyState).toBe(MockSocket.OPEN);
    expect(api.attachesFor(OTHER)).toBe(1);
  });

  it("第一次載入就失敗，重試成功：開一個 socket", async () => {
    const api = stubSwitchApi();
    api.failSessionOnce(ID);
    const { wrapper } = await render();
    expect(sockets).toHaveLength(0);
    expect(api.attachesFor(ID)).toBe(0);

    await retryFromVeil(wrapper);
    await vi.waitFor(() => expect(sockets).toHaveLength(1));
    sockets[0].open();
    await pastFirstRetry();
    expect(sockets).toHaveLength(1);
    expect(api.attachesFor(ID)).toBe(1);
  });
});
