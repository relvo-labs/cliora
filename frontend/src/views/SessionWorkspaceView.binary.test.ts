// Coming back from a full-screen preview on a phone (plan/31/05 BP-06 §0, §5
// `focus_returns_to_row`; plan/29 MS-16).
//
// On a phone the file list is not mounted beside the preview — it gives way to
// it — so "coming back" is a fresh FileBrowser. What must survive is the
// user's place: the folder they were in, the search they ran, and the row they
// opened, which is where focus goes. The same harness as
// `SessionWorkspaceView.files.test.ts`: real file components, stubbed API,
// fresh Pinia, nothing pre-bound.

import { enableAutoUnmount, flushPromises, mount } from "@vue/test-utils";
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
    status: { value: "connected" } as { value: string },
    role: { value: "writer" },
    gap: { value: undefined },
    exit: { value: undefined },
    lastError: { value: undefined },
    canRetry: { value: false },
  },
}));
vi.mock("../composables/useTerminalSession", async () => {
  const { ref } = await import("vue");
  term.status = ref("connected");
  return { useTerminalSession: () => term };
});

vi.mock("../monaco/setup", () => {
  const monaco = {
    Uri: {
      from: (p: { path: string; query: string }) => `${p.query}${p.path}`,
    },
    editor: {
      create: () => {
        let model: unknown = null;
        return {
          getModel: () => model,
          setModel: (next: unknown) => (model = next),
          updateOptions: () => {},
          trigger: () => {},
          focus: () => {},
          dispose: () => {},
        };
      },
      createModel: (value: string) => ({
        getValue: () => value,
        setValue: () => {},
        dispose: () => {},
      }),
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
import { previewResponse } from "../testing/binaryPreviewResponse";
import SessionWorkspaceView from "./SessionWorkspaceView.vue";

const ID = "44444444-4444-4444-8444-444444444444";

function entry(name: string, relPath: string, type: "file" | "directory") {
  return {
    name,
    rel_path: relPath,
    type,
    size: 4,
    modified_at: "2026-09-27T00:00:00Z",
    hidden: false,
    symlink: false,
    excluded: false,
    expandable: type === "directory",
  } as FileEntry;
}

function session(): SessionDetail {
  return {
    id: ID,
    node_id: "11111111-1111-1111-1111-111111111111",
    user_id: "22222222-2222-2222-2222-222222222222",
    name: "s",
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
      can_preview_binary: true,
    },
  } as unknown as SessionDetail;
}

const LISTING: Record<string, FileEntry[]> = {
  ".": [
    entry("img", "img", "directory"),
    entry("README.md", "README.md", "file"),
  ],
  img: Array.from({ length: 30 }, (_, i) =>
    entry(`photo-${i}.png`, `img/photo-${i}.png`, "file"),
  ),
};

let width = 390;
function installMatchMedia(): void {
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    writable: true,
    value: (query: string) => {
      const min = /min-width:\s*(\d+)px/.exec(query);
      const max = /max-width:\s*(\d+)px/.exec(query);
      const matches =
        !(min && width < Number(min[1])) && !(max && width > Number(max[1]));
      return {
        matches,
        addEventListener: () => {},
        removeEventListener: () => {},
      };
    },
  });
}

let fetchBinaryPreview: ReturnType<typeof vi.fn>;
function stubApi(): void {
  fetchBinaryPreview = vi.fn(async () =>
    previewResponse({
      meta: { kind: "image", mime: "image/png", size: 4, width: 2, height: 1 },
      bytes: new Uint8Array(4),
    }),
  );
  vi.spyOn(auth, "api").mockReturnValue({
    getSession: vi.fn(async () => session()),
    getNode: vi.fn(async () => {
      throw new ApiError("NOT_FOUND", "no", 404, "r");
    }),
    attachSession: vi.fn(async () => ({ ticket: "t" })),
    terminateSession: vi.fn(async () => ({})),
    terminateSessionOnUnload: vi.fn(),
    listFileTree: vi.fn(async (_id: string, params: { path: string }) => ({
      path: params.path,
      truncated: false,
      entries: LISTING[params.path] ?? [],
    })),
    searchFiles: vi.fn(async () => ({
      results: [
        { name: "photo-7.png", rel_path: "img/photo-7.png", type: "file" },
      ],
      partial: false,
      scanned_count: 40,
    })),
    readFileContent: vi.fn(async (_id: string, relPath: string) => ({
      success: true,
      rel_path: relPath,
      size: 2,
      encoding: "utf-8",
      language_hint: "markdown",
      content: "#\n",
    })),
    fetchBinaryPreview,
  } as never);
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
    attachTo: document.body,
    global: {
      plugins: [router],
      stubs: { AppLayout: { template: "<div><slot /></div>" } },
    },
  });
  await flushPromises();
  return wrapper;
}

async function settle(): Promise<void> {
  for (let i = 0; i < 4; i += 1) {
    await flushPromises();
    await new Promise((r) => setTimeout(r, 0));
  }
}

enableAutoUnmount(afterEach);

beforeEach(() => {
  setActivePinia(createPinia());
  auth.useAuthStore().accessToken = "test-access";
  width = 390;
  installMatchMedia();
  vi.spyOn(window.history, "pushState").mockImplementation(() => {});
  vi.spyOn(window.history, "back").mockImplementation(() => {});
  vi.stubGlobal(
    "createImageBitmap",
    vi.fn(async () => ({ width: 2, height: 1, close: vi.fn() })),
  );
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(
    () => ({ drawImage: vi.fn(), clearRect: vi.fn() }) as never,
  );
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  Reflect.deleteProperty(window, "matchMedia");
});

describe("SessionWorkspaceView — focus_returns_to_row (phone)", () => {
  for (const how of ["back gesture", "tab close"] as const) {
    it(`${how}: back in the same folder, scrolled where it was, focus on the row that opened it`, async () => {
      stubApi();
      const wrapper = await render();
      await wrapper.findAll('.modes [role="tab"]')[1].trigger("click");
      await flushPromises();
      const folder = wrapper
        .findAll("#file-panel .entry")
        .find((e) => e.text().includes("img"));
      await folder!.trigger("click");
      await settle();

      // Either may be the scroller depending on layout; both come back.
      wrapper.get("#file-panel .browser").element.scrollTop = 240;
      wrapper.get("#file-panel").element.scrollTop = 120;
      const row = wrapper
        .findAll("#file-panel .entry")
        .find((e) => e.text().includes("photo-12.png"))!;
      (row.element as HTMLElement).focus();
      await row.trigger("click");
      await settle();
      await vi.waitFor(
        () => expect(fetchBinaryPreview).toHaveBeenCalledTimes(1),
        { timeout: 5_000 },
      );
      expect(wrapper.find("#file-panel").exists()).toBe(false);

      if (how === "back gesture") {
        window.dispatchEvent(new PopStateEvent("popstate"));
      } else {
        const close = wrapper.find('[role="tablist"] .close');
        await close.trigger("click");
      }
      await settle();

      expect(wrapper.find("#file-panel").exists()).toBe(true);
      expect(wrapper.get("#file-panel .crumbs").text()).toContain("img");
      expect(wrapper.get("#file-panel .browser").element.scrollTop).toBe(240);
      expect(wrapper.get("#file-panel").element.scrollTop).toBe(120);
      const active = document.activeElement as HTMLElement | null;
      expect(active?.textContent).toContain("photo-12.png");
    });
  }

  it("from a search result: the query and the results are still there, focus on the hit", async () => {
    stubApi();
    const wrapper = await render();
    await wrapper.findAll('.modes [role="tab"]')[1].trigger("click");
    await flushPromises();
    const input = wrapper.get('#file-panel input[name="file-keyword"]');
    await input.setValue("photo-7");
    await wrapper.get('#file-panel form[role="search"]').trigger("submit");
    await settle();
    const hit = wrapper.find("#file-panel .hit");
    expect(hit.exists()).toBe(true);
    await hit.trigger("click");
    await settle();
    await vi.waitFor(
      () => expect(fetchBinaryPreview).toHaveBeenCalledTimes(1),
      { timeout: 5_000 },
    );

    window.dispatchEvent(new PopStateEvent("popstate"));
    await settle();

    expect(
      (
        wrapper.get('#file-panel input[name="file-keyword"]')
          .element as HTMLInputElement
      ).value,
    ).toBe("photo-7");
    const active = document.activeElement as HTMLElement | null;
    expect(active?.classList.contains("hit")).toBe(true);
    expect(active?.textContent).toContain("img/photo-7.png");
  });

  it("a mode switch after coming back does not steal focus again", async () => {
    stubApi();
    const wrapper = await render();
    await wrapper.findAll('.modes [role="tab"]')[1].trigger("click");
    await flushPromises();
    const readme = wrapper
      .findAll("#file-panel .entry")
      .find((e) => e.text().includes("README.md"))!;
    await readme.trigger("click");
    await settle();
    window.dispatchEvent(new PopStateEvent("popstate"));
    await settle();

    const tabs = wrapper.findAll('.modes [role="tab"]');
    await tabs[0].trigger("click");
    await settle();
    (tabs[0].element as HTMLElement).focus();
    await tabs[1].trigger("click");
    await settle();
    expect(document.activeElement).toBe(tabs[0].element);
  });
});
