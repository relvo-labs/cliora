import { describe, expect, it, vi } from "vitest";

import {
  PREVIEW_TRANSFER_FAILED,
  readPreviewBody,
} from "../composables/useBinaryPreview";
import { ApiClient, ApiError } from "./client";
import type { TokenStore } from "./client";

// The read-only binary preview call (ADR 0029 §6, plan/31/05 BP-06 §2).
//
// Two properties are pinned here because nothing downstream can see them: the
// workspace path never appears in the URL (every hop logs URLs), and a body
// that does not deliver exactly what it declared is refused as a whole rather
// than handed on as a truncated image. The request is the client's; reading
// the body is the preview owner's, so it stays in the preview's lazy chunk.

const store: TokenStore = {
  accessToken: () => "token",
  refreshToken: () => null,
  setTokens: () => {},
  clear: () => {},
};

function client(fetchImpl: unknown): ApiClient {
  return new ApiClient(store, fetchImpl as typeof fetch);
}

const SID = "44444444-4444-4444-8444-444444444444";

function streamOf(parts: Uint8Array[]): ReadableStream<Uint8Array> {
  return new ReadableStream({
    start(controller) {
      for (const part of parts) controller.enqueue(part);
      controller.close();
    },
  });
}

function previewResponse(
  parts: Uint8Array[],
  headers: Record<string, string>,
): Response {
  return new Response(streamOf(parts), {
    status: 200,
    headers: {
      "Content-Type": "application/octet-stream",
      "X-Cliora-Preview-Mime": "image/png",
      "X-Cliora-Preview-Kind": "image",
      "X-Cliora-Preview-Width": "2",
      "X-Cliora-Preview-Height": "1",
      ...headers,
    },
  });
}

describe("ApiClient.fetchBinaryPreview", () => {
  it("path_travels_in_body: POST, JSON body, no query string, path only in the body", async () => {
    const fetchImpl = vi.fn(
      async (_url: string, _init: NonNullable<Parameters<typeof fetch>[1]>) =>
        previewResponse([new Uint8Array([1, 2, 3])], { "Content-Length": "3" }),
    );
    const path = "機密 dir/bp-canary+x/photo 1.png";
    await client(fetchImpl).fetchBinaryPreview(SID, path);

    expect(fetchImpl).toHaveBeenCalledTimes(1);
    const [url, init] = fetchImpl.mock.calls[0];
    expect(init.method).toBe("POST");
    expect((init.headers as Record<string, string>)["Content-Type"]).toBe(
      "application/json",
    );
    expect(url.endsWith(`/api/sessions/${SID}/files/binary-preview`)).toBe(
      true,
    );
    expect(url).not.toContain("?");
    // Neither the raw nor the percent-encoded form of any path segment.
    for (const fragment of ["機密", "bp-canary", "photo", "png"]) {
      expect(url).not.toContain(fragment);
      expect(url).not.toContain(encodeURIComponent(fragment));
    }
    expect(JSON.parse(init.body as string)).toEqual({ path });
  });

  it("an in-band refusal keeps its code, status and details", async () => {
    const fetchImpl = vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            error: {
              code: "FILE_PREVIEW_LIMIT",
              message: "limit",
              details: { reason: "pixels" },
            },
            request_id: "r",
          }),
          { status: 413, headers: { "Content-Type": "application/json" } },
        ),
    );
    const error = (await client(fetchImpl)
      .fetchBinaryPreview(SID, "a.png")
      .catch((e: unknown) => e)) as ApiError;
    expect(error.code).toBe("FILE_PREVIEW_LIMIT");
    expect(error.status).toBe(413);
    expect(error.details).toEqual({ reason: "pixels" });
  });
});

describe("readPreviewBody", () => {
  it("returns the declared metadata and exactly the bytes that arrived", async () => {
    const progress: Array<[number, number]> = [];
    const result = await readPreviewBody(
      previewResponse([new Uint8Array([1, 2]), new Uint8Array([3, 4, 5])], {
        "Content-Length": "5",
      }),
      (received, total) => progress.push([received, total]),
    );
    expect(result.meta).toEqual({
      kind: "image",
      mime: "image/png",
      size: 5,
      width: 2,
      height: 1,
    });
    expect([...result.bytes]).toEqual([1, 2, 3, 4, 5]);
    expect(progress.at(-1)).toEqual([5, 5]);
  });

  const refusals: Array<[string, Uint8Array[], Record<string, string>]> = [
    [
      "a stream shorter than Content-Length",
      [new Uint8Array([1, 2])],
      { "Content-Length": "10" },
    ],
    [
      "a stream longer than Content-Length",
      [new Uint8Array(4), new Uint8Array(4)],
      { "Content-Length": "5" },
    ],
    [
      "a declared size over the kind's ceiling",
      [new Uint8Array(1)],
      { "Content-Length": String(8 * 1024 * 1024 + 1) },
    ],
    [
      "a MIME outside the allowlist",
      [new Uint8Array(3)],
      { "Content-Length": "3", "X-Cliora-Preview-Mime": "image/svg+xml" },
    ],
    [
      "a kind that contradicts the MIME",
      [new Uint8Array(3)],
      { "Content-Length": "3", "X-Cliora-Preview-Kind": "pdf" },
    ],
    [
      "an image without its dimensions",
      [new Uint8Array(3)],
      { "Content-Length": "3", "X-Cliora-Preview-Width": "" },
    ],
  ];
  for (const [name, parts, headers] of refusals) {
    it(`${name} is a transfer failure with no bytes`, async () => {
      const error = await readPreviewBody(
        previewResponse(parts, headers),
      ).catch((e: unknown) => e);
      expect(error).toBeInstanceOf(ApiError);
      expect((error as ApiError).code).toBe(PREVIEW_TRANSFER_FAILED);
    });
  }
});
