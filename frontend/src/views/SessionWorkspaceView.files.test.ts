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

import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createRouter, createWebHistory } from "vue-router";

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
    status: { value: "connected" },
    role: { value: "writer" },
    gap: { value: undefined },
    exit: { value: undefined },
    lastError: { value: undefined },
    canRetry: { value: false },
  },
}));
vi.mock("../composables/useTerminalSession", () => ({
  useTerminalSession: () => term,
}));

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

import * as auth from "../stores/auth";
import { useFilesStore } from "../stores/files";
import { useSessionsStore } from "../stores/sessions";
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

beforeEach(() => {
  setActivePinia(createPinia());
  listeners.clear();
  width = 1440;
  installMatchMedia();
  shown.length = 0;
  models.length = 0;
  editors.length = 0;
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

async function openReadmeOnPhone(wrapper: Awaited<ReturnType<typeof render>>) {
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
