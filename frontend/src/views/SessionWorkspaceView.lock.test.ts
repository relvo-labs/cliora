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

function session(): SessionDetail {
  return {
    id: ID,
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
