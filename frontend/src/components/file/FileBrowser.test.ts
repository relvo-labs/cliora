// The narrow-viewport file browser (plan/29 MS-14/MS-15).
//
// These cases are about two things the design documents are emphatic about and
// that a layout change is well placed to break:
//
//   * a truncated level must never look complete (ADR 0014/0015), and
//   * the search must not read as "search this folder" when it searches the
//     whole workspace — on a phone the box sits directly under a breadcrumb
//     saying `src`, and that layout answers the question for the user unless
//     something says otherwise.
//
// The daemon stays the path authority throughout. Nothing here asserts a path
// rule; it asserts that the UI passes the daemon's answers on intact.

import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { FileEntry } from "../../api/dto";
import * as auth from "../../stores/auth";
import { useFilesStore } from "../../stores/files";
import FileBrowser from "./FileBrowser.vue";

function entry(over: Partial<FileEntry> & { name: string }): FileEntry {
  return {
    rel_path: over.name,
    type: "file",
    size: 10,
    modified_at: "2026-09-14T00:00:00Z",
    hidden: false,
    symlink: false,
    excluded: false,
    expandable: false,
    ...over,
  } as FileEntry;
}

const ROOT = [
  entry({ name: "src", rel_path: "src", type: "directory", expandable: true }),
  entry({
    name: "node_modules",
    rel_path: "node_modules",
    type: "directory",
    expandable: false,
    excluded: true,
  }),
  entry({ name: "README.md", rel_path: "README.md" }),
];
const SRC = [entry({ name: "app.py", rel_path: "src/app.py" })];

function listing(path: string, truncated = false) {
  return {
    path,
    truncated,
    next_cursor: truncated ? "cursor-1" : undefined,
    entries: path === "src" ? SRC : path === "." ? ROOT : [],
  };
}

function render(props: Record<string, unknown> = {}) {
  return mount(FileBrowser, {
    props: {
      sessionId: "44444444-4444-4444-8444-444444444444",
      rootLabel: "api",
      canBrowse: true,
      ...props,
    },
  });
}

beforeEach(() => {
  setActivePinia(createPinia());
  vi.restoreAllMocks();
});

function stubApi(overrides: Record<string, unknown> = {}) {
  vi.spyOn(auth, "api").mockReturnValue({
    listFileTree: vi.fn(async (_id: string, params: { path: string }) =>
      listing(params.path),
    ),
    ...overrides,
  } as never);
  useFilesStore().useSession("44444444-4444-4444-8444-444444444444");
}

describe("FileBrowser — 逐層瀏覽", () => {
  it("一次顯示一層，點資料夾往下、上一層往回", async () => {
    stubApi();
    const wrapper = render();
    await flushPromises();

    expect(wrapper.text()).toContain("README.md");
    expect(wrapper.text()).not.toContain("app.py");

    await wrapper.findAll(".entry")[0].trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("app.py");
    expect(wrapper.text()).not.toContain("README.md");

    await wrapper.get(".entry.up").trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("README.md");
  });

  it("麵包屑是相對路徑，而且每一段都可以跳回去", async () => {
    stubApi();
    const wrapper = render();
    await flushPromises();
    await wrapper.findAll(".entry")[0].trigger("click");
    await flushPromises();

    const crumbs = wrapper.findAll(".crumb").map((c) => c.text());
    expect(crumbs).toEqual(["api", "src"]);
    // The root crumb is a folder name, never an absolute path (ADR 0014).
    expect(wrapper.text()).not.toContain("/srv");

    await wrapper.findAll(".crumb")[0].trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("README.md");
  });

  it("被排除的資料夾列得出來但點不進去", async () => {
    stubApi();
    const wrapper = render();
    await flushPromises();
    const excluded = wrapper.findAll(".entry")[1];
    expect(excluded.attributes("disabled")).toBeDefined();
    expect(excluded.text()).toContain("未納入");
  });

  it("開啟檔案交給呼叫端，不自己決定預覽", async () => {
    stubApi();
    const wrapper = render();
    await flushPromises();
    await wrapper.findAll(".entry")[2].trigger("click");
    expect(wrapper.emitted("open")?.[0]).toEqual(["README.md"]);
  });

  it("被截斷的一層說出來，並提供真的延續", async () => {
    const listFileTree = vi.fn(async (_id: string, params: { path: string }) =>
      listing(params.path, params.path === "."),
    );
    stubApi({ listFileTree });
    const wrapper = render();
    await flushPromises();

    expect(wrapper.text()).toContain("還沒載入完");
    await wrapper.get(".more button").trigger("click");
    await flushPromises();
    // A real continuation carries the daemon's opaque cursor back.
    expect(listFileTree.mock.calls.at(-1)?.[1]).toMatchObject({
      cursor: "cursor-1",
    });
  });

  it("空資料夾與無搜尋結果是兩句不同的話", async () => {
    stubApi({
      listFileTree: vi.fn(async (_id: string, params: { path: string }) => ({
        path: params.path,
        truncated: false,
        entries: [],
      })),
    });
    const wrapper = render();
    await flushPromises();
    expect(wrapper.text()).toContain("這個資料夾是空的");
    expect(wrapper.text()).not.toContain("沒有符合");
  });

  it("沒有瀏覽權限時只說明，不發請求", async () => {
    const listFileTree = vi.fn();
    stubApi({ listFileTree });
    const wrapper = render({ canBrowse: false, disabledReason: "沒有權限" });
    await flushPromises();
    expect(wrapper.text()).toContain("沒有權限");
    expect(listFileTree).not.toHaveBeenCalled();
  });

  it("換 session 時回到根目錄", async () => {
    stubApi();
    const wrapper = render();
    await flushPromises();
    await wrapper.findAll(".entry")[0].trigger("click");
    await flushPromises();
    expect(wrapper.findAll(".crumb")).toHaveLength(2);

    await wrapper.setProps({
      sessionId: "55555555-5555-4555-8555-555555555555",
    });
    await flushPromises();
    // A path from the previous session must not survive into the next one.
    expect(wrapper.findAll(".crumb")).toHaveLength(1);
  });
});

// --- #76: the mobile browser has to bind the store itself ------------------
//
// Every case above goes through `stubApi`, which binds the files store to the
// session *before* the component mounts. On a phone nothing does that: the
// desktop `useFileTree` is the one that calls `store.useSession`, and below
// 768px it is not mounted. So a fresh session opened on a phone showed the
// breadcrumb and an empty list — no request, no loading, no error — while
// every test here was green. The cases below start from a fresh Pinia and
// never pre-bind.

const A = "44444444-4444-4444-8444-444444444444";
const B = "55555555-5555-4555-8555-555555555555";
const A_ROOT = [entry({ name: "README.md", rel_path: "README.md" })];
const B_ROOT = [entry({ name: "b-only.txt", rel_path: "b-only.txt" })];

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => (resolve = r));
  return { promise, resolve };
}

function unboundApi(overrides: Record<string, unknown> = {}) {
  const listFileTree = vi.fn(async (id: string, params: { path: string }) => ({
    path: params.path,
    truncated: false,
    entries: id === B ? B_ROOT : A_ROOT,
  }));
  vi.spyOn(auth, "api").mockReturnValue({
    listFileTree,
    ...overrides,
  } as never);
  return listFileTree;
}

describe("FileBrowser — 沒有預先綁定的新 session（#76）", () => {
  it("session 從 null 變成可瀏覽時，以該 session 載入根目錄並顯示檔案", async () => {
    const listFileTree = unboundApi();
    // The workspace view mounts the panel before the session payload has
    // confirmed anything: no id, no capability.
    const wrapper = render({ sessionId: null, canBrowse: false });
    await flushPromises();
    expect(listFileTree).not.toHaveBeenCalled();

    await wrapper.setProps({ sessionId: A, canBrowse: true });
    await flushPromises();

    expect(listFileTree).toHaveBeenCalledTimes(1);
    expect(listFileTree.mock.calls[0][0]).toBe(A);
    expect(listFileTree.mock.calls[0][1]).toMatchObject({ path: "." });
    expect(wrapper.text()).toContain("README.md");
    expect(useFilesStore().sessionId).toBe(A);
  });

  it("一開始就帶著可瀏覽的 session 掛載，也會載入", async () => {
    const listFileTree = unboundApi();
    const wrapper = render({ sessionId: A });
    await flushPromises();
    expect(listFileTree).toHaveBeenCalledTimes(1);
    expect(wrapper.text()).toContain("README.md");
  });

  it("請求進行中顯示載入狀態，而不是一片空白", async () => {
    const pending = deferred<unknown>();
    unboundApi({ listFileTree: vi.fn(() => pending.promise) });
    const wrapper = render({ sessionId: A });
    await flushPromises();
    expect(wrapper.get('[aria-busy="true"]').attributes("aria-label")).toBe(
      "正在載入資料夾",
    );
  });

  it("session 已結束：說明原因、不發請求、也不給沒用的重試", async () => {
    const listFileTree = unboundApi();
    const wrapper = render({
      sessionId: A,
      canBrowse: true,
      disabledReason: "Session 已結束，檔案瀏覽不再可用。",
    });
    await flushPromises();
    expect(listFileTree).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain("Session 已結束");
    expect(wrapper.text()).not.toContain("重試");
    expect(useFilesStore().sessionId).toBeNull();
  });

  it("沒有瀏覽權限：不發請求，且不留下任何 session 綁定", async () => {
    const listFileTree = unboundApi();
    const wrapper = render({ sessionId: A, canBrowse: false });
    await flushPromises();
    expect(listFileTree).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain("沒有瀏覽這個工作區的權限");
    expect(useFilesStore().sessionId).toBeNull();
  });

  it("失去權限時清掉已載入的內容", async () => {
    unboundApi();
    const wrapper = render({ sessionId: A });
    await flushPromises();
    expect(wrapper.text()).toContain("README.md");

    await wrapper.setProps({ canBrowse: false });
    await flushPromises();
    expect(wrapper.text()).not.toContain("README.md");
    expect(useFilesStore().sessionId).toBeNull();
    expect(useFilesStore().dirs).toEqual({});
  });

  it("session 結束時清掉已載入的內容", async () => {
    unboundApi();
    const wrapper = render({ sessionId: A });
    await flushPromises();
    await wrapper.setProps({ disabledReason: "Session 已結束" });
    await flushPromises();
    expect(wrapper.text()).not.toContain("README.md");
    expect(useFilesStore().dirs).toEqual({});
  });

  it("換 session 後，前一個 session 遲到的回應不會落地", async () => {
    const late = deferred<unknown>();
    const listFileTree = vi.fn((id: string, params: { path: string }) =>
      id === A
        ? late.promise
        : Promise.resolve({
            path: params.path,
            truncated: false,
            entries: B_ROOT,
          }),
    );
    unboundApi({ listFileTree });
    const wrapper = render({ sessionId: A });
    await flushPromises();

    await wrapper.setProps({ sessionId: B });
    await flushPromises();
    // A's answer arrives after the switch. The abort already fired; a stub
    // that ignores the signal still resolves, which is the harder case.
    late.resolve({ path: ".", truncated: false, entries: A_ROOT });
    await flushPromises();

    expect(listFileTree.mock.calls.map((c) => c[0])).toEqual([A, B]);
    expect(wrapper.text()).toContain("b-only.txt");
    expect(wrapper.text()).not.toContain("README.md");
    expect(useFilesStore().sessionId).toBe(B);
  });

  it("快取屬於單一 session：切回原 session 會重新向它要資料", async () => {
    const listFileTree = unboundApi();
    const wrapper = render({ sessionId: A });
    await flushPromises();
    await wrapper.setProps({ sessionId: B });
    await flushPromises();
    expect(wrapper.text()).not.toContain("README.md");
    await wrapper.setProps({ sessionId: A });
    await flushPromises();

    expect(listFileTree.mock.calls.map((c) => c[0])).toEqual([A, B, A]);
    expect(wrapper.text()).toContain("README.md");
    expect(wrapper.text()).not.toContain("b-only.txt");
  });

  it("載入失敗時顯示錯誤並提供重試，重試成功後列出檔案", async () => {
    const { ApiError } = await import("../../api/client");
    const listFileTree = vi
      .fn()
      .mockRejectedValueOnce(new ApiError("RELAY_TIMEOUT", "逾時", 504, "r1"))
      .mockResolvedValue({ path: ".", truncated: false, entries: A_ROOT });
    unboundApi({ listFileTree });
    const wrapper = render({ sessionId: A });
    await flushPromises();

    expect(wrapper.find('[role="alert"]').text()).toContain("逾時");
    await wrapper.get('[data-action="retry"]').trigger("click");
    await flushPromises();

    expect(listFileTree).toHaveBeenCalledTimes(2);
    expect(listFileTree.mock.calls[1][0]).toBe(A);
    expect(wrapper.text()).toContain("README.md");
  });

  it("權限被伺服器拒絕（403）時說明，而且不給重試", async () => {
    const { ApiError } = await import("../../api/client");
    unboundApi({
      listFileTree: vi
        .fn()
        .mockRejectedValue(new ApiError("FORBIDDEN", "no", 403, "r1")),
    });
    const wrapper = render({ sessionId: A });
    await flushPromises();
    expect(wrapper.text()).toContain("You do not have permission");
    expect(wrapper.find('[data-action="retry"]').exists()).toBe(false);
  });

  it("卸載再掛載（切模式、跨寬度）保留同一個 session 的綁定與快取", async () => {
    const listFileTree = unboundApi();
    const first = render({ sessionId: A });
    await flushPromises();
    first.unmount();
    expect(useFilesStore().sessionId).toBe(A);

    const second = render({ sessionId: A });
    await flushPromises();
    // Served from the cache the first mount filled: same session, no refetch.
    expect(listFileTree).toHaveBeenCalledTimes(1);
    expect(second.text()).toContain("README.md");
  });
});

describe("FileBrowser — 搜尋範圍不能被誤讀", () => {
  it("永遠說明搜尋的是整個工作區的檔名", async () => {
    stubApi();
    const wrapper = render();
    await flushPromises();
    expect(wrapper.text()).toContain("整個工作區");
    expect(wrapper.text()).toContain("不含檔案內容");
  });

  it("送出搜尋時不帶 root，所以不會被限縮在目前資料夾", async () => {
    const searchFiles = vi.fn(async (_id: string, _params: unknown) => ({
      keyword: "guide",
      results: [],
      partial: false,
      scanned_count: 12,
    }));
    stubApi({ searchFiles });
    const wrapper = render();
    await flushPromises();
    // Walk into a folder first: this is the exact situation the wording exists
    // to correct.
    await wrapper.findAll(".entry")[0].trigger("click");
    await flushPromises();

    await wrapper.get('input[type="search"]').setValue("guide");
    await wrapper.get("form").trigger("submit");
    await flushPromises();

    expect(searchFiles).toHaveBeenCalled();
    // `root: undefined`, not `root: "src"`. The key is present because the
    // store always spreads it; what matters is that the current folder never
    // reaches it, which is what would quietly narrow the search.
    expect(
      (searchFiles.mock.calls[0][1] as { root?: string } | undefined)?.root,
    ).toBeUndefined();
  });

  for (const [reason, fragment] of [
    ["results", "結果上限"],
    ["depth", "深度上限"],
    ["scanned", "掃描檔案數上限"],
    ["timeout", "逾時"],
  ] as const) {
    it(`部分結果說得出 ${reason}，並附上已掃描數量`, async () => {
      stubApi({
        searchFiles: vi.fn(async () => ({
          keyword: "a",
          results: [
            {
              name: "a.md",
              rel_path: "docs/a.md",
              type: "file",
              size: 1,
              modified_at: "2026-09-14T00:00:00Z",
            },
          ],
          partial: true,
          stopped_reason: reason,
          scanned_count: 4321,
        })),
      });
      const wrapper = render();
      await flushPromises();
      await wrapper.get('input[type="search"]').setValue("a");
      await wrapper.get("form").trigger("submit");
      await flushPromises();

      expect(wrapper.text()).toContain(fragment);
      // The reason without a size is a sentence the user cannot act on.
      expect(wrapper.text()).toContain("4321");
    });
  }
});
