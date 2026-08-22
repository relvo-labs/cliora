import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiClient, ApiError, type TokenStore } from "./client";
import type { TokenPair } from "./dto";

interface FakeResponse {
  status: number;
  ok: boolean;
  text: () => Promise<string>;
  json: () => Promise<unknown>;
}

function res(status: number, body?: unknown): FakeResponse {
  const text = body === undefined ? "" : JSON.stringify(body);
  return {
    status,
    ok: status >= 200 && status < 300,
    text: () => Promise.resolve(text),
    json: () => Promise.resolve(JSON.parse(text)),
  };
}

// A refresh response whose `ok`/status are already settled (so refresh() gets
// past its `!res.ok` check and reads the current refresh token) but whose
// `json()` body parse is controlled by the test, to land state changes inside
// the TOCTOU window between that read and `await res.json()`.
function deferredJsonResponse(): {
  response: FakeResponse;
  jsonCalled: Promise<void>;
  resolveJson: (body: unknown) => void;
} {
  let markJsonCalled!: () => void;
  const jsonCalled = new Promise<void>((resolve) => {
    markJsonCalled = resolve;
  });
  let resolveJson!: (body: unknown) => void;
  const deferredBody = new Promise<unknown>((resolve) => {
    resolveJson = resolve;
  });
  const response: FakeResponse = {
    status: 200,
    ok: true,
    text: () => Promise.resolve(""),
    json: () => {
      markJsonCalled();
      return deferredBody;
    },
  };
  return { response, jsonCalled, resolveJson };
}

function makeStore(
  access: string | null,
  refresh: string | null,
): TokenStore & {
  current: () => { access: string | null; refresh: string | null };
} {
  let a = access;
  let r = refresh;
  return {
    accessToken: () => a,
    refreshToken: () => r,
    setTokens: (pair: TokenPair) => {
      a = pair.access_token;
      r = pair.refresh_token;
    },
    clear: () => {
      a = null;
      r = null;
    },
    current: () => ({ access: a, refresh: r }),
  };
}

describe("ApiClient", () => {
  let store: ReturnType<typeof makeStore>;

  beforeEach(() => {
    store = makeStore("access-1", "refresh-1");
  });

  it("maps an error body to a typed ApiError with code and request id", async () => {
    const fetchMock = vi.fn(() =>
      Promise.resolve(
        res(403, {
          error: { code: "FORBIDDEN", message: "nope" },
          request_id: "req-9",
        }),
      ),
    );
    const client = new ApiClient(store, fetchMock as unknown as typeof fetch);

    await expect(client.listNodes()).rejects.toMatchObject({
      name: "ApiError",
      code: "FORBIDDEN",
      status: 403,
      requestId: "req-9",
    });
    await expect(client.listNodes()).rejects.toBeInstanceOf(ApiError);
  });

  it("injects the Bearer access token on authenticated calls", async () => {
    const fetchMock = vi.fn(
      (_url: string, _init?: { headers?: Record<string, string> }) =>
        Promise.resolve(res(200, [])),
    );
    const client = new ApiClient(store, fetchMock as unknown as typeof fetch);

    await client.listNodes();
    expect(fetchMock.mock.calls[0][1]?.headers?.["Authorization"]).toBe(
      "Bearer access-1",
    );
  });

  it("refreshes once on 401 and retries the original request", async () => {
    let nodeCalls = 0;
    let refreshCalls = 0;
    const fetchMock = vi.fn((url: string) => {
      if (url.endsWith("/api/auth/refresh")) {
        refreshCalls += 1;
        return Promise.resolve(
          res(200, {
            access_token: "access-2",
            refresh_token: "refresh-2",
            token_type: "bearer",
          }),
        );
      }
      nodeCalls += 1;
      return Promise.resolve(
        nodeCalls === 1
          ? res(401, { error: { code: "UNAUTHENTICATED", message: "x" } })
          : res(200, [{ id: "n1" }]),
      );
    });
    const client = new ApiClient(store, fetchMock as unknown as typeof fetch);

    const result = await client.listNodes();
    expect(result).toEqual([{ id: "n1" }]);
    expect(refreshCalls).toBe(1);
    expect(store.current()).toEqual({
      access: "access-2",
      refresh: "refresh-2",
    });
  });

  it("shares a single refresh across concurrent 401s", async () => {
    let refreshCalls = 0;
    const nodeStatus = new Map<string, number>();
    const fetchMock = vi.fn((url: string) => {
      if (url.endsWith("/api/auth/refresh")) {
        refreshCalls += 1;
        return Promise.resolve(
          res(200, {
            access_token: "a2",
            refresh_token: "r2",
            token_type: "bearer",
          }),
        );
      }
      const seen = (nodeStatus.get(url) ?? 0) + 1;
      nodeStatus.set(url, seen);
      return Promise.resolve(
        seen === 1
          ? res(401, { error: { code: "UNAUTHENTICATED", message: "x" } })
          : res(200, []),
      );
    });
    const client = new ApiClient(store, fetchMock as unknown as typeof fetch);

    await Promise.all([client.getNode("a"), client.getNode("b")]);
    expect(refreshCalls).toBe(1);
  });

  it("gives up and clears tokens when refresh fails", async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url.endsWith("/api/auth/refresh")) {
        return Promise.resolve(
          res(401, { error: { code: "TOKEN_INVALID", message: "x" } }),
        );
      }
      return Promise.resolve(
        res(401, { error: { code: "UNAUTHENTICATED", message: "x" } }),
      );
    });
    const client = new ApiClient(store, fetchMock as unknown as typeof fetch);

    await expect(client.listNodes()).rejects.toBeInstanceOf(ApiError);
    expect(store.current()).toEqual({ access: null, refresh: null });
  });

  it("adopts a newer shared pair and retries the original request when a stale refresh loses the race", async () => {
    // Two browser contexts share one token backing (e.g. localStorage). This
    // store reads/writes that backing directly rather than through a private
    // closure, so a second context's rotation is visible to the first
    // context's in-flight refresh.
    const backing: { access: string | null; refresh: string | null } = {
      access: "access-1",
      refresh: "refresh-1",
    };
    const sharedStore: TokenStore = {
      accessToken: () => backing.access,
      refreshToken: () => backing.refresh,
      setTokens: (pair: TokenPair) => {
        backing.access = pair.access_token;
        backing.refresh = pair.refresh_token;
      },
      clear: () => {
        backing.access = null;
        backing.refresh = null;
      },
    };

    let resolveRefresh!: (value: FakeResponse) => void;
    const deferredRefresh = new Promise<FakeResponse>((resolve) => {
      resolveRefresh = resolve;
    });
    let refreshRequested!: () => void;
    const refreshWasRequested = new Promise<void>((resolve) => {
      refreshRequested = resolve;
    });

    const fetchMock = vi.fn(
      (url: string, init?: { headers?: Record<string, string> }) => {
        if (url.endsWith("/api/auth/refresh")) {
          refreshRequested();
          return deferredRefresh;
        }
        const authHeader = init?.headers?.["Authorization"];
        if (authHeader === "Bearer access-2") {
          return Promise.resolve(res(200, [{ id: "n1" }]));
        }
        return Promise.resolve(
          res(401, { error: { code: "UNAUTHENTICATED", message: "x" } }),
        );
      },
    );
    const client = new ApiClient(
      sharedStore,
      fetchMock as unknown as typeof fetch,
    );

    const pending = client.listNodes();
    await refreshWasRequested; // refresh-1 was sent; its response is still pending

    // Another browser context wins a concurrent refresh and rotates the shared pair.
    backing.access = "access-2";
    backing.refresh = "refresh-2";

    resolveRefresh(
      res(401, { error: { code: "TOKEN_INVALID", message: "expired" } }),
    );

    await expect(pending).resolves.toEqual([{ id: "n1" }]);
    expect(backing).toEqual({ access: "access-2", refresh: "refresh-2" });
  });

  it("does not resurrect a token pair cleared by an explicit logout during an in-flight refresh", async () => {
    // Another context calls store.clear() (e.g. the user hit "log out") while
    // this context's refresh-1 is still in flight. The refresh landing after
    // that clear must not write access-2/refresh-2 back in, and must not let
    // the original request complete as if still authenticated.
    let resolveRefresh!: (value: FakeResponse) => void;
    const deferredRefresh = new Promise<FakeResponse>((resolve) => {
      resolveRefresh = resolve;
    });
    let refreshRequested!: () => void;
    const refreshWasRequested = new Promise<void>((resolve) => {
      refreshRequested = resolve;
    });

    const fetchMock = vi.fn(
      (url: string, init?: { headers?: Record<string, string> }) => {
        if (url.endsWith("/api/auth/refresh")) {
          refreshRequested();
          return deferredRefresh;
        }
        const authHeader = init?.headers?.["Authorization"];
        if (authHeader === "Bearer access-2") {
          return Promise.resolve(res(200, [{ id: "n1" }]));
        }
        return Promise.resolve(
          res(401, { error: { code: "UNAUTHENTICATED", message: "x" } }),
        );
      },
    );
    const client = new ApiClient(store, fetchMock as unknown as typeof fetch);

    const pending = client.listNodes();
    await refreshWasRequested; // refresh-1 was sent; its response is still pending

    store.clear(); // explicit logout in another context

    resolveRefresh(
      res(200, {
        access_token: "access-2",
        refresh_token: "refresh-2",
        token_type: "bearer",
      }),
    );

    await expect(pending).rejects.toBeInstanceOf(ApiError);
    expect(store.current()).toEqual({ access: null, refresh: null });
  });

  it("does not resurrect a token pair cleared by an explicit logout while a same-token refresh body is still parsing", async () => {
    // The vulnerable window is inside refresh() itself: it reads the current
    // refresh token, finds it still matches refresh-1, and only *then* awaits
    // `res.json()`. If an explicit logout (store.clear()) lands after that read
    // but before the body finishes parsing, the late `setTokens` must not
    // resurrect the cleared session.
    const { response, jsonCalled, resolveJson } = deferredJsonResponse();
    let refreshRequested!: () => void;
    const refreshWasRequested = new Promise<void>((resolve) => {
      refreshRequested = resolve;
    });
    const fetchMock = vi.fn(
      (url: string, init?: { headers?: Record<string, string> }) => {
        if (url.endsWith("/api/auth/refresh")) {
          refreshRequested();
          return Promise.resolve(response);
        }
        const authHeader = init?.headers?.["Authorization"];
        if (authHeader === "Bearer access-2") {
          return Promise.resolve(res(200, [{ id: "n1" }]));
        }
        return Promise.resolve(
          res(401, { error: { code: "UNAUTHENTICATED", message: "x" } }),
        );
      },
    );
    const client = new ApiClient(store, fetchMock as unknown as typeof fetch);

    const pending = client.listNodes();
    await refreshWasRequested; // refresh-1 was sent and its 200 has landed
    await jsonCalled; // refresh() saw refresh-1 still current and started parsing the body

    store.clear(); // explicit logout in another context, mid-parse

    resolveJson({
      access_token: "access-2",
      refresh_token: "refresh-2",
      token_type: "bearer",
    });

    await expect(pending).rejects.toBeInstanceOf(ApiError);
    expect(store.current()).toEqual({ access: null, refresh: null });
  });

  it("keeps a newer rotated pair when a same-token refresh body resolves later with a stale pair", async () => {
    // Same vulnerable window as above: another context wins its own refresh and
    // rotates in access-3/refresh-3 while this context's refresh-1 response body
    // is still parsing. The stale access-2 pair from that late parse must not
    // overwrite the newer one, and the original request must retry with it.
    const { response, jsonCalled, resolveJson } = deferredJsonResponse();
    let refreshRequested!: () => void;
    const refreshWasRequested = new Promise<void>((resolve) => {
      refreshRequested = resolve;
    });
    const fetchMock = vi.fn(
      (url: string, init?: { headers?: Record<string, string> }) => {
        if (url.endsWith("/api/auth/refresh")) {
          refreshRequested();
          return Promise.resolve(response);
        }
        const authHeader = init?.headers?.["Authorization"];
        if (authHeader === "Bearer access-3") {
          return Promise.resolve(res(200, [{ id: "n1" }]));
        }
        return Promise.resolve(
          res(401, { error: { code: "UNAUTHENTICATED", message: "x" } }),
        );
      },
    );
    const client = new ApiClient(store, fetchMock as unknown as typeof fetch);

    const pending = client.listNodes();
    await refreshWasRequested; // refresh-1 was sent and its 200 has landed
    await jsonCalled; // refresh() saw refresh-1 still current and started parsing the body

    store.setTokens({
      access_token: "access-3",
      refresh_token: "refresh-3",
      token_type: "bearer",
    }); // another context's own refresh won the race and rotated the pair

    resolveJson({
      access_token: "access-2",
      refresh_token: "refresh-2",
      token_type: "bearer",
    });

    await expect(pending).resolves.toEqual([{ id: "n1" }]);
    expect(store.current()).toEqual({
      access: "access-3",
      refresh: "refresh-3",
    });
  });

  it("clears tokens on logout even when the request fails", async () => {
    const fetchMock = vi.fn(() =>
      Promise.resolve(
        res(500, { error: { code: "INTERNAL_ERROR", message: "x" } }),
      ),
    );
    const client = new ApiClient(store, fetchMock as unknown as typeof fetch);

    await expect(client.logout()).rejects.toBeInstanceOf(ApiError);
    expect(store.current()).toEqual({ access: null, refresh: null });
  });
});

// --- General file upload (FU-06, ADR 0026) --------------------------------

describe("uploadFile", () => {
  it("percent-encodes the destination, and does not send a guessed type", async () => {
    // `+` is the failure that would be invisible: a query-string reader decodes a
    // bare `+` as a space, so `a+b.txt` would silently become `a b.txt`
    // (measured: plan/15/07-open-measurements.md §2). encodeURIComponent sends %2B.
    const sent: { url?: string; headers: Record<string, string> } = {
      headers: {},
    };
    class FakeXHR {
      upload = { onprogress: null as unknown };
      status = 201;
      statusText = "Created";
      responseText = JSON.stringify({
        path: "docs/a+b.txt",
        size: 3,
        modified_at: "2026-08-03T00:00:00Z",
      });
      onload: (() => void) | null = null;
      onerror: (() => void) | null = null;
      onabort: (() => void) | null = null;
      open(_method: string, url: string) {
        sent.url = url;
      }
      setRequestHeader(key: string, value: string) {
        sent.headers[key] = value;
      }
      send() {
        this.onload?.();
      }
      abort() {}
    }
    const original = globalThis.XMLHttpRequest;
    (globalThis as { XMLHttpRequest: unknown }).XMLHttpRequest =
      FakeXHR as unknown as typeof XMLHttpRequest;
    try {
      const client = new ApiClient(makeStore("tok", "ref"));
      const result = await client.uploadFile(
        "s1",
        "docs",
        "a+b.txt",
        new Blob(["abc"]),
      );
      expect(result.path).toBe("docs/a+b.txt");
      expect(sent.url).toContain("directory=docs");
      expect(sent.url).toContain("filename=a%2Bb.txt");
      // Not the blob's own type: this path does not judge content type at all, and
      // sending a guess would invite someone to trust it.
      expect(sent.headers["Content-Type"]).toBe("application/octet-stream");
    } finally {
      (globalThis as { XMLHttpRequest: unknown }).XMLHttpRequest = original;
    }
  });
});
