import { describe, expect, it, vi } from "vitest";

import { ApiClient, type TokenStore } from "./client";

// Both HTTP entry points propagate capacity failures without refreshing credentials
// or fabricating a ticket; the terminal's existing retry schedule handles recovery.
describe.each(["generic", "attach"])("%s ticket capacity", (endpoint) => {
  it.each([
    [429, "WS_TICKET_BUSY"],
    [503, "INTERNAL_ERROR"],
  ])(
    "preserves the %s error and the signed-in identity",
    async (status, code) => {
      const store: TokenStore = {
        accessToken: () => "access",
        refreshToken: () => "refresh",
        setTokens: vi.fn(),
        clear: vi.fn(),
      };
      const fetchMock = vi.fn(
        async () =>
          new Response(
            JSON.stringify({
              error: { code, message: "Please retry later" },
              request_id: "capacity-request",
            }),
            { status },
          ),
      );
      const client = new ApiClient(store, fetchMock);
      const pending =
        endpoint === "generic"
          ? client.wsTicket("session:sid")
          : client.attachSession("sid");
      await expect(pending).rejects.toMatchObject({
        code,
        status,
        message: "Please retry later",
        requestId: "capacity-request",
      });
      expect(fetchMock).toHaveBeenCalledTimes(1);
      expect(store.setTokens).not.toHaveBeenCalled();
      expect(store.clear).not.toHaveBeenCalled();
    },
  );
});
