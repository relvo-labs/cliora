import { effectScope } from "vue";
import { describe, expect, it, vi } from "vitest";

import { ApiError } from "../api/client";
import type { FileStoreResult } from "../api/dto";
import {
  MAX_BATCH,
  filenameRefusal,
  filesFromDrop,
  suggestRename,
  useFileUpload,
  type FileUploader,
} from "./useFileUpload";

// The tests are organised around the properties the design leans on, not the
// happy path: a folder never reaches the network, a bad name never reaches the
// network, uploads run one at a time, and a collision is answered by a rename
// rather than by a second attempt at the same name.

function file(name: string, size = 8): File {
  return new File([new Uint8Array(size)], name, { type: "text/plain" });
}

function stored(path: string): FileStoreResult {
  return { path, size: 8, modified_at: "2026-08-03T00:00:00Z" };
}

/** Runs `body` inside an effect scope so onScopeDispose has an owner, matching
 * how the composable is used from a component. */
async function inScope<T>(body: () => Promise<T> | T): Promise<T> {
  const scope = effectScope();
  try {
    return await (scope.run(body) as Promise<T>);
  } finally {
    scope.stop();
  }
}

function fakeItem(
  kind: string,
  entry: { isFile: boolean } | null,
  asFile: File | null,
): DataTransferItem {
  return {
    kind,
    type: "text/plain",
    webkitGetAsEntry: () => entry,
    getAsFile: () => asFile,
    getAsString: () => undefined,
  } as unknown as DataTransferItem;
}

function fakeTransfer(items: DataTransferItem[] | null): DataTransfer {
  return { items } as unknown as DataTransfer;
}

describe("filenameRefusal", () => {
  it("accepts ordinary and non-ascii names", () => {
    for (const name of [
      "data.csv",
      "測試資料.csv",
      "a+b c.txt",
      ".editorconfig",
    ]) {
      expect(filenameRefusal(name), name).toBe("");
    }
  });

  it("refuses a name that is a path, or is not a name", () => {
    expect(filenameRefusal("")).not.toBe("");
    expect(filenameRefusal("a/b.txt")).not.toBe("");
    expect(filenameRefusal("..")).not.toBe("");
    expect(filenameRefusal(".")).not.toBe("");
    expect(filenameRefusal("ab")).not.toBe("");
  });

  it("measures length in bytes, not characters", () => {
    // 84 CJK characters plus ".csv" is 88 characters and 256 bytes. A
    // character-counted limit would let this through and the node would refuse it.
    const cjk = "測".repeat(84) + ".csv";
    expect(cjk.length).toBeLessThan(255);
    expect(filenameRefusal(cjk)).not.toBe("");
    expect(filenameRefusal("a".repeat(255))).toBe("");
    expect(filenameRefusal("a".repeat(256))).not.toBe("");
  });
});

describe("filesFromDrop", () => {
  it("takes files that are positively confirmed to be files", () => {
    const f = file("data.csv");
    const { files, refusal } = filesFromDrop(
      fakeTransfer([fakeItem("file", { isFile: true }, f)]),
    );
    expect(refusal).toBe("");
    expect(files).toEqual([f]);
  });

  it("refuses the whole batch when any item is a directory", () => {
    // Not "skip the folder and upload the rest": a user who drags a folder and
    // sees three of its files upload will believe the folder uploaded.
    const { files, refusal } = filesFromDrop(
      fakeTransfer([
        fakeItem("file", { isFile: true }, file("a.txt")),
        fakeItem("file", { isFile: false }, null),
      ]),
    );
    expect(files).toEqual([]);
    expect(refusal).toContain("資料夾");
  });

  it("refuses when nothing can be confirmed", () => {
    // Positive confirmation, not directory detection: an entry we cannot classify
    // is refused rather than assumed to be a file. The behaviour of
    // webkitGetAsEntry could not be measured where this was written, so the code
    // must not depend on it being truthful.
    expect(filesFromDrop(fakeTransfer(null)).refusal).not.toBe("");
    expect(filesFromDrop(fakeTransfer([])).refusal).not.toBe("");
    expect(
      filesFromDrop(fakeTransfer([fakeItem("file", null, file("a.txt"))]))
        .refusal,
    ).not.toBe("");
    expect(filesFromDrop(null).refusal).not.toBe("");
  });
});

describe("suggestRename", () => {
  it("keeps the extension", () => {
    expect(suggestRename("data.csv")).toBe("data-2.csv");
    expect(suggestRename("archive.tar.gz")).toBe("archive.tar-2.gz");
    expect(suggestRename("Makefile")).toBe("Makefile-2");
    expect(suggestRename(".gitignore")).toBe(".gitignore-2");
  });
});

describe("useFileUpload", () => {
  it("uploads to the given directory and reports what to refresh", async () => {
    const upload = vi.fn(async () =>
      stored("datasets/data.csv"),
    ) as unknown as FileUploader;
    const outcome = await inScope(async () => {
      const q = useFileUpload(upload);
      return q.submit([file("data.csv")], "datasets");
    });
    expect(outcome).toEqual({
      touched: ["datasets"],
      succeeded: 1,
      failed: 0,
    });
    expect(upload).toHaveBeenCalledTimes(1);
    expect(
      (upload as unknown as ReturnType<typeof vi.fn>).mock.calls[0][0],
    ).toBe("datasets");
  });

  it("uploads sequentially, never in parallel", async () => {
    // filesystem.store is a large-frame type on the node's single control
    // connection; twenty concurrent 4 MiB uploads would block it for everything
    // else on that node.
    let inFlight = 0;
    let maxInFlight = 0;
    const upload: FileUploader = async (dir, name) => {
      inFlight += 1;
      maxInFlight = Math.max(maxInFlight, inFlight);
      await new Promise((resolve) => setTimeout(resolve, 1));
      inFlight -= 1;
      return stored(`${dir}/${name}`);
    };
    const outcome = await inScope(async () => {
      const q = useFileUpload(upload);
      return q.submit([file("a.txt"), file("b.txt"), file("c.txt")], "docs");
    });
    expect(outcome.succeeded).toBe(3);
    expect(maxInFlight).toBe(1);
  });

  it("reports each touched directory once", async () => {
    const upload: FileUploader = async (dir, name) => stored(`${dir}/${name}`);
    const outcome = await inScope(async () => {
      const q = useFileUpload(upload);
      return q.submit([file("a.txt"), file("b.txt")], "docs");
    });
    // One refresh per batch, not one per file: three uploads should not make the
    // tree jump three times.
    expect(outcome.touched).toEqual(["docs"]);
  });

  it("refuses an oversize file and a bad name without a request", async () => {
    const upload = vi.fn(async () => stored("x")) as unknown as FileUploader;
    const items = await inScope(async () => {
      const q = useFileUpload(upload);
      await q.submit(
        [file("big.bin", 4 * 1024 * 1024 + 1), file("a/b.txt")],
        "docs",
      );
      return q.items.value.map((i) => ({ name: i.name, code: i.errorCode }));
    });
    expect(upload).not.toHaveBeenCalled();
    expect(items).toEqual([
      { name: "big.bin", code: "FILE_UPLOAD_TOO_LARGE" },
      { name: "a/b.txt", code: "FILE_INVALID_NAME" },
    ]);
  });

  it("keeps going after one file fails", async () => {
    const upload: FileUploader = async (dir, name) => {
      if (name === "b.txt") throw new ApiError("FILE_EXISTS", "taken", 409);
      return stored(`${dir}/${name}`);
    };
    const result = await inScope(async () => {
      const q = useFileUpload(upload);
      const outcome = await q.submit(
        [file("a.txt"), file("b.txt"), file("c.txt")],
        "docs",
      );
      return { outcome, states: q.items.value.map((i) => i.state) };
    });
    expect(result.outcome).toEqual({
      touched: ["docs"],
      succeeded: 2,
      failed: 1,
    });
    expect(result.states).toEqual(["done", "error", "done"]);
  });

  it("answers a collision with a rename that keeps the bytes", async () => {
    // Upload never overwrites, so the only answer to FILE_EXISTS is a different
    // name — and the user must not have to pick the file again.
    const seen: string[] = [];
    const upload: FileUploader = async (dir, name, f) => {
      seen.push(`${name}:${f.size}`);
      if (name === "data.csv") throw new ApiError("FILE_EXISTS", "taken", 409);
      return stored(`${dir}/${name}`);
    };
    const result = await inScope(async () => {
      const q = useFileUpload(upload);
      await q.submit([file("data.csv", 12)], "datasets");
      const failed = q.items.value[0];
      expect(failed.errorCode).toBe("FILE_EXISTS");
      const outcome = await q.retryAs(failed.id, suggestRename(failed.name));
      return { outcome, items: q.items.value.map((i) => i.name) };
    });
    expect(seen).toEqual(["data.csv:12", "data-2.csv:12"]);
    expect(result.outcome.succeeded).toBe(1);
    expect(result.items).toEqual(["data-2.csv"]);
  });

  it("caps a batch and says so", async () => {
    const upload: FileUploader = async (dir, name) => stored(`${dir}/${name}`);
    const result = await inScope(async () => {
      const q = useFileUpload(upload);
      const files = Array.from({ length: MAX_BATCH + 3 }, (_, i) =>
        file(`f${i}.txt`),
      );
      const outcome = await q.submit(files, "docs");
      return { outcome, refusal: q.batchRefusal.value };
    });
    expect(result.outcome.succeeded).toBe(MAX_BATCH);
    expect(result.refusal).toContain(String(MAX_BATCH));
  });

  it("surfaces a 403 as a permission message", async () => {
    const upload: FileUploader = async () => {
      throw new ApiError("FORBIDDEN", "nope", 403);
    };
    const message = await inScope(async () => {
      const q = useFileUpload(upload);
      await q.submit([file("a.txt")], "docs");
      return q.items.value[0].errorMessage;
    });
    expect(message).toContain("權限");
  });
});
