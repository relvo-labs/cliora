import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import PreviewDenied from "./PreviewDenied.vue";
import type { PreviewDenial } from "../../composables/useMonacoModel";

function render(denial: PreviewDenial, relPath = "config/app.conf") {
  return mount(PreviewDenied, { props: { denial, relPath } });
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
