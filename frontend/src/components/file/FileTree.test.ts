import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { nextTick } from "vue";

import type { FileEntry, FileTreePage } from "../../api/dto";

// Fake Central for the tree panel: a small fixture workspace.
const { listImpl } = vi.hoisted(() => ({
  listImpl: {
    fn: null as null | ((path: string) => Promise<FileTreePage>),
  },
}));

vi.mock("../../stores/auth", () => ({
  api: () => ({
    listFileTree: (_sessionId: string, params: { path?: string }) =>
      listImpl.fn!(params.path ?? "."),
    searchFiles: async () => ({
      results: [],
      partial: false,
      scanned_count: 0,
    }),
  }),
}));

import FileTree from "./FileTree.vue";

function entry(
  over: Partial<FileEntry> & { name: string; rel_path: string },
): FileEntry {
  return {
    type: "file",
    size: 1,
    modified_at: "2026-07-25T00:00:00Z",
    hidden: false,
    symlink: false,
    excluded: false,
    expandable: false,
    ...over,
  };
}

const settle = async (): Promise<void> => {
  for (let i = 0; i < 6; i += 1) {
    await Promise.resolve();
    await nextTick();
  }
};

function render(props: Partial<InstanceType<typeof FileTree>["$props"]> = {}) {
  return mount(FileTree, {
    attachTo: document.body,
    props: {
      sessionId: "s1",
      rootLabel: "app",
      canBrowse: true,
      ...props,
    },
  });
}

describe("FileTree", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    listImpl.fn = async (path) => {
      if (path === ".") {
        return {
          path: ".",
          truncated: false,
          entries: [
            entry({
              name: "src",
              rel_path: "src",
              type: "directory",
              expandable: true,
            }),
            entry({
              name: "node_modules",
              rel_path: "node_modules",
              type: "directory",
              excluded: true,
              expandable: false,
            }),
            entry({ name: "README.md", rel_path: "README.md" }),
          ],
        };
      }
      if (path === "src") {
        return {
          path: "src",
          truncated: false,
          entries: [
            entry({ name: "app.ts", rel_path: "src/app.ts" }),
            entry({ name: "main.py", rel_path: "src/main.py" }),
          ],
        };
      }
      return { path, truncated: false, entries: [] };
    };
  });

  it("renders the workspace root and its level as tree items", async () => {
    const wrapper = render();
    await settle();
    const items = wrapper.findAll('[role="treeitem"]');
    expect(items.map((i) => i.attributes("data-key"))).toEqual([
      ".",
      "src",
      "node_modules",
      "README.md",
    ]);
    // The container is the single tab stop; the focused row is advertised via
    // aria-activedescendant, so no row carries a tabindex.
    const tree = wrapper.find('[role="tree"]');
    expect(tree.attributes("tabindex")).toBe("0");
    expect(tree.attributes("aria-activedescendant")).toBe(
      items[0].attributes("id"),
    );
    expect(items.some((i) => i.attributes("tabindex") !== undefined)).toBe(
      false,
    );
  });

  it("labels an excluded directory and leaves it non-expandable", async () => {
    const wrapper = render();
    await settle();
    const excluded = wrapper.find('[data-key="node_modules"]');
    expect(excluded.text()).toContain("已排除");
    expect(excluded.attributes("aria-expanded")).toBeUndefined();
  });

  // The composable's keyboard logic is unit-tested directly; this proves the
  // handler is actually wired to the tree element in the rendered component.
  it("handles arrow keys through the tree's keydown binding", async () => {
    const wrapper = render();
    await settle();
    const tree = wrapper.find('[role="tree"]');

    await tree.trigger("keydown", { key: "ArrowDown" });
    await settle();
    expect(tree.attributes("aria-activedescendant")).toBe(
      wrapper.find('[data-key="src"]').attributes("id"),
    );

    await tree.trigger("keydown", { key: "ArrowRight" });
    await settle();
    expect(wrapper.find('[data-key="src"]').attributes("aria-expanded")).toBe(
      "true",
    );
    expect(wrapper.find('[data-key="src/main.py"]').exists()).toBe(true);

    // Focus moves over the file without opening it.
    await tree.trigger("keydown", { key: "ArrowDown" });
    await settle();
    expect(wrapper.emitted("open")).toBeUndefined();

    // Enter is what opens it.
    await tree.trigger("keydown", { key: "End" });
    await settle();
    await tree.trigger("keydown", { key: "Enter" });
    await settle();
    expect(wrapper.emitted("open")?.[0]?.[0]).toBe("README.md");
  });

  it("shows the RBAC affordance and fetches nothing without file.browse", async () => {
    const calls: string[] = [];
    const original = listImpl.fn!;
    listImpl.fn = async (path) => {
      calls.push(path);
      return original(path);
    };
    const wrapper = render({ canBrowse: false });
    await settle();
    expect(wrapper.text()).toContain("file.browse");
    expect(wrapper.find('[role="tree"]').exists()).toBe(false);
    expect(calls).toEqual([]);
  });

  it("shows the session-ended affordance instead of the tree", async () => {
    const wrapper = render({
      disabledReason: "Session 已結束，檔案瀏覽不再可用。",
    });
    await settle();
    expect(wrapper.text()).toContain("Session 已結束");
    expect(wrapper.find('[role="tree"]').exists()).toBe(false);
  });
});

// --- Drag and drop (FU-06, ADR 0026) --------------------------------------
//
// The composable's target resolution is unit-tested through useFileTree; these
// prove the handlers are wired to the rendered rows, that the destination shown is
// the resolved one, and that nothing is offered when the gate is closed.

function dropEvent(items: Array<{ isFile: boolean; file: File | null }>) {
  return {
    dataTransfer: {
      items: items.map((i) => ({
        kind: "file",
        type: "text/plain",
        webkitGetAsEntry: () => ({ isFile: i.isFile }),
        getAsFile: () => i.file,
      })),
      dropEffect: "",
    },
  };
}

describe("FileTree drag and drop", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    listImpl.fn = async (path) => {
      if (path === ".") {
        return {
          path: ".",
          truncated: false,
          entries: [
            entry({
              name: "src",
              rel_path: "src",
              type: "directory",
              expandable: true,
            }),
            entry({
              name: "node_modules",
              rel_path: "node_modules",
              type: "directory",
              excluded: true,
              expandable: false,
            }),
            entry({ name: "README.md", rel_path: "README.md" }),
          ],
        };
      }
      return { path, truncated: false, entries: [] };
    };
  });

  it("highlights a directory row and names it as the destination", async () => {
    const wrapper = render({ canUpload: true });
    await settle();
    await wrapper.find('[data-key="src"]').trigger("dragenter");
    await nextTick();
    const row = wrapper.find('[data-key="src"]');
    expect(row.attributes("data-drop-target")).toBeDefined();
    expect(row.text()).toContain("放到 src/");
  });

  it("resolves a file row to its parent directory, and says so", async () => {
    // Requiring a precise hit on a folder row would make the feature tedious, so a
    // file row means "next to this file" — and the label has to name the folder or
    // the user is guessing.
    const wrapper = render({ canUpload: true });
    await settle();
    await wrapper.find('[data-key="README.md"]').trigger("dragenter");
    await nextTick();
    const row = wrapper.find('[data-key="README.md"]');
    expect(row.attributes("data-drop-target")).toBeDefined();
    expect(row.text()).toContain("放到 app/");
  });

  it("does not offer an excluded directory as a destination", async () => {
    const wrapper = render({ canUpload: true });
    await settle();
    await wrapper.find('[data-key="node_modules"]').trigger("dragenter");
    await nextTick();
    expect(
      wrapper.find('[data-key="node_modules"]').attributes("data-drop-target"),
    ).toBeUndefined();
  });

  it("emits the files and the resolved directory on drop", async () => {
    const wrapper = render({ canUpload: true });
    await settle();
    const file = new File([new Uint8Array(4)], "data.csv");
    await wrapper
      .find('[data-key="README.md"]')
      .trigger("drop", dropEvent([{ isFile: true, file }]));
    const emitted = wrapper.emitted("upload");
    expect(emitted).toHaveLength(1);
    expect(emitted![0][0]).toEqual([file]);
    // The parent of README.md is the workspace root.
    expect(emitted![0][1]).toBe(".");
  });

  it("refuses a folder without emitting an upload", async () => {
    const wrapper = render({ canUpload: true });
    await settle();
    await wrapper
      .find('[data-key="src"]')
      .trigger("drop", dropEvent([{ isFile: false, file: null }]));
    expect(wrapper.emitted("upload")).toBeUndefined();
    const refused = wrapper.emitted("uploadRefused");
    expect(refused).toHaveLength(1);
    expect(String(refused![0][0])).toContain("資料夾");
  });

  it("offers nothing at all when the gate is closed", async () => {
    // Hidden rather than disabled: a drop target that refuses on release is worse
    // than one that was never offered (ADR 0026 §9 — the node's own answer).
    const wrapper = render({ canUpload: false });
    await settle();
    await wrapper.find('[data-key="src"]').trigger("dragenter");
    await nextTick();
    expect(
      wrapper.find('[data-key="src"]').attributes("data-drop-target"),
    ).toBeUndefined();
    await wrapper
      .find('[data-key="src"]')
      .trigger(
        "drop",
        dropEvent([{ isFile: true, file: new File([], "a.txt") }]),
      );
    expect(wrapper.emitted("upload")).toBeUndefined();
    // And the picker is not rendered either.
    expect(wrapper.find('input[type="file"]').exists()).toBe(false);
  });

  it("emits the focused directory when the picker is used", async () => {
    // Drag and drop does not exist for keyboard or touch users, so this entry point
    // is not optional.
    const wrapper = render({ canUpload: true });
    await settle();
    const input = wrapper.find('input[type="file"]');
    expect(input.exists()).toBe(true);
    const file = new File([new Uint8Array(2)], "notes.md");
    Object.defineProperty(input.element, "files", { value: [file] });
    await input.trigger("change");
    const emitted = wrapper.emitted("upload");
    expect(emitted).toHaveLength(1);
    expect(emitted![0][0]).toEqual([file]);
    expect(emitted![0][1]).toBe(".");
  });
});
