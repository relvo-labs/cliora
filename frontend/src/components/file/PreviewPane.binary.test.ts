// PreviewPane's routing branch for images (plan/31/05 BP-06 §1, §4, §5).
//
// The Monaco path is replaced by the same minimal fake the workspace tests
// use; what is asserted here is *which* path a file takes and what the binary
// path leaves in the DOM. Fresh Pinia, and the session payload is placed where
// the view places it (`sessions.current`) rather than handed to the pane.

import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { nextTick } from "vue";

import { ApiError } from "../../api/client";
import type { BinaryPreviewPayload, SessionDetail } from "../../api/dto";

const { shown } = vi.hoisted(() => ({ shown: [] as string[] }));
vi.mock("../../monaco/setup", () => {
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
      createModel: (value: string) => {
        shown.push(value);
        return { getValue: () => value, setValue: () => {}, dispose: () => {} };
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
  };
});

import * as auth from "../../stores/auth";
import { previewResponse } from "../../testing/binaryPreviewResponse";
import { useSessionsStore } from "../../stores/sessions";
import PreviewPane from "./PreviewPane.vue";

const SID = "44444444-4444-4444-8444-444444444444";

function setCapability(canPreviewBinary: boolean | undefined): void {
  useSessionsStore().current = {
    id: SID,
    status: "running",
    capabilities: {
      can_view: true,
      can_write: true,
      can_takeover: false,
      can_terminate: false,
      can_browse_files: true,
      can_upload_files: false,
      can_open_shell: false,
      ...(canPreviewBinary === undefined
        ? {}
        : { can_preview_binary: canPreviewBinary }),
    },
  } as unknown as SessionDetail;
}

function image(over: Partial<BinaryPreviewPayload["meta"]> = {}) {
  return {
    meta: {
      kind: "image" as const,
      mime: "image/png" as const,
      size: 4,
      width: 20,
      height: 10,
      ...over,
    },
    bytes: new Uint8Array([1, 2, 3, 4]),
  };
}

let fetchBinaryPreview: ReturnType<typeof vi.fn>;
let readFileContent: ReturnType<typeof vi.fn>;
function stubApi(
  binary: () => Promise<BinaryPreviewPayload> = async () => image(),
): void {
  fetchBinaryPreview = vi.fn(async () => previewResponse(await binary()));
  readFileContent = vi.fn(async (_id: string, relPath: string) =>
    /\.(png|gif)$/.test(relPath)
      ? {
          success: false,
          rel_path: relPath,
          size: 4,
          mime: "image/png",
          error: { code: "FILE_BINARY", reason: "binary" },
        }
      : {
          success: true,
          rel_path: relPath,
          size: 5,
          encoding: "utf-8",
          language_hint: "typescript",
          content: "text\n",
        },
  );
  vi.spyOn(auth, "api").mockReturnValue({
    fetchBinaryPreview,
    readFileContent,
  } as never);
}

const drawImage = vi.fn();
const createImageBitmapMock = vi.fn(async () => ({
  width: 20,
  height: 10,
  close: vi.fn(),
}));

async function settle(): Promise<void> {
  for (let i = 0; i < 4; i += 1) {
    await flushPromises();
    await nextTick();
  }
}

let wrapper: VueWrapper | undefined;
async function render(relPath: string, props: Record<string, unknown> = {}) {
  wrapper = mount(PreviewPane, {
    props: { sessionId: SID, relPath, ...props },
    attachTo: document.body,
  });
  await settle();
  return wrapper;
}

beforeEach(() => {
  setActivePinia(createPinia());
  shown.length = 0;
  drawImage.mockClear();
  createImageBitmapMock.mockClear();
  vi.stubGlobal("createImageBitmap", createImageBitmapMock);
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(
    () =>
      ({
        drawImage,
        clearRect: vi.fn(),
        imageSmoothingEnabled: true,
        imageSmoothingQuality: "high",
      }) as never,
  );
});
afterEach(() => {
  wrapper?.unmount();
  wrapper = undefined;
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("PreviewPane — routes_by_capability_then_hint", () => {
  it("capability true + image extension → binary preview, not the text read", async () => {
    setCapability(true);
    stubApi();
    await render("img/photo.PNG");
    expect(fetchBinaryPreview).toHaveBeenCalledTimes(1);
    expect(fetchBinaryPreview.mock.calls[0][0]).toBe(SID);
    expect(fetchBinaryPreview.mock.calls[0][1]).toBe("img/photo.PNG");
    expect(readFileContent).not.toHaveBeenCalled();
  });

  it("capability true + no hint → the existing text path", async () => {
    setCapability(true);
    stubApi();
    await render("src/app.ts");
    expect(fetchBinaryPreview).not.toHaveBeenCalled();
    expect(readFileContent).toHaveBeenCalledTimes(1);
    expect(shown).toEqual(["text\n"]);
  });

  it("capability false (or absent: an old Central) + image → text path and the unchanged FILE_BINARY pane", async () => {
    for (const cap of [false, undefined]) {
      setActivePinia(createPinia());
      setCapability(cap);
      stubApi();
      const w = await render("img/photo.png");
      expect(fetchBinaryPreview).not.toHaveBeenCalled();
      expect(readFileContent).toHaveBeenCalledTimes(1);
      expect(w.text()).toContain("不支援預覽此檔案");
      w.unmount();
      wrapper = undefined;
    }
  });
});

describe("PreviewPane — capability_drop_clears", () => {
  it("true → false while an image is shown: disposed, then the existing FILE_BINARY pane", async () => {
    setCapability(true);
    const bitmap = { width: 20, height: 10, close: vi.fn() };
    createImageBitmapMock.mockResolvedValueOnce(bitmap);
    stubApi();
    const w = await render("img/photo.png");
    expect(w.find("canvas").exists()).toBe(true);

    useSessionsStore().current!.capabilities.can_preview_binary = false;
    await settle();

    expect(bitmap.close).toHaveBeenCalledTimes(1);
    expect(w.find("canvas").exists()).toBe(false);
    expect(readFileContent).toHaveBeenCalledTimes(1);
    expect(w.text()).toContain("不支援預覽此檔案");
  });
});

describe("PreviewPane — no_object_url_no_img", () => {
  it("a full image flow: canvas only, no object URL, nothing that saves", async () => {
    const createObjectURL = vi.fn();
    Object.defineProperty(URL, "createObjectURL", {
      value: createObjectURL,
      configurable: true,
      writable: true,
    });
    try {
      setCapability(true);
      stubApi();
      const w = await render("img/photo.png", { canDownload: true });
      const canvas = w.find("canvas");
      expect(canvas.exists()).toBe(true);
      expect(canvas.attributes("role")).toBe("img");
      expect(canvas.attributes("aria-label")).toBe("photo.png，20×10 像素");
      expect(drawImage).toHaveBeenCalled();
      expect(createObjectURL).not.toHaveBeenCalled();
      for (const selector of [
        "img",
        "a[download]",
        "iframe",
        "object",
        "embed",
      ]) {
        expect(w.find(selector).exists(), selector).toBe(false);
      }
      // No download control of any kind on the binary route, including the
      // header one #71 offers for text files.
      expect(w.text()).not.toContain("下載");
    } finally {
      Reflect.deleteProperty(URL, "createObjectURL");
    }
  });

  for (const [name, error] of [
    [
      "limit",
      new ApiError("FILE_PREVIEW_LIMIT", "x", 413, "r", { reason: "pixels" }),
    ],
    [
      "invalid",
      new ApiError("FILE_PREVIEW_INVALID", "x", 422, "r", {
        reason: "malformed",
      }),
    ],
  ] as const) {
    it(`${name}: no download, no blob URL`, async () => {
      setCapability(true);
      stubApi(async () => {
        throw error;
      });
      const w = await render("img/photo.png", { canDownload: true });
      expect(w.find("a[download]").exists()).toBe(false);
      expect(w.text()).not.toContain("下載");
      expect(w.text()).not.toContain("另存");
    });
  }

  it("render_failed: no download", async () => {
    setCapability(true);
    createImageBitmapMock.mockRejectedValueOnce(new Error("decode"));
    stubApi();
    const w = await render("img/photo.png", { canDownload: true });
    expect(w.text()).toContain("此瀏覽器無法顯示這個檔案");
    expect(w.text()).not.toContain("下載");
  });
});

describe("PreviewPane — the binary states the user acts on", () => {
  it("GIF says only the first frame is shown", async () => {
    setCapability(true);
    stubApi(async () => image({ mime: "image/gif" }));
    const w = await render("img/anim.gif");
    expect(w.text()).toContain("動畫僅顯示第一幀");
  });

  it("unsupported offers the text preview, which reads the existing path", async () => {
    setCapability(true);
    stubApi(async () => {
      throw new ApiError("FILE_PREVIEW_UNSUPPORTED", "x", 415, "r", {
        reason: "unsupported_type",
      });
    });
    const w = await render("notes.png");
    const button = w
      .findAll("button")
      .find((b) => b.text().includes("改用文字預覽"));
    expect(button).toBeDefined();
    await button!.trigger("click");
    await settle();
    expect(readFileContent).toHaveBeenCalledTimes(1);
  });

  it("the node reconnected without the capability: falls back to the text path", async () => {
    setCapability(true);
    stubApi(async () => {
      throw new ApiError("FILE_PREVIEW_UNSUPPORTED_NODE", "x", 409, "r");
    });
    const w = await render("img/photo.png");
    expect(readFileContent).toHaveBeenCalledTimes(1);
    expect(w.text()).toContain("不支援預覽此檔案");
  });

  it("loading shows progress and a cancel that closes the preview", async () => {
    setCapability(true);
    stubApi(() => new Promise(() => {}));
    const w = await render("img/photo.png");
    expect(w.text()).toContain("正在載入預覽");
    const cancel = w.findAll("button").find((b) => b.text() === "取消");
    expect(cancel).toBeDefined();
    await cancel!.trigger("click");
    expect(w.emitted("close")).toHaveLength(1);
  });
});
