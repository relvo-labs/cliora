import { describe, expect, it, vi } from "vitest";
import { effectScope } from "vue";

import { ApiError } from "../api/client";
import type { FileUploadResult } from "../api/dto";
import { useImageDrop, type ImageUploader } from "./useImageDrop";

// Image drop (WF-07, ADR 0024). The cases here are the ones the design depends
// on: one code path for three entry points, a text paste that is left alone,
// local refusal before any upload, and no leaked object URLs.

const STORED = ".cliora/uploads/2026-08-05/01K1ZQ9F3B7T2M8V4X6Y0N5R3D.png";

function result(path = STORED): FileUploadResult {
  return {
    path,
    mime: "image/png",
    size: 12,
    modified_at: "2026-08-05T09:00:00Z",
  };
}

function pngFile(name = "shot.png", size = 12): File {
  const file = new File([new Uint8Array(size)], name, { type: "image/png" });
  return file;
}

function run<T>(fn: () => T): T {
  // useImageDrop registers onScopeDispose, which warns outside an active scope.
  const scope = effectScope();
  return scope.run(fn) as T;
}

function stubObjectUrls(): { created: number; revoked: string[] } {
  const state = { created: 0, revoked: [] as string[] };
  vi.stubGlobal("URL", {
    ...URL,
    createObjectURL: () => `blob:stub-${++state.created}`,
    revokeObjectURL: (url: string) => state.revoked.push(url),
  });
  return state;
}

describe("useImageDrop", () => {
  it("uploads an accepted image and returns the daemon-chosen path", async () => {
    stubObjectUrls();
    const upload = vi.fn<ImageUploader>(async () => result());
    const drop = run(() => useImageDrop(upload));

    const path = await drop.submit(pngFile());

    expect(path).toBe(STORED);
    expect(drop.state.value).toBe("done");
    expect(upload).toHaveBeenCalledOnce();
    // The user's filename stays a label; it is never what the server stores.
    expect(drop.current.value?.label).toBe("shot.png");
    expect(drop.current.value?.storedPath).toBe(STORED);
  });

  it("refuses an unsupported type without uploading", async () => {
    stubObjectUrls();
    const upload = vi.fn<ImageUploader>(async () => result());
    const drop = run(() => useImageDrop(upload));

    const svg = new File(["<svg/>"], "x.svg", { type: "image/svg+xml" });
    const path = await drop.submit(svg);

    expect(path).toBeNull();
    expect(upload).not.toHaveBeenCalled();
    expect(drop.errorCode.value).toBe("FILE_UPLOAD_UNSUPPORTED_TYPE");
  });

  it("refuses an oversize image without uploading", async () => {
    stubObjectUrls();
    const upload = vi.fn<ImageUploader>(async () => result());
    const drop = run(() => useImageDrop(upload));

    const path = await drop.submit(pngFile("big.png", 4 * 1024 * 1024 + 1));

    expect(path).toBeNull();
    expect(upload).not.toHaveBeenCalled();
    expect(drop.errorCode.value).toBe("FILE_UPLOAD_TOO_LARGE");
  });

  it("surfaces the server's code so the UI can say what to do", async () => {
    stubObjectUrls();
    const upload = vi.fn<ImageUploader>(async () => {
      throw new ApiError("FILE_UPLOAD_QUOTA_EXCEEDED", "quota full", 429);
    });
    const drop = run(() => useImageDrop(upload));

    expect(await drop.submit(pngFile())).toBeNull();
    expect(drop.state.value).toBe("error");
    expect(drop.errorCode.value).toBe("FILE_UPLOAD_QUOTA_EXCEEDED");
  });

  it("leaves an ordinary text paste alone", () => {
    stubObjectUrls();
    const drop = run(() => useImageDrop(vi.fn<ImageUploader>()));
    const preventDefault = vi.fn();
    const stopPropagation = vi.fn();
    const event = {
      clipboardData: { files: [] as unknown as FileList },
      preventDefault,
      stopPropagation,
    } as unknown as ClipboardEvent;

    expect(drop.handlePaste(event)).toBeNull();
    // xterm.js must still receive the paste; breaking text paste to gain image
    // paste would be a bad trade.
    expect(preventDefault).not.toHaveBeenCalled();
    expect(stopPropagation).not.toHaveBeenCalled();
  });

  it("takes over a paste that carries an image", () => {
    stubObjectUrls();
    const drop = run(() => useImageDrop(vi.fn<ImageUploader>()));
    const preventDefault = vi.fn();
    const file = pngFile();
    const event = {
      clipboardData: { files: [file] as unknown as FileList },
      preventDefault,
      stopPropagation: vi.fn(),
    } as unknown as ClipboardEvent;

    expect(drop.handlePaste(event)).toBe(file);
    expect(preventDefault).toHaveBeenCalled();
  });

  it("ignores a paste whose files are not images", () => {
    stubObjectUrls();
    const drop = run(() => useImageDrop(vi.fn<ImageUploader>()));
    const zip = new File([new Uint8Array(4)], "a.zip", {
      type: "application/zip",
    });
    const preventDefault = vi.fn();
    const event = {
      clipboardData: { files: [zip] as unknown as FileList },
      preventDefault,
      stopPropagation: vi.fn(),
    } as unknown as ClipboardEvent;

    expect(drop.handlePaste(event)).toBeNull();
    expect(preventDefault).not.toHaveBeenCalled();
  });

  it("reads the same file from a drop event", () => {
    stubObjectUrls();
    const drop = run(() => useImageDrop(vi.fn<ImageUploader>()));
    const file = pngFile();
    const event = {
      dataTransfer: { files: [file] as unknown as FileList },
      preventDefault: vi.fn(),
    } as unknown as DragEvent;

    expect(drop.handleDrop(event)).toBe(file);
  });

  it("revokes the preview URL on clear, so blobs do not accumulate", async () => {
    const urls = stubObjectUrls();
    const drop = run(() =>
      useImageDrop(vi.fn<ImageUploader>(async () => result())),
    );

    await drop.submit(pngFile());
    const created = drop.current.value?.previewUrl;
    drop.clear();

    expect(urls.revoked).toContain(created);
    expect(drop.current.value).toBeNull();
    expect(drop.state.value).toBe("idle");
  });

  it("revokes the previous preview when a second image replaces it", async () => {
    const urls = stubObjectUrls();
    const drop = run(() =>
      useImageDrop(vi.fn<ImageUploader>(async () => result())),
    );

    await drop.submit(pngFile("one.png"));
    const first = drop.current.value?.previewUrl;
    await drop.submit(pngFile("two.png"));

    expect(urls.revoked).toContain(first);
  });

  it("reports a cancelled upload as no result rather than an error", async () => {
    stubObjectUrls();
    const drop = run(() =>
      useImageDrop(
        vi.fn<ImageUploader>(async () => {
          throw new ApiError("CANCELLED", "aborted", 0);
        }),
      ),
    );

    expect(await drop.submit(pngFile())).toBeNull();
    expect(drop.state.value).toBe("idle");
    expect(drop.errorCode.value).toBeUndefined();
  });
});

// Issue #143: body transfer is not storage confirmation; obsolete work owns nothing.
describe("image upload liveness", () => {
  it("shows storage confirmation as pending after body transfer", async () => {
    stubObjectUrls();
    let finish!: (value: FileUploadResult) => void;
    const drop = run(() =>
      useImageDrop((_file, progress) => {
        progress(1);
        return new Promise((resolve) => {
          finish = resolve;
        });
      }),
    );
    const pending = drop.submit(pngFile());
    expect(drop.state.value).toBe("confirming");
    finish(result());
    await pending;
    expect(drop.state.value).toBe("done");
  });

  it.each(["cancel", "clear", "replace", "invalid", "dispose"])(
    "discards late progress and success after %s",
    async (action) => {
      stubObjectUrls();
      let finish!: (value: FileUploadResult) => void;
      let report!: (fraction: number) => void;
      const scope = effectScope();
      const drop = scope.run(() =>
        useImageDrop((_file, progress) => {
          report = progress;
          return new Promise((resolve) => {
            finish = resolve;
          });
        }),
      )!;
      const pending = drop.submit(pngFile());
      const oldFinish = finish;
      const oldReport = report;
      if (action === "dispose") scope.stop();
      else if (action === "replace") void drop.submit(pngFile("new.png"));
      else if (action === "invalid")
        await drop.submit(new File(["x"], "x.svg", { type: "image/svg+xml" }));
      else drop[action as "cancel" | "clear"]();
      const before = {
        state: drop.state.value,
        progress: drop.progress.value,
        current: drop.current.value,
      };
      oldReport(0.9);
      oldFinish(result());
      expect(await pending).toBeNull();
      expect({
        state: drop.state.value,
        progress: drop.progress.value,
        current: drop.current.value,
      }).toEqual(before);
      scope.stop();
    },
  );
});
