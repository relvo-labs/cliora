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
