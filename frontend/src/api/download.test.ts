import { describe, expect, it, vi } from "vitest";

import { ApiClient, ApiError, filenameFromDisposition } from "./client";
import type { TokenStore } from "./client";

// The download call and the one header it depends on (FD-06, ADR 0028).
//
// `filenameFromDisposition` gets the bulk of the attention because it is the
// piece with no visible failure: taking the ASCII fallback when the starred form
// is present does not error, it just silently saves 年度統計.csv as download.csv,
// and nobody reports that as a bug — they rename the file and move on.

describe("filenameFromDisposition", () => {
  it("prefers the RFC 5987 form over the ASCII fallback", () => {
    expect(
      filenameFromDisposition(
        `attachment; filename="download.csv"; filename*=UTF-8''%E5%B9%B4%E5%BA%A6%E7%B5%B1%E8%A8%88.csv`,
      ),
    ).toBe("年度統計.csv");
  });

  it("falls back to the ASCII form when there is no starred one", () => {
    expect(filenameFromDisposition('attachment; filename="data.csv"')).toBe(
      "data.csv",
    );
  });

  it("falls back rather than throwing on a malformed escape", () => {
    // A bad percent-escape is not worth failing a download over, which is exactly
    // what an uncaught decodeURIComponent would do.
    expect(
      filenameFromDisposition(
        `attachment; filename="ok.csv"; filename*=UTF-8''%E5%`,
      ),
    ).toBe("ok.csv");
  });

  it("returns null when there is no header and no name in it", () => {
    expect(filenameFromDisposition(null)).toBeNull();
    expect(filenameFromDisposition("attachment")).toBeNull();
  });
});

// No refresh token, deliberately: these cases must not depend on the 401
// refresh-and-retry, which has its own tests next door in client.test.ts.
const store: TokenStore = {
  accessToken: () => "token",
  refreshToken: () => null,
  setTokens: () => {},
  clear: () => {},
};

function client(fetchImpl: unknown): ApiClient {
  return new ApiClient(store, fetchImpl as typeof fetch);
}

describe("ApiClient.downloadFile", () => {
  it("returns the bytes and the server's filename", async () => {
    // Typed through its parameters so `mock.calls[0][0]` is the request URL
    // rather than an element of an empty tuple.
    const fetchImpl = vi.fn(
      async (_url: unknown, _init?: unknown) =>
        new Response("a,b\n", {
          status: 200,
          headers: {
            "content-type": "application/octet-stream",
            "content-disposition": 'attachment; filename="data.csv"',
          },
        }),
    );
    const result = await client(fetchImpl).downloadFile(
      "11111111-1111-4111-8111-111111111111",
      "datasets/data.csv",
    );

    expect(await result.blob.text()).toBe("a,b\n");
    expect(result.filename).toBe("data.csv");
    const url = String(fetchImpl.mock.calls[0][0]);
    expect(url).toContain("/files/download?path=datasets%2Fdata.csv");
  });

  it("falls back to the path's last segment when the header carries no name", async () => {
    const fetchImpl = vi.fn(async () => new Response("", { status: 200 }));
    const result = await client(fetchImpl).downloadFile(
      "11111111-1111-4111-8111-111111111111",
      "src/__init__.py",
    );
    expect(result.filename).toBe("__init__.py");
  });

  it("raises the server's error code, because the error body is JSON even though the success body is bytes", async () => {
    const fetchImpl = vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            error: {
              code: "FILE_DENIED",
              message: "This file cannot be downloaded",
            },
            request_id: "r1",
          }),
          { status: 403, headers: { "content-type": "application/json" } },
        ),
    );

    await expect(
      client(fetchImpl).downloadFile(
        "11111111-1111-4111-8111-111111111111",
        ".env",
      ),
    ).rejects.toMatchObject({ code: "FILE_DENIED", status: 403 });
    await expect(
      client(fetchImpl).downloadFile(
        "11111111-1111-4111-8111-111111111111",
        ".env",
      ),
    ).rejects.toBeInstanceOf(ApiError);
  });
});
