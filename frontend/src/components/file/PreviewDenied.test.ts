import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import PreviewDenied from "./PreviewDenied.vue";
import type { PreviewDenial } from "../../composables/useMonacoModel";

function render(
  denial: PreviewDenial,
  relPath = "config/app.conf",
  extra: { canDownload?: boolean; downloading?: boolean } = {},
) {
  return mount(PreviewDenied, { props: { denial, relPath, ...extra } });
}

describe("PreviewDenied", () => {
  it("explains an oversize file with its size and the cap", () => {
    const text = render({
      code: "FILE_TOO_LARGE",
      size: 5 * 1024 * 1024,
    }).text();
    expect(text).toContain("檔案過大");
    expect(text).toContain("5.00 MB");
    expect(text).toContain("2 MiB");
  });

  it("explains a binary file with mime and size but no content", () => {
    const text = render({
      code: "FILE_BINARY",
      mime: "application/octet-stream",
      size: 4096,
      modifiedAt: "2026-07-25T00:00:00Z",
    }).text();
    expect(text).toContain("不支援預覽");
    expect(text).toContain("application/octet-stream");
    expect(text).toContain("4.0 KB");
  });

  // WF-08: "we cannot decode this encoding" and "this is not text" arrive under
  // the same wire code but call for different actions, so the pane must not say
  // the same thing for both. Calling a Big5 source file binary is wrong, and it
  // was part of what users were reporting.
  it("says 'not UTF-8' rather than 'binary' for an undecodable text file", () => {
    const text = render(
      {
        code: "FILE_BINARY",
        reason: "unsupported_encoding",
        mime: "text/plain; charset=unknown",
        size: 2048,
      },
      "docs/legacy.txt",
    ).text();
    expect(text).toContain("無法以 UTF-8 顯示此檔案");
    expect(text).toContain("Big5");
    // And the next step differs: convert it, rather than give up.
    expect(text).toContain("iconv");
    expect(text).not.toContain("二進位");
  });

  it("still says 'binary' when the reason says binary", () => {
    const text = render({
      code: "FILE_BINARY",
      reason: "binary",
      mime: "application/octet-stream",
      size: 4096,
    }).text();
    expect(text).toContain("不支援預覽");
    expect(text).toContain("二進位");
    expect(text).not.toContain("iconv");
  });

  it("explains a sensitive denial by classification only", () => {
    const text = render(
      { code: "FILE_DENIED", reason: "dotenv" },
      "config/.env",
    ).text();
    expect(text).toContain("敏感類型");
    expect(text).toContain("環境變數檔");
    expect(text).toContain("內容完全未被讀取或傳輸");
  });

  it("names each sensitive classification distinctly", () => {
    for (const [reason, label] of [
      ["private_key", "私鑰檔"],
      ["keystore", "金鑰庫檔"],
      ["sensitive_dir", "敏感目錄"],
    ] as const) {
      expect(render({ code: "FILE_DENIED", reason }).text()).toContain(label);
    }
  });

  it("explains a permission denial", () => {
    expect(render({ code: "FILE_PERMISSION_DENIED" }).text()).toContain(
      "無讀取權限",
    );
  });

  it("suggests a refresh when the file is gone", () => {
    const text = render({ code: "FILE_NOT_FOUND" }).text();
    expect(text).toContain("已不存在或無法存取");
    expect(text).toContain("重新整理");
  });

  it("always states a next step and never shows an absolute path", () => {
    for (const code of [
      "FILE_TOO_LARGE",
      "FILE_BINARY",
      "FILE_DENIED",
      "FILE_PERMISSION_DENIED",
      "FILE_NOT_FOUND",
    ]) {
      const text = render({ code }, "src/app/main.py").text();
      expect(text).toContain("下一步");
      expect(text).not.toContain("/home/");
      expect(text).not.toMatch(/(^|\s)\/(etc|var|root)\//);
    }
  });

  it("emits refresh so the user can re-check a changed file", async () => {
    const wrapper = render({ code: "FILE_NOT_FOUND" });
    await wrapper.get("button").trigger("click");
    expect(wrapper.emitted("refresh")).toHaveLength(1);
  });
});

// Download (FD-06, ADR 0028). This pane is where the two ceilings become visible
// to a user, and where the platform has to be careful not to offer a button that
// reproduces the refusal it is standing next to.
describe("PreviewDenied download offer", () => {
  const binary: PreviewDenial = {
    code: "FILE_BINARY",
    mime: "application/octet-stream",
    size: 4096,
    modifiedAt: "2026-07-25T00:00:00Z",
  };

  it("offers a download for a binary file, which is the case it exists for", () => {
    const wrapper = render(binary, "assets/logo.png", { canDownload: true });
    const button = wrapper
      .findAll("button")
      .find((b) => b.text().includes("下載檔案"));
    expect(button).toBeDefined();
    button!.trigger("click");
    expect(wrapper.emitted("download")).toHaveLength(1);
  });

  it("offers nothing when the node does not hand files back", () => {
    const wrapper = render(binary, "assets/logo.png", { canDownload: false });
    expect(wrapper.text()).not.toContain("下載檔案");
  });

  it("offers a download for a file between the preview cap and the download cap", () => {
    // 3 MiB: unshowable at 2 MiB, obtainable at 4 MiB. Telling this user to go
    // and use a terminal would simply be wrong.
    const wrapper = render(
      { code: "FILE_TOO_LARGE", size: 3 * 1024 * 1024 },
      "data/big.csv",
      { canDownload: true },
    );
    expect(wrapper.text()).toContain("下載上限");
    expect(wrapper.text()).toContain("下載檔案");
  });

  it("withdraws the offer above the download cap rather than letting the button teach the limit", () => {
    const wrapper = render(
      { code: "FILE_TOO_LARGE", size: 9 * 1024 * 1024 },
      "data/huge.csv",
      { canDownload: true },
    );
    expect(wrapper.text()).toContain("終端機");
    expect(wrapper.text()).not.toContain("下載檔案");
  });

  it("never offers a download for a sensitive file, because the node refuses it too", () => {
    const wrapper = render({ code: "FILE_DENIED", reason: "dotenv" }, ".env", {
      canDownload: true,
    });
    expect(wrapper.text()).not.toContain("下載檔案");
    // And it says so, rather than leaving the user to discover it by trying.
    expect(wrapper.text()).toContain("下載同樣被拒");
  });
});
