// The binary-preview branch of the denial pane (plan/31/05 BP-06 §4).
//
// `states_are_distinct`: every state a user can land in says something
// different, because each has a different next step, and none of them offers
// to hand the file over instead (ADR 0029 §16, T16).

import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import type {
  BinaryDenialState,
  BinaryPreviewDetail,
} from "../../composables/useBinaryPreview";
import PreviewDenied from "./PreviewDenied.vue";

const STATES: Array<[BinaryDenialState, BinaryPreviewDetail]> = [
  ["cancelled", {}],
  ["denied_sensitive", { reason: "dotenv" }],
  ["denied_access", { reason: "outside_root" }],
  ["permission", {}],
  ["too_large", { size: 9 * 1024 * 1024, limit: 8 * 1024 * 1024 }],
  ["limit", { reason: "pixels" }],
  ["invalid", { reason: "malformed" }],
  ["changed", { reason: "changed" }],
  ["unsupported", { reason: "unsupported_type" }],
  ["render_failed", {}],
  ["unsupported_browser", {}],
  ["offline", {}],
  ["forbidden", {}],
  ["busy", {}],
  ["transfer_failed", {}],
  ["session_ended", {}],
  // BP-07
  ["pdf_password_required", {}],
  ["pdf_too_many_pages", { pages: 10_000, limit: 200 }],
];

function text(state: BinaryDenialState, detail: BinaryPreviewDetail) {
  return mount(PreviewDenied, {
    props: { binary: { state, detail }, relPath: "img/a.png" },
  }).text();
}

describe("PreviewDenied — binary states", () => {
  it("states_are_distinct: every state's copy differs, and none says download or save", () => {
    const seen = new Map<string, BinaryDenialState>();
    for (const [state, detail] of STATES) {
      const copy = text(state, detail);
      expect(copy.length, state).toBeGreaterThan(0);
      for (const word of ["下載", "另存", "儲存", "Download", "Save"]) {
        expect(copy, `${state} mentions ${word}`).not.toContain(word);
      }
      expect(seen.get(copy), `${state} repeats another state`).toBeUndefined();
      seen.set(copy, state);
    }
    expect(seen.size).toBe(STATES.length);
  });

  it("the three limit reasons say which limit it was", () => {
    const copies = ["pixels", "dimensions", "complexity"].map((reason) =>
      text("limit", { reason }),
    );
    expect(new Set(copies).size).toBe(3);
    expect(copies[0]).toContain("像素");
    expect(copies[1]).toContain("邊長");
    expect(copies[2]).toContain("複雜");
  });

  it("too_large names the actual size and the limit", () => {
    const copy = text("too_large", {
      size: 9 * 1024 * 1024,
      limit: 8 * 1024 * 1024,
    });
    expect(copy).toContain("9.00 MB");
    expect(copy).toContain("8.00 MB");
    expect(copy).toContain("終端機");
  });

  it("sensitive: says it is protected and nothing about the classification", () => {
    const copy = text("denied_sensitive", { reason: "private_key" });
    expect(copy).toContain("此檔案受保護，不提供預覽");
    expect(copy).not.toContain("私鑰");
  });

  it("pdf_too_many_pages names the page count and the limit", () => {
    const copy = text("pdf_too_many_pages", { pages: 10_000, limit: 200 });
    expect(copy).toContain("10000");
    expect(copy).toContain("200");
  });

  it("pdf_password_required says a password is needed and asks for none", () => {
    const w = mount(PreviewDenied, {
      props: {
        binary: { state: "pdf_password_required", detail: {} },
        relPath: "secret.pdf",
      },
    });
    expect(w.text()).toContain("此 PDF 需要密碼才能開啟，預覽不支援");
    expect(w.find("input").exists()).toBe(false);
  });

  it("session ended offers no retry that cannot work", () => {
    const w = mount(PreviewDenied, {
      props: {
        binary: { state: "session_ended", detail: {} },
        relPath: "a.png",
      },
    });
    expect(w.findAll("button")).toHaveLength(0);
  });

  it("retry only where asking again can help", () => {
    const retryable = new Set([
      "changed",
      "offline",
      "busy",
      "transfer_failed",
      "cancelled",
    ]);
    for (const [state, detail] of STATES) {
      const w = mount(PreviewDenied, {
        props: { binary: { state, detail }, relPath: "a.png" },
      });
      const hasRetry = w
        .findAll("button")
        .some((b) => b.text() === "重試" || b.text() === "重新載入");
      expect(hasRetry, state).toBe(retryable.has(state));
    }
  });
});
