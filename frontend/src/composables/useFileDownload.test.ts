import { describe, expect, it, vi } from "vitest";
import { effectScope } from "vue";

import { ApiError } from "../api/client";
import { useFileDownload } from "./useFileDownload";

// Workspace file download (FD-06, ADR 0028).
//
// The composable is small, so the tests are about the two things a browser makes
// easy to get wrong and impossible to see: a superseded request saving its bytes
// over a newer one's, and an in-flight request outliving the view that started
// it. Neither shows up in manual testing — the first needs two clicks inside one
// round trip, the second needs a 4 MiB file and a tab change.

function blob(text: string): Blob {
  return new Blob([text], { type: "application/octet-stream" });
}

// A downloader whose promise is resolved by the test, so ordering is decided here
// rather than by the scheduler.
function deferred() {
  const calls: {
    path: string;
    signal: AbortSignal;
    resolve: (v: { blob: Blob; filename: string }) => void;
    reject: (e: unknown) => void;
  }[] = [];
  const download = (path: string, signal: AbortSignal) =>
    new Promise<{ blob: Blob; filename: string }>((resolve, reject) => {
      calls.push({ path, signal, resolve, reject });
      signal.addEventListener("abort", () => {
        const error = new Error("aborted");
        error.name = "AbortError";
        reject(error);
      });
    });
  return { calls, download };
}

describe("useFileDownload", () => {
  it("saves the bytes and the server-chosen filename", async () => {
    const save = vi.fn();
    const dl = useFileDownload(
      async () => ({ blob: blob("a,b\n"), filename: "data.csv" }),
      save,
    );

    await expect(dl.start("datasets/data.csv")).resolves.toBe(true);
    expect(save).toHaveBeenCalledTimes(1);
    // The filename comes from Content-Disposition, not from the path: the two can
    // differ, and the server's answer is the one both browsers agree on.
    expect(save.mock.calls[0][1]).toBe("data.csv");
    expect(dl.state.value).toBe("idle");
    expect(dl.activePath.value).toBeNull();
  });

  it("reports which path is in flight so one row can show a spinner", async () => {
    const { calls, download } = deferred();
    const dl = useFileDownload(download, vi.fn());

    const pending = dl.start("a/big.bin");
    expect(dl.state.value).toBe("downloading");
    expect(dl.activePath.value).toBe("a/big.bin");
    calls[0].resolve({ blob: blob(""), filename: "big.bin" });
    await pending;
    expect(dl.activePath.value).toBeNull();
  });

  it("a superseded download never saves over the newer one", async () => {
    const save = vi.fn();
    const { calls, download } = deferred();
    const dl = useFileDownload(download, save);

    const first = dl.start("old.txt");
    const second = dl.start("new.txt");
    // The first request is aborted by the second, but a real network can still
    // deliver its body afterwards — so resolving it late must change nothing.
    calls[0].resolve({ blob: blob("stale"), filename: "old.txt" });
    calls[1].resolve({ blob: blob("fresh"), filename: "new.txt" });
    await Promise.all([first, second]);

    expect(save).toHaveBeenCalledTimes(1);
    expect(save.mock.calls[0][1]).toBe("new.txt");
    // And the superseded one must not leave an error behind, or the newer
    // download looks broken while it is succeeding.
    expect(dl.state.value).toBe("idle");
    expect(dl.errorMessage.value).toBe("");
  });

  it("aborts the request when the scope is disposed", async () => {
    const { calls, download } = deferred();
    const scope = effectScope();
    let dl!: ReturnType<typeof useFileDownload>;
    scope.run(() => {
      dl = useFileDownload(download, vi.fn());
    });
    const pending = dl.start("big.bin");
    expect(calls[0].signal.aborted).toBe(false);

    scope.stop();
    expect(calls[0].signal.aborted).toBe(true);
    await expect(pending).resolves.toBe(false);
  });

  it("a cancelled download is not an error", async () => {
    const { download } = deferred();
    const dl = useFileDownload(download, vi.fn());
    const pending = dl.start("big.bin");
    dl.cancel();

    await expect(pending).resolves.toBe(false);
    expect(dl.state.value).toBe("idle");
    expect(dl.errorMessage.value).toBe("");
  });

  it.each([
    ["FILE_DENIED", 403, "This file cannot be downloaded"],
    ["FILE_TOO_LARGE", 413, "The file is larger than the 4 MiB download limit"],
    ["FILE_DOWNLOAD_DISABLED", 403, "This node does not hand files back"],
    ["NODE_OFFLINE", 409, "Node is not connected"],
  ])("shows the server's own wording for %s", async (code, status, message) => {
    const dl = useFileDownload(async () => {
      throw new ApiError(code, message, status);
    }, vi.fn());

    await expect(dl.start("a.txt")).resolves.toBe(false);
    expect(dl.state.value).toBe("error");
    // Each of these has a different next step, so each keeps its own sentence.
    expect(dl.errorMessage.value).toBe(message);
  });

  it("an unrecognised 403 reads as a permission problem, not as a file problem", async () => {
    const dl = useFileDownload(async () => {
      throw new ApiError("FORBIDDEN", "Forbidden", 403);
    }, vi.fn());

    await expect(dl.start("a.txt")).resolves.toBe(false);
    expect(dl.errorMessage.value).toContain("權限");
  });

  it("collapses anything else into one sentence", async () => {
    const dl = useFileDownload(async () => {
      throw new Error("socket hang up");
    }, vi.fn());

    await expect(dl.start("a.txt")).resolves.toBe(false);
    expect(dl.errorMessage.value).toBe("無法下載這個檔案。");
    dl.clearError();
    expect(dl.state.value).toBe("idle");
    expect(dl.errorMessage.value).toBe("");
  });
});
