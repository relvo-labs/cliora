import { describe, expect, it } from "vitest";
import { ProtocolError, decodeControl } from "./decode";

// Read-only binary preview, contract 1.11.0 (ADR 0029). The browser never sees
// these frames (the preview travels over HTTP), but the decoder validates them so
// the three consumers accept and reject the same messages.

const PREVIEW_ID = "01K6B9R3V1EW7Q2M8N4X6Y0Z5T";
const SESSION_ID = "22222222-2222-4222-8222-222222222222";

function frame(
  type: string,
  payload: Record<string, unknown>,
  success?: boolean,
): string {
  return JSON.stringify({
    version: 1,
    type,
    request_id: "01K0ABCDEFGHJKMNPQRSTVWXYZ",
    node_id: "11111111-1111-4111-8111-111111111111",
    timestamp: "2026-09-27T00:00:00Z",
    ...(success === undefined ? {} : { success }),
    payload,
  });
}

const image = {
  success: true,
  preview_id: PREVIEW_ID,
  path: "a/b.png",
  kind: "image",
  mime: "image/png",
  size: 1024,
  modified_at: "2026-09-27T00:00:00Z",
  chunk_size: 524288,
  chunk_count: 1,
  width: 10,
  height: 20,
};
const pdf = {
  ...image,
  path: "a/b.pdf",
  kind: "pdf",
  mime: "application/pdf",
  width: undefined,
  height: undefined,
};

const cases: Array<[string, string, boolean]> = [
  [
    "open",
    frame("filesystem.preview_open", { session_id: SESSION_ID, path: "a.png" }),
    true,
  ],
  [
    "open with mime",
    frame("filesystem.preview_open", {
      session_id: SESSION_ID,
      path: "a.png",
      mime: "image/png",
    }),
    false,
  ],
  [
    "open with offset",
    frame("filesystem.preview_open", {
      session_id: SESSION_ID,
      path: "a.png",
      offset: 0,
    }),
    false,
  ],
  [
    "open escape",
    frame("filesystem.preview_open", {
      session_id: SESSION_ID,
      path: "../a.png",
    }),
    false,
  ],
  ["opened image", frame("filesystem.preview_opened", image, true), true],
  [
    "opened image without size",
    frame(
      "filesystem.preview_opened",
      { ...image, width: undefined, height: undefined },
      true,
    ),
    false,
  ],
  [
    "opened svg",
    frame(
      "filesystem.preview_opened",
      { ...image, mime: "image/svg+xml" },
      true,
    ),
    false,
  ],
  ["opened pdf", frame("filesystem.preview_opened", pdf, true), true],
  [
    "opened pdf with width",
    frame("filesystem.preview_opened", { ...pdf, width: 10 }, true),
    false,
  ],
  [
    "opened pdf with image mime",
    frame("filesystem.preview_opened", { ...pdf, mime: "image/png" }, true),
    false,
  ],
  [
    "opened chunk size",
    frame("filesystem.preview_opened", { ...pdf, chunk_size: 1 }, true),
    false,
  ],
  [
    "opened chunk count",
    frame("filesystem.preview_opened", { ...pdf, chunk_count: 33 }, true),
    false,
  ],
  [
    "opened with disposition",
    frame(
      "filesystem.preview_opened",
      { ...pdf, disposition: "attachment" },
      true,
    ),
    false,
  ],
  [
    "denied",
    frame(
      "filesystem.preview_opened",
      {
        success: false,
        path: "a.png",
        error: { code: "FILE_PREVIEW_LIMIT", reason: "pixels" },
      },
      false,
    ),
    true,
  ],
  [
    "denied with a path as reason",
    frame(
      "filesystem.preview_opened",
      {
        success: false,
        path: "a.png",
        error: { code: "FILE_DENIED", reason: "/etc/passwd" },
      },
      false,
    ),
    false,
  ],
  [
    "denied with FILE_BINARY",
    frame(
      "filesystem.preview_opened",
      {
        success: false,
        path: "a.png",
        error: { code: "FILE_BINARY", reason: "binary" },
      },
      false,
    ),
    false,
  ],
  [
    "chunk",
    frame("filesystem.preview_chunk", {
      session_id: SESSION_ID,
      preview_id: PREVIEW_ID,
      index: 31,
    }),
    true,
  ],
  [
    "chunk 32",
    frame("filesystem.preview_chunk", {
      session_id: SESSION_ID,
      preview_id: PREVIEW_ID,
      index: 32,
    }),
    false,
  ],
  [
    "chunk without index",
    frame("filesystem.preview_chunk", {
      session_id: SESSION_ID,
      preview_id: PREVIEW_ID,
    }),
    false,
  ],
  [
    "data",
    frame(
      "filesystem.preview_data",
      { preview_id: PREVIEW_ID, index: 0, data: "QUJD" },
      true,
    ),
    true,
  ],
  [
    "data without success",
    frame("filesystem.preview_data", {
      preview_id: PREVIEW_ID,
      index: 0,
      data: "QUJD",
    }),
    false,
  ],
  [
    "data empty",
    frame(
      "filesystem.preview_data",
      { preview_id: PREVIEW_ID, index: 0, data: "" },
      true,
    ),
    false,
  ],
  [
    "close",
    frame("filesystem.preview_close", {
      session_id: SESSION_ID,
      preview_id: PREVIEW_ID,
    }),
    true,
  ],
  [
    "closed",
    frame("filesystem.preview_closed", { preview_id: PREVIEW_ID }, true),
    true,
  ],
  [
    "closed with bad id",
    frame("filesystem.preview_closed", { preview_id: "x" }, true),
    false,
  ],
];

describe("binary preview frames (contract 1.11.0)", () => {
  for (const [name, raw, accept] of cases) {
    it(`${accept ? "accepts" : "rejects"} ${name}`, () => {
      if (accept) expect(decodeControl(raw).type).toMatch(/^filesystem\./);
      else expect(() => decodeControl(raw)).toThrow(ProtocolError);
    });
  }

  it("binary_preview is const:true — a disabled daemon omits it", () => {
    const base = {
      name: "n",
      hostname: "h",
      os: "linux",
      os_version: "1",
      architecture: "amd64",
      daemon_version: "0.1.0",
      run_user: "agentd",
      runtimes: [],
      workspace_roots: [],
    };
    expect(decodeControl(frame("node.register", base)).type).toBe(
      "node.register",
    );
    expect(
      decodeControl(frame("node.register", { ...base, binary_preview: true }))
        .type,
    ).toBe("node.register");
    for (const value of [false, "true", null, 1])
      expect(() =>
        decodeControl(
          frame("node.register", { ...base, binary_preview: value }),
        ),
      ).toThrow(ProtocolError);
  });
});
