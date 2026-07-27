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
