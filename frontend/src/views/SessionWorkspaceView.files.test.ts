// The workspace's file panel with the real file components (#76).
//
// `SessionWorkspaceView.test.ts` mocks both FileTree and FileBrowser, because
// its cases are about the shell around them. That is also why #76 was
// invisible there: the defect lived in *who binds the files store*, and a mock
// binds nothing and needs nothing bound. These cases mount the real
// FileBrowser, FileTree and PreviewPane against a stubbed API, so the path from
// "the session payload arrived" to "a listing request left" to "a tapped file
// was read" is exercised end to end. Only xterm and Monaco are replaced — the
// first needs a socket, the second a real DOM layout.

import {
  enableAutoUnmount,
  flushPromises,
  mount,
  type DOMWrapper,
} from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  createMemoryHistory,
  createRouter,
  createWebHistory,
  type Router,
} from "vue-router";

import { ApiError } from "../api/client";
import type { FileEntry, SessionDetail } from "../api/dto";

const { term } = vi.hoisted(() => ({
  term: {
    mount: vi.fn(),
    connect: vi.fn(async () => {}),
    retry: vi.fn(),
    takeover: vi.fn(),
    disconnect: vi.fn(),
    dispose: vi.fn(),
    fit: vi.fn(),
    focus: vi.fn(),
    proposeSize: vi.fn(() => ({ rows: 24, columns: 80 })),
    applyTheme: vi.fn(),
    setFontSize: vi.fn(),
    typeText: vi.fn(),
    status: { value: "connected" } as { value: string },
    role: { value: "writer" },
    gap: { value: undefined },
    exit: { value: undefined },
    lastError: { value: undefined },
    // The ticket provider the view handed the composable, so a case can ask it
    // for a ticket the way a reconnect would.
    getTicket: undefined as undefined | ((id: string) => Promise<string>),
    canRetry: { value: false },
  },
}));
// `status` is made a real ref so a case can deliver the socket's own exit
// signal — the one `useTerminalSession` sets on `terminal.exited` /
// `session.stopped` — without a session refetch behind it.
vi.mock("../composables/useTerminalSession", async () => {
  const { ref } = await import("vue");
  term.status = ref("connected");
  return {
    useTerminalSession: (getTicket: (id: string) => Promise<string>) => {
      term.getTicket = getTicket;
      return term;
    },
  };
});

// Just enough Monaco for useMonacoModel to create an editor and a model. The
// content that reaches the model is recorded so the test can see that the
// preview really read the file rather than merely opening a tab.
const { shown, models, editors } = vi.hoisted(() => ({
  shown: [] as string[],
  models: [] as Array<{ value: string; disposed: boolean }>,
  editors: [] as Array<{ disposed: boolean }>,
}));
vi.mock("../monaco/setup", () => {
  const monaco = {
    Uri: {
      from: (parts: { path: string; query: string }) =>
        `${parts.query}${parts.path}`,
    },
    editor: {
      create: () => {
        let model: unknown = null;
        const record = { disposed: false };
        editors.push(record);
        return {
          getModel: () => model,
          setModel: (next: unknown) => (model = next),
          updateOptions: () => {},
          trigger: () => {},
          focus: () => {},
          dispose: () => {
            record.disposed = true;
          },
          saveViewState: () => null,
          restoreViewState: () => {},
          revealLine: () => {},
          layout: () => {},
        };
      },
      createModel: (value: string) => {
        shown.push(value);
        const record = { value, disposed: false };
        models.push(record);
        return {
          getValue: () => value,
          setValue: () => {},
          dispose: () => {
            record.disposed = true;
          },
        };
      },
      getModel: () => null,
      setModelLanguage: () => {},
    },
  };
  return {
    PREVIEW_THEME: "cliora-preview",
    setupMonaco: () => monaco,
    setPreviewTheme: () => {},
    monacoLanguage: (hint?: string) => hint ?? "plaintext",
    monacoWorkerCount: () => 0,
  };
});

import * as router from "../router";
import * as auth from "../stores/auth";
import { useFavoritesStore } from "../stores/favorites";
import { useFilesStore } from "../stores/files";
import { useSessionsStore } from "../stores/sessions";
import App from "../App.vue";
import SessionWorkspaceView from "./SessionWorkspaceView.vue";

const ID = "44444444-4444-4444-8444-444444444444";

function session(overrides: Partial<SessionDetail> = {}): SessionDetail {
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
    ...overrides,
  } as SessionDetail;
}

const README: FileEntry = {
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

// A controllable `matchMedia`, so a width change is a real breakpoint change
// that `useBreakpoint` hears, not a second mount at a different width.
let width = 1440;
const listeners = new Set<{
  query: string;
  matches: boolean;
  cb: (e: { matches: boolean }) => void;
}>();
function evaluate(query: string): boolean {
  const min = /min-width:\s*(\d+)px/.exec(query);
  const max = /max-width:\s*(\d+)px/.exec(query);
  if (min && width < Number(min[1])) return false;
  if (max && width > Number(max[1])) return false;
  return true;
}
function installMatchMedia(): void {
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    writable: true,
    value: (query: string) => {
      type Listener = (e: { matches: boolean }) => void;
      const entry = {
        query,
        matches: evaluate(query),
        cb: (() => {}) as Listener,
      };
      return {
        get matches() {
          return evaluate(query);
        },
        addEventListener: (_: string, cb: Listener) =>
          listeners.add(Object.assign(entry, { cb })),
        removeEventListener: () => listeners.delete(entry),
      };
    },
  });
}
function resizeTo(px: number): void {
  width = px;
  for (const entry of listeners) {
    const next = evaluate(entry.query);
    if (next !== entry.matches) {
      entry.matches = next;
      entry.cb({ matches: next });
    }
  }
}

function stubApi(
  getSession: () => Promise<SessionDetail>,
  over: Record<string, unknown> = {},
) {
  const listFileTree = vi.fn(async (_id: string, params: { path: string }) => ({
    path: params.path,
    truncated: false,
    entries: params.path === "." ? [README] : [],
  }));
  const readFileContent = vi.fn(async (_id: string, relPath: string) => ({
    success: true,
    rel_path: relPath,
    size: 12,
    encoding: "utf-8",
    language_hint: "markdown",
    content: "# synthetic\n",
  }));
  vi.spyOn(auth, "api").mockReturnValue({
    getSession: vi.fn(getSession),
    getNode: vi.fn(async () => {
      throw new ApiError("NOT_FOUND", "no", 404, "r");
    }),
    attachSession: vi.fn(async () => ({ ticket: "t" })),
    terminateSession: vi.fn(async () => ({})),
    terminateSessionOnUnload: vi.fn(),
    listFileTree,
    readFileContent,
    ...over,
  } as never);
  return { listFileTree, readFileContent };
}

async function render() {
  const router = createRouter({
    history: createWebHistory(),
    routes: [
      {
        path: "/sessions/:id",
        name: "session-workspace",
        component: SessionWorkspaceView,
      },
    ],
  });
  router.push(`/sessions/${ID}`);
  await router.isReady();
  const wrapper = mount(SessionWorkspaceView, {
    props: { id: ID },
    global: {
      plugins: [router],
      stubs: { AppLayout: { template: "<div><slot /></div>" } },
    },
  });
  await flushPromises();
  return wrapper;
}

async function settle(): Promise<void> {
  // The preview pane is an async component: one macrotask for the dynamic
  // import, then the microtasks it schedules.
  for (let i = 0; i < 3; i += 1) {
    await flushPromises();
    await new Promise((r) => setTimeout(r, 0));
  }
}

// Every case's view is unmounted after it. They all share the one terminal
// mock, so a view left mounted by an earlier case would hear a later case's
// exit signal and act on it.
enableAutoUnmount(afterEach);

beforeEach(() => {
  setActivePinia(createPinia());
  // Signed in, as the router guard guarantees before this view can mount; the
  // signed-out cases at the end of this file replace it with real tokens.
  auth.useAuthStore().accessToken = "test-access";
  listeners.clear();
  width = 1440;
  installMatchMedia();
  shown.length = 0;
  models.length = 0;
  editors.length = 0;
  term.status.value = "connected";
  vi.spyOn(window.history, "pushState").mockImplementation(() => {});
  vi.spyOn(window.history, "back").mockImplementation(() => {});
});
afterEach(() => {
  vi.restoreAllMocks();
  // jsdom has none; leaving ours behind would change what `useBreakpoint`
  // does for anything that runs after this file in the same environment.
  Reflect.deleteProperty(window, "matchMedia");
});

describe("SessionWorkspaceView — 手機上的檔案（#76）", () => {
  it("新 session 進入檔案分頁：列出根目錄，點檔案開啟全幅唯讀預覽並讀取內容", async () => {
    width = 390;
    const { listFileTree, readFileContent } = stubApi(async () => session());
    const wrapper = await render();

    // Nothing is requested until the user actually opens the files mode.
    expect(listFileTree).not.toHaveBeenCalled();
    await wrapper.findAll('.modes [role="tab"]')[1].trigger("click");
    await flushPromises();

    expect(listFileTree).toHaveBeenCalledTimes(1);
    expect(listFileTree.mock.calls[0][0]).toBe(ID);
    expect(listFileTree.mock.calls[0][1]).toMatchObject({ path: "." });
    const row = wrapper
      .findAll("#file-panel .entry")
      .find((e) => e.text().includes("README.md"));
    expect(row, "the root listing is on screen").toBeDefined();

    await row!.trigger("click");
    await settle();

    // Fullscreen: the mode switch and the file list give way to the preview.
    expect(wrapper.find(".modes").exists()).toBe(false);
    expect(wrapper.find("#file-panel").exists()).toBe(false);
    expect(wrapper.find("#panel-preview").exists()).toBe(true);
    // And it is the existing read-only text preview, reading the file through
    // the content endpoint for the same session — not just a tab label.
    // The first dynamic import compiles the SFC, which takes real time.
    await vi.waitFor(() => expect(readFileContent).toHaveBeenCalledTimes(1), {
      timeout: 5_000,
    });
    await settle();
    expect(readFileContent.mock.calls[0][0]).toBe(ID);
    expect(readFileContent.mock.calls[0][1]).toBe("README.md");
    expect(shown).toEqual(["# synthetic\n"]);
    expect(wrapper.get("#panel-preview").text()).toContain("唯讀");
  });

  it("手機與桌面寬度互換時保留同一個 session 的綁定，不重新載入", async () => {
    width = 390;
    const { listFileTree } = stubApi(async () => session());
    const wrapper = await render();
    await wrapper.findAll('.modes [role="tab"]')[1].trigger("click");
    await flushPromises();
    expect(listFileTree).toHaveBeenCalledTimes(1);

    resizeTo(1440);
    await flushPromises();
    // The desktop tree took over from the same binding and the same cache.
    expect(wrapper.find('[role="tree"]').exists()).toBe(true);
    expect(wrapper.find('[role="tree"]').text()).toContain("README.md");
    expect(useFilesStore().sessionId).toBe(ID);

    resizeTo(390);
    await flushPromises();
    expect(wrapper.find("#file-panel").exists()).toBe(true);
    expect(wrapper.get("#file-panel").text()).toContain("README.md");
    expect(listFileTree).toHaveBeenCalledTimes(1);
  });

  it("已結束的 session：手機檔案分頁說明原因，不發任何瀏覽請求", async () => {
    width = 390;
    const { listFileTree } = stubApi(async () =>
      session({ status: "terminated" }),
    );
    const wrapper = await render();
    await wrapper.findAll('.modes [role="tab"]')[1].trigger("click");
    await flushPromises();

    expect(wrapper.get("#file-panel").text()).toContain("Session 已結束");
    expect(listFileTree).not.toHaveBeenCalled();
    expect(useFilesStore().sessionId).toBeNull();
  });

  it("沒有 can_browse_files：手機檔案分頁說明權限，不發請求", async () => {
    width = 390;
    const base = session();
    const { listFileTree } = stubApi(async () => ({
      ...base,
      capabilities: { ...base.capabilities, can_browse_files: false },
    }));
    const wrapper = await render();
    await wrapper.findAll('.modes [role="tab"]')[1].trigger("click");
    await flushPromises();

    expect(wrapper.get("#file-panel").text()).toContain("沒有瀏覽");
    expect(listFileTree).not.toHaveBeenCalled();
  });
});

describe("SessionWorkspaceView — 檔案快取只屬於伺服器剛確認過的 session", () => {
  it("重新進入時伺服器回 403：清掉上次留下的列表，也不再發請求", async () => {
    // The previous visit left both behind: the session payload in the
    // sessions store and that session's listing in the files store.
    useSessionsStore().current = session();
    const files = useFilesStore();
    files.useSession(ID);
    files.dirs["."] = {
      path: ".",
      entries: [README],
      state: "success",
      truncated: false,
    };
    const { listFileTree } = stubApi(async () => {
      throw new ApiError("FORBIDDEN", "no", 403, "r");
    });
    const wrapper = await render();

    expect(wrapper.text()).toContain("無法存取此 Session");
    expect(files.sessionId).toBeNull();
    expect(files.dirs).toEqual({});
    expect(wrapper.text()).not.toContain("README.md");
    expect(listFileTree).not.toHaveBeenCalled();
  });

  it("桌面：新 session 的檔案樹照舊載入根目錄（回歸）", async () => {
    const { listFileTree } = stubApi(async () => session());
    const wrapper = await render();
    expect(listFileTree).toHaveBeenCalledTimes(1);
    expect(listFileTree.mock.calls[0][0]).toBe(ID);
    expect(wrapper.get('[role="tree"]').text()).toContain("README.md");
  });
});

// --- The session ends while a file is open (#76 review) ---------------------
//
// On a phone the preview is fullscreen and the file browser is *not mounted*
// under it, so nothing that lives in the browser can notice the session ending.
// The binding the view hands out has to drop on a terminal status, and the
// preview has to go with it: content off screen, Monaco disposed, no further
// read or listing, and the user back on the file panel being told why.

const OTHER = "66666666-6666-4666-8666-666666666666";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => (resolve = r));
  return { promise, resolve };
}

// Only what the helper touches, so the directly mounted view and the routed
// host both qualify.
interface Finder {
  findAll(selector: string): DOMWrapper<Element>[];
}

async function openReadmeOnPhone(wrapper: Finder) {
  await wrapper.findAll('.modes [role="tab"]')[1].trigger("click");
  await flushPromises();
  await wrapper
    .findAll("#file-panel .entry")
    .find((e) => e.text().includes("README.md"))!
    .trigger("click");
  await settle();
}

function expectEndedOnFilePanel(wrapper: Awaited<ReturnType<typeof render>>) {
  expect(wrapper.find("#panel-preview").exists()).toBe(false);
  // Back on the file panel, which is where the preview was opened from, and it
  // says why there is nothing to browse.
  expect(wrapper.find(".modes").exists()).toBe(true);
  expect(wrapper.get("#file-panel").text()).toContain("Session 已結束");
  expect(wrapper.findAll('[role="tab"]').map((t) => t.text())).not.toContain(
    "README.md",
  );
  const files = useFilesStore();
  expect(files.sessionId).toBeNull();
  expect(files.dirs).toEqual({});
}

describe("SessionWorkspaceView — session 在預覽開著時結束（#76）", () => {
  it("手機：終止後預覽關閉、模型釋放、回到檔案面板並說明，不再讀取或列目錄", async () => {
    width = 390;
    const { listFileTree, readFileContent } = stubApi(async () => session(), {
      terminateSession: vi.fn(async () => session({ status: "terminated" })),
    });
    const wrapper = await render();
    await openReadmeOnPhone(wrapper);
    await vi.waitFor(() => expect(shown).toEqual(["# synthetic\n"]), {
      timeout: 5_000,
    });
    expect(window.history.pushState).toHaveBeenCalledTimes(1);

    // The same state update the terminate confirmation makes.
    await useSessionsStore().terminate(ID);
    await settle();

    expectEndedOnFilePanel(wrapper);
    expect(models.every((m) => m.disposed)).toBe(true);
    expect(editors.every((e) => e.disposed)).toBe(true);
    // The one same-URL entry this view pushed is popped, once, and nothing
    // else: the route is still this session.
    expect(window.history.back).toHaveBeenCalledTimes(1);
    expect(wrapper.vm.$route.params.id).toBe(ID);

    // No stale restoration: moving between the modes brings nothing back and
    // asks the node for nothing.
    await wrapper.findAll('.modes [role="tab"]')[0].trigger("click");
    await flushPromises();
    await wrapper.findAll('.modes [role="tab"]')[1].trigger("click");
    await settle();
    expect(wrapper.find("#panel-preview").exists()).toBe(false);
    expect(readFileContent).toHaveBeenCalledTimes(1);
    expect(listFileTree).toHaveBeenCalledTimes(1);
  });

  it("手機：讀取進行中就終止，遲到的內容不會出現", async () => {
    width = 390;
    const pending = deferred<unknown>();
    const readFileContent = vi.fn(() => pending.promise);
    stubApi(async () => session(), {
      readFileContent,
      terminateSession: vi.fn(async () => session({ status: "terminated" })),
    });
    const wrapper = await render();
    await openReadmeOnPhone(wrapper);
    await vi.waitFor(() => expect(readFileContent).toHaveBeenCalledTimes(1), {
      timeout: 5_000,
    });

    await useSessionsStore().terminate(ID);
    await settle();
    // Resolves anyway: a transport that ignores the abort is the harder case.
    pending.resolve({
      success: true,
      rel_path: "README.md",
      encoding: "utf-8",
      content: "# late\n",
    });
    await settle();

    expectEndedOnFilePanel(wrapper);
    expect(shown).toEqual([]);
    expect(readFileContent).toHaveBeenCalledTimes(1);
  });

  it("手機：重新取得 session 回報已結束，同樣關閉預覽", async () => {
    width = 390;
    let status: SessionDetail["status"] = "running";
    const { readFileContent } = stubApi(async () => session({ status }));
    const wrapper = await render();
    await openReadmeOnPhone(wrapper);
    await vi.waitFor(() => expect(readFileContent).toHaveBeenCalledTimes(1), {
      timeout: 5_000,
    });

    status = "exited";
    await useSessionsStore().fetchSession(ID);
    await settle();

    expectEndedOnFilePanel(wrapper);
    expect(models.every((m) => m.disposed)).toBe(true);
    expect(window.history.back).toHaveBeenCalledTimes(1);
    expect(readFileContent).toHaveBeenCalledTimes(1);
  });

  it("桌面：終止後預覽分頁移除、回到 CLI、檔案樹說明原因，不動瀏覽歷史", async () => {
    const { listFileTree, readFileContent } = stubApi(async () => session(), {
      terminateSession: vi.fn(async () => session({ status: "terminated" })),
    });
    const wrapper = await render();
    await wrapper
      .get('[role="tree"]')
      .findAll('[role="treeitem"]')
      .find((row) => row.text().includes("README.md"))!
      .trigger("click");
    await vi.waitFor(() => expect(readFileContent).toHaveBeenCalledTimes(1), {
      timeout: 5_000,
    });
    await settle();
    expect(wrapper.findAll('[role="tab"]').map((t) => t.text())).toEqual([
      "CLI",
      "README.md",
    ]);

    await useSessionsStore().terminate(ID);
    await settle();

    expect(wrapper.find("#panel-preview").exists()).toBe(false);
    const tabs = wrapper.findAll('[role="tab"]');
    expect(tabs.map((t) => t.text())).toEqual(["CLI"]);
    expect(tabs[0].attributes("aria-selected")).toBe("true");
    expect(wrapper.get("#file-panel").text()).toContain("Session 已結束");
    expect(models.every((m) => m.disposed)).toBe(true);
    // Desktop never pushed an entry, so it must not pop one.
    expect(window.history.pushState).not.toHaveBeenCalled();
    expect(window.history.back).not.toHaveBeenCalled();
    expect(readFileContent).toHaveBeenCalledTimes(1);
    expect(listFileTree).toHaveBeenCalledTimes(1);
    expect(useFilesStore().sessionId).toBeNull();
  });

  it("手機：預覽開著時切到另一個 session，不回退瀏覽歷史，也不留下預覽", async () => {
    width = 390;
    const { readFileContent } = stubApi(async () => session());
    const wrapper = await render();
    await openReadmeOnPhone(wrapper);
    await vi.waitFor(() => expect(readFileContent).toHaveBeenCalledTimes(1), {
      timeout: 5_000,
    });

    // Navigation in progress: popping the preview's entry here would fight the
    // router, so it is disowned, not popped.
    (auth.api as unknown as ReturnType<typeof vi.fn>).mockReturnValue({
      ...(auth.api as unknown as () => Record<string, unknown>)(),
      getSession: vi.fn(async () => session({ id: OTHER })),
    });
    await wrapper.setProps({ id: OTHER });
    await settle();

    expect(window.history.back).not.toHaveBeenCalled();
    expect(wrapper.find("#panel-preview").exists()).toBe(false);
    expect(models.every((m) => m.disposed)).toBe(true);
    expect(readFileContent).toHaveBeenCalledTimes(1);
  });
});

// --- The terminal socket reports the end, and nothing refetches (#76 review) --
//
// `useTerminalSession` sets `exited` on `terminal.exited` / `session.stopped`.
// That is often the *only* news the page gets: no refetch follows, so
// `sessions.current` still says `running`. The binding has to drop on the
// socket's word alone, and take the preview with it.

async function exitFromTerminal(): Promise<void> {
  term.status.value = "exited";
  await settle();
}

describe("SessionWorkspaceView — 終端機回報 session 結束、沒有重新取得 session（#76）", () => {
  it("手機：預覽關閉、模型釋放、回到檔案面板並說明，同一個 route，不再讀取或列目錄", async () => {
    width = 390;
    const getSession = vi.fn(async () => session());
    const { listFileTree, readFileContent } = stubApi(getSession);
    const wrapper = await render();
    await openReadmeOnPhone(wrapper);
    await vi.waitFor(() => expect(shown).toEqual(["# synthetic\n"]), {
      timeout: 5_000,
    });
    expect(window.history.pushState).toHaveBeenCalledTimes(1);

    await exitFromTerminal();

    // The payload was never refetched and still says running.
    expect(getSession).toHaveBeenCalledTimes(1);
    expect(useSessionsStore().current?.status).toBe("running");
    expectEndedOnFilePanel(wrapper);
    expect(wrapper.text()).not.toContain("# synthetic");
    expect(models.every((m) => m.disposed)).toBe(true);
    expect(editors.every((e) => e.disposed)).toBe(true);
    // Exactly the one same-URL entry this view pushed, and the route is still
    // this session.
    expect(window.history.back).toHaveBeenCalledTimes(1);
    expect(wrapper.vm.$route.params.id).toBe(ID);

    // No stale restoration, no request.
    await wrapper.findAll('.modes [role="tab"]')[0].trigger("click");
    await flushPromises();
    await wrapper.findAll('.modes [role="tab"]')[1].trigger("click");
    await settle();
    expect(wrapper.find("#panel-preview").exists()).toBe(false);
    expect(wrapper.get("#file-panel").text()).not.toContain("README.md");
    expect(readFileContent).toHaveBeenCalledTimes(1);
    expect(listFileTree).toHaveBeenCalledTimes(1);
    // No retry is offered for something asking again cannot change.
    expect(wrapper.find('#file-panel [data-action="retry"]').exists()).toBe(
      false,
    );
  });

  it("手機：讀取進行中時終端機回報結束，遲到的內容不會出現", async () => {
    width = 390;
    const pending = deferred<unknown>();
    const readFileContent = vi.fn(() => pending.promise);
    const { listFileTree } = stubApi(async () => session(), {
      readFileContent,
    });
    const wrapper = await render();
    await openReadmeOnPhone(wrapper);
    await vi.waitFor(() => expect(readFileContent).toHaveBeenCalledTimes(1), {
      timeout: 5_000,
    });

    await exitFromTerminal();
    pending.resolve({
      success: true,
      rel_path: "README.md",
      encoding: "utf-8",
      content: "# late\n",
    });
    await settle();

    expectEndedOnFilePanel(wrapper);
    expect(shown).toEqual([]);
    expect(wrapper.text()).not.toContain("# late");
    expect(readFileContent).toHaveBeenCalledTimes(1);
    expect(listFileTree).toHaveBeenCalledTimes(1);
    expect(window.history.back).toHaveBeenCalledTimes(1);
    expect(wrapper.vm.$route.params.id).toBe(ID);
  });

  it("桌面：預覽分頁移除、回到 CLI、檔案樹說明原因，不動瀏覽歷史", async () => {
    const getSession = vi.fn(async () => session());
    const { listFileTree, readFileContent } = stubApi(getSession);
    const wrapper = await render();
    await wrapper
      .get('[role="tree"]')
      .findAll('[role="treeitem"]')
      .find((row) => row.text().includes("README.md"))!
      .trigger("click");
    await vi.waitFor(() => expect(readFileContent).toHaveBeenCalledTimes(1), {
      timeout: 5_000,
    });
    await settle();

    await exitFromTerminal();

    expect(getSession).toHaveBeenCalledTimes(1);
    expect(wrapper.find("#panel-preview").exists()).toBe(false);
    const tabs = wrapper.findAll('[role="tab"]');
    expect(tabs.map((t) => t.text())).toEqual(["CLI"]);
    expect(tabs[0].attributes("aria-selected")).toBe("true");
    expect(wrapper.get("#file-panel").text()).toContain("Session 已結束");
    expect(wrapper.get("#file-panel").text()).not.toContain("README.md");
    expect(models.every((m) => m.disposed)).toBe(true);
    expect(window.history.pushState).not.toHaveBeenCalled();
    expect(window.history.back).not.toHaveBeenCalled();
    expect(readFileContent).toHaveBeenCalledTimes(1);
    expect(listFileTree).toHaveBeenCalledTimes(1);
    expect(useFilesStore().sessionId).toBeNull();
  });
});

// --- Signed out by something other than this tab's Logout button (#76) -------
//
// Another tab signing out, or a refresh Central refuses, clears the tokens
// without any navigation in this tab — so the router guard never runs, and the
// workspace would go on showing the last user's listing and open file. These
// cases go through the real API client (only `fetch` is replaced), the real
// guard, the real storage sync and the app's own auth-loss handler, mounted
// behind a RouterView so leaving the route really unmounts the workspace.

const USER_A = {
  id: "user-a",
  username: "alice",
  display_name: "Alice",
  role: "Developer",
  permissions: [],
};
const USER_B = { ...USER_A, id: "user-b", username: "bob", display_name: "B" };

function fakeCentral() {
  const state = {
    expired: false,
    forbidden: false,
    // `/me`: who the current tokens belong to, and a gate to hold the answer.
    me: USER_A as typeof USER_A,
    meHeld: null as Promise<void> | null,
    // One 401 followed by a refresh Central accepts: an ordinary refresh.
    expireOnce: false,
  };
  const json = (body: unknown, status = 200) =>
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    });
  const fail = (code: string, status: number) =>
    json({ error: { code, message: "no" }, request_id: "r" }, status);
  const calls: string[] = [];
  const fetchMock = vi.fn(async (url: string) => {
    const path = new URL(url, "http://central.test").pathname;
    calls.push(path);
    if (path === "/api/auth/refresh") {
      return state.expired
        ? fail("TOKEN_INVALID", 401)
        : json({
            access_token: "a2-access",
            refresh_token: "a2-refresh",
            token_type: "bearer",
          });
    }
    if (state.expired) return fail("TOKEN_EXPIRED", 401);
    if (state.expireOnce) {
      state.expireOnce = false;
      return fail("TOKEN_EXPIRED", 401);
    }
    if (path === "/api/auth/me") {
      if (state.meHeld) await state.meHeld;
      return json(state.me);
    }
    if (path.endsWith("/attach")) return json({ ticket: "t" });
    if (path === `/api/sessions/${ID}`) {
      return state.forbidden ? fail("FORBIDDEN", 403) : json(session());
    }
    if (path.endsWith("/files/tree")) {
      return json({ path: ".", truncated: false, entries: [README] });
    }
    if (path.endsWith("/files/content")) {
      return json({
        success: true,
        rel_path: "README.md",
        size: 12,
        encoding: "utf-8",
        language_hint: "markdown",
        content: "# synthetic\n",
      });
    }
    return fail("NOT_FOUND", 404);
  });
  vi.stubGlobal("fetch", fetchMock);
  const fileCalls = () =>
    calls.filter((c) => c.includes("/files/") || c.startsWith("/api/sessions"))
      .length;
  const count = (fragment: string) =>
    calls.filter((c) => c.includes(fragment)).length;
  /** Hold `/me` until the returned function is called. */
  function holdMe(): () => void {
    let release!: () => void;
    state.meHeld = new Promise<void>((r) => (release = r));
    return () => {
      state.meHeld = null;
      release();
    };
  }
  return { state, fileCalls, count, holdMe };
}

const cleanups: Array<() => void> = [];

async function renderRouted(): Promise<{
  wrapper: ReturnType<typeof mount>;
  appRouter: Router;
}> {
  const appRouter = createRouter({
    history: createMemoryHistory(),
    routes: [
      {
        path: "/login",
        name: "login",
        component: { template: '<p class="login-page">login</p>' },
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
  // The real app root: the gate that makes a protected page inert lives there.
  const wrapper = mount(App, {
    attachTo: document.body,
    global: {
      plugins: [appRouter],
      stubs: { AppLayout: { template: "<div><slot /></div>" } },
    },
  });
  await settle();
  return { wrapper, appRouter };
}

function signIn(user: typeof USER_A, token: string): void {
  auth.useAuthStore().setTokens({
    access_token: `${token}-access`,
    refresh_token: `${token}-refresh`,
    token_type: "bearer",
  });
  auth.useAuthStore().user = user;
}

async function openReadmeOnDesktop(wrapper: ReturnType<typeof mount>) {
  await wrapper
    .get('[role="tree"]')
    .findAll('[role="treeitem"]')
    .find((row) => row.text().includes("README.md"))!
    .trigger("click");
  await settle();
}

function expectSignedOutAndWiped(
  wrapper: ReturnType<typeof mount>,
  appRouter: Router,
): void {
  const files = useFilesStore();
  expect(files.sessionId).toBeNull();
  expect(files.dirs).toEqual({});
  expect(useFavoritesStore().favorites).toEqual([]);
  expect(useSessionsStore().current).toBeNull();
  expect(auth.useAuthStore().isAuthenticated).toBe(false);
  // Left the protected view for the login page, remembering where it was.
  expect(appRouter.currentRoute.value.name).toBe("login");
  expect(appRouter.currentRoute.value.query.redirect).toBe(`/sessions/${ID}`);
  expect(wrapper.find(".login-page").exists()).toBe(true);
  // Nothing of the previous user's workspace is still mounted.
  expect(wrapper.find("#panel-preview").exists()).toBe(false);
  expect(wrapper.find("#file-panel").exists()).toBe(false);
  expect(wrapper.text()).not.toContain("# synthetic");
  expect(wrapper.text()).not.toContain("README.md");
  expect(models.every((m) => m.disposed)).toBe(true);
  expect(editors.every((e) => e.disposed)).toBe(true);
  // A navigation is in progress: the preview's same-URL entry is disowned,
  // not popped under it.
  expect(window.history.back).not.toHaveBeenCalled();
}

describe("SessionWorkspaceView — 在別處失去登入時清掉檔案與預覽（#76）", () => {
  beforeEach(() => {
    localStorage.clear();
    auth._resetApiClient();
    signIn(USER_A, "a");
    useFavoritesStore().favorites = [
      { id: "f1", node_id: "n", path: "/srv/private" } as never,
    ];
  });
  afterEach(() => {
    while (cleanups.length) cleanups.pop()!();
    vi.unstubAllGlobals();
    auth._resetApiClient();
    localStorage.clear();
  });

  it("手機：另一個分頁登出（storage 事件）→ 快取、收藏、預覽都清掉並回到登入；之後換人登入看不到舊快取", async () => {
    width = 390;
    const central = fakeCentral();
    cleanups.push(auth.installAuthStorageSync());
    const { wrapper, appRouter } = await renderRouted();
    await openReadmeOnPhone(wrapper);
    await vi.waitFor(() => expect(shown).toEqual(["# synthetic\n"]), {
      timeout: 5_000,
    });
    expect(useFilesStore().dirs["."]?.entries).toHaveLength(1);
    const before = central.fileCalls();

    // The other tab's logout: both keys removed, one event each.
    localStorage.removeItem("cliora.access_token");
    window.dispatchEvent(
      new StorageEvent("storage", { key: "cliora.access_token" }),
    );
    localStorage.removeItem("cliora.refresh_token");
    window.dispatchEvent(
      new StorageEvent("storage", { key: "cliora.refresh_token" }),
    );
    await settle();

    expectSignedOutAndWiped(wrapper, appRouter);
    expect(central.fileCalls()).toBe(before);

    // Someone else signs in in this tab and opens the same session id, which
    // the server refuses them. Nothing from the first user may be served.
    central.state.forbidden = true;
    signIn(USER_B, "b");
    await appRouter.push(`/sessions/${ID}`);
    await settle();
    expect(wrapper.text()).toContain("無法存取此 Session");
    expect(wrapper.text()).not.toContain("README.md");
    expect(useFilesStore().sessionId).toBeNull();
    expect(useFilesStore().dirs).toEqual({});
    // Only the refused session read; no listing or content was asked for.
    expect(central.fileCalls()).toBe(before + 1);
  });

  it("手機：token 更新被拒 → 快取、收藏、預覽都清掉並回到登入", async () => {
    width = 390;
    const central = fakeCentral();
    const { wrapper, appRouter } = await renderRouted();
    await openReadmeOnPhone(wrapper);
    await vi.waitFor(() => expect(shown).toEqual(["# synthetic\n"]), {
      timeout: 5_000,
    });
    const before = central.fileCalls();

    // Any request in this tab meets an expired token and Central refuses the
    // refresh; the client drops the tokens and nothing navigates.
    central.state.expired = true;
    await expect(auth.api().listNodes()).rejects.toMatchObject({
      status: 401,
    });
    await settle();

    expectSignedOutAndWiped(wrapper, appRouter);
    expect(localStorage.getItem("cliora.access_token")).toBeNull();
    expect(central.fileCalls()).toBe(before);
  });

  it("桌面：另一個分頁登出 → 預覽分頁與檔案樹一起清掉並回到登入", async () => {
    const central = fakeCentral();
    cleanups.push(auth.installAuthStorageSync());
    const { wrapper, appRouter } = await renderRouted();
    await openReadmeOnDesktop(wrapper);
    await vi.waitFor(() => expect(shown).toEqual(["# synthetic\n"]), {
      timeout: 5_000,
    });
    const before = central.fileCalls();

    localStorage.removeItem("cliora.access_token");
    localStorage.removeItem("cliora.refresh_token");
    window.dispatchEvent(new StorageEvent("storage", { key: null }));
    await settle();

    expectSignedOutAndWiped(wrapper, appRouter);
    expect(window.history.pushState).not.toHaveBeenCalled();
    expect(central.fileCalls()).toBe(before);
  });
});

// --- Another tab swaps the account before this one hears (#76 review 3) -----
//
// All this tab sees is one token pair replaced by another; whose it is waits on
// `/me`. Until then the page must be covered and inert, its file work stopped
// and its terminal unable to reconnect — without wiping, because `/me` may name
// the same user (another tab merely refreshed). Then: the same user gets the
// page back as it was; a different one never sees it.

function swapTokensFromAnotherTab(token: string): void {
  localStorage.setItem("cliora.access_token", `${token}-access`);
  window.dispatchEvent(
    new StorageEvent("storage", { key: "cliora.access_token" }),
  );
  localStorage.setItem("cliora.refresh_token", `${token}-refresh`);
  window.dispatchEvent(
    new StorageEvent("storage", { key: "cliora.refresh_token" }),
  );
}

function gate(wrapper: ReturnType<typeof mount>) {
  return wrapper.find('[role="alertdialog"]');
}

async function expectCoveredAndInert(
  wrapper: ReturnType<typeof mount>,
  reason: string,
): Promise<void> {
  expect(gate(wrapper).exists()).toBe(true);
  expect(gate(wrapper).attributes("data-reason")).toBe(reason);
  expect(gate(wrapper).attributes("aria-modal")).toBe("true");
  const routed = wrapper.get(".routed");
  expect(routed.attributes("inert")).toBeDefined();
  expect(routed.attributes("aria-hidden")).toBe("true");
  // The gate is not inside the inert part, and it has the focus.
  expect(routed.element.contains(gate(wrapper).element)).toBe(false);
  await vi.waitFor(() =>
    expect(gate(wrapper).element.contains(document.activeElement)).toBe(true),
  );
}

function expectUncovered(wrapper: ReturnType<typeof mount>): void {
  expect(gate(wrapper).exists()).toBe(false);
  const routed = wrapper.get(".routed");
  expect(routed.attributes("inert")).toBeUndefined();
  expect(routed.attributes("aria-hidden")).toBeUndefined();
}

describe("SessionWorkspaceView — 另一個分頁換了帳號、/me 尚未回答（#76）", () => {
  beforeEach(() => {
    localStorage.clear();
    auth._resetApiClient();
    signIn(USER_A, "a");
    useFavoritesStore().favorites = [
      { id: "f1", node_id: "n", path: "/srv/private" } as never,
    ];
  });
  afterEach(() => {
    while (cleanups.length) cleanups.pop()!();
    vi.unstubAllGlobals();
    auth._resetApiClient();
    localStorage.clear();
  });

  async function openAndSwap() {
    width = 390;
    const central = fakeCentral();
    cleanups.push(auth.installAuthStorageSync());
    const rendered = await renderRouted();
    await openReadmeOnPhone(rendered.wrapper);
    await vi.waitFor(() => expect(shown).toEqual(["# synthetic\n"]), {
      timeout: 5_000,
    });
    expectUncovered(rendered.wrapper);
    const before = central.fileCalls();
    const release = central.holdMe();
    swapTokensFromAnotherTab("b");
    await settle();
    return { ...rendered, central, before, release };
  }

  it("/me 未回：頁面被蓋住且 inert、焦點在對話框、不發檔案請求、終端機停住且拿不到 ticket", async () => {
    const { wrapper, central, before, release } = await openAndSwap();

    await expectCoveredAndInert(wrapper, "pending");
    expect(auth.useAuthStore().identityPending).toBe(true);
    // Not wiped yet — it may be the same user — but nothing new is asked for.
    expect(useFilesStore().dirs["."]?.entries).toHaveLength(1);
    expect(central.fileCalls()).toBe(before);
    // The terminal's socket is closed and no reconnect can get a ticket;
    // Central is not even asked.
    expect(term.disconnect).toHaveBeenCalled();
    await expect(term.getTicket!(ID)).rejects.toThrow();
    expect(central.count("/attach")).toBe(0);

    release();
    await settle();
  });

  it("/me 回答另一位使用者：快取、收藏清空，離開頁面，舊內容不會出現在新使用者面前", async () => {
    const { wrapper, appRouter, central, before, release } =
      await openAndSwap();

    central.state.me = USER_B;
    release();
    await settle();

    expect(useFilesStore().sessionId).toBeNull();
    expect(useFilesStore().dirs).toEqual({});
    expect(useFavoritesStore().favorites).toEqual([]);
    expect(useSessionsStore().current).toBeNull();
    expect(auth.useAuthStore().user?.id).toBe("user-b");
    expect(appRouter.currentRoute.value.name).toBe("dashboard");
    expect(wrapper.text()).toContain("dashboard");
    expect(wrapper.text()).not.toContain("README.md");
    expect(wrapper.text()).not.toContain("# synthetic");
    expect(wrapper.find("#panel-preview").exists()).toBe(false);
    expect(models.every((m) => m.disposed)).toBe(true);
    expectUncovered(wrapper);
    expect(central.fileCalls()).toBe(before);
  });

  it("/me 回答同一位使用者：原樣恢復，不清快取、不重新讀取，終端機重新連線", async () => {
    const { wrapper, appRouter, central, before, release } =
      await openAndSwap();
    await expectCoveredAndInert(wrapper, "pending");

    release();
    await settle();

    expectUncovered(wrapper);
    expect(auth.useAuthStore().identityPending).toBe(false);
    expect(appRouter.currentRoute.value.name).toBe("session-workspace");
    expect(useFilesStore().sessionId).toBe(ID);
    expect(useFilesStore().dirs["."]?.entries).toHaveLength(1);
    expect(useFavoritesStore().favorites).toHaveLength(1);
    // The preview is still the one that was open, with the same model.
    expect(wrapper.find("#panel-preview").exists()).toBe(true);
    expect(shown).toEqual(["# synthetic\n"]);
    expect(models.some((m) => !m.disposed)).toBe(true);
    expect(window.history.back).not.toHaveBeenCalled();
    expect(central.fileCalls()).toBe(before);
    // Reconnected, through a ticket that is minted again now.
    expect(term.retry).toHaveBeenCalled();
    await expect(term.getTicket!(ID)).resolves.toBe("t");
  });

  it("本分頁一般的 token 更新：不蓋頁面、不停終端機、不動快取", async () => {
    width = 390;
    const central = fakeCentral();
    cleanups.push(auth.installAuthStorageSync());
    const { wrapper } = await renderRouted();
    await openReadmeOnPhone(wrapper);
    await vi.waitFor(() => expect(shown).toEqual(["# synthetic\n"]), {
      timeout: 5_000,
    });
    term.disconnect.mockClear();

    central.state.expireOnce = true;
    await auth
      .api()
      .listNodes()
      .catch(() => {});
    await settle();

    expect(central.count("/api/auth/refresh")).toBe(1);
    expect(localStorage.getItem("cliora.access_token")).toBe("a2-access");
    expectUncovered(wrapper);
    expect(auth.useAuthStore().identityConfirmed).toBe(true);
    expect(term.disconnect).not.toHaveBeenCalled();
    expect(useFilesStore().dirs["."]?.entries).toHaveLength(1);
    expect(wrapper.find("#panel-preview").exists()).toBe(true);
  });
});
