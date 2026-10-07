import { createServer, request as proxyRequest } from "node:http";
import type { AddressInfo } from "node:net";
import { expect, test } from "@playwright/test";
import { mockCentral, SESSION_ID } from "./binary-preview.harness";

// Real console + xterm + native XHR; Central is deterministic and local.
// No backend sessions are created, so there is no API session to clean up.
for (const width of [1440, 390]) {
  test(`image storage wait, cancel, timeout and retry at ${width}`, async ({
    page,
    context,
  }) => {
    let mode = "hold";
    const timers = new Set<ReturnType<typeof setTimeout>>();
    const storage = createServer((request, response) => {
      if (!request.url?.endsWith("/files/images")) {
        const proxy = proxyRequest(
          new URL(
            request.url ?? "/",
            test.info().project.use.baseURL as string,
          ),
          { method: request.method, headers: request.headers },
          (upstream) => {
            response.writeHead(upstream.statusCode ?? 502, upstream.headers);
            upstream.pipe(response);
          },
        );
        proxy.on("error", () => {
          response.writeHead(502);
          response.end();
        });
        request.pipe(proxy);
        return;
      }
      request.resume();
      request.on("end", () => {
        const reply = () => {
          response.writeHead(201, {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
          });
          response.end(
            JSON.stringify({
              path: ".cliora/uploads/fixture.png",
              mime: "image/png",
              size: 8,
              modified_at: "2026-10-07T00:00:00Z",
            }),
          );
        };
        if (mode === "hold") {
          const timer = setTimeout(() => {
            timers.delete(timer);
            reply();
          }, 10000);
          timers.add(timer);
        } else reply();
      });
    });
    await new Promise<void>((resolve) =>
      storage.listen(0, "127.0.0.1", resolve),
    );
    const storageUrl = `http://127.0.0.1:${(storage.address() as AddressInfo).port}`;
    try {
      await page.setViewportSize({ width, height: 900 });
      await mockCentral(context, []);
      await context.route(
        (url) => url.pathname.startsWith("/api/"),
        async (route) => {
          const path = new URL(route.request().url()).pathname;
          if (path === `/api/sessions/${SESSION_ID}`)
            return route.fulfill({
              json: {
                id: SESSION_ID,
                node_id: "11111111-1111-1111-1111-111111111111",
                name: "upload fault fixture",
                runtime: "claude",
                workspace: "/srv/work/fixture",
                status: "running",
                rows: 24,
                columns: 80,
                capabilities: {
                  can_view: true,
                  can_write: true,
                  can_browse_files: true,
                  can_upload_files: true,
                },
              },
            });
          if (path.startsWith("/api/nodes/"))
            return route.fulfill({
              json: {
                id: "11111111-1111-1111-1111-111111111111",
                image_upload: true,
                runtimes: [],
              },
            });
          if (path.endsWith("/attach"))
            return route.fulfill({ json: { ticket: "fixture-ticket" } });
          return route.fallback();
        },
      );
      const inputs: Buffer[] = [];
      await context.routeWebSocket(
        `**/ws/sessions/${SESSION_ID}/terminal?*`,
        (ws) => {
          ws.send(
            JSON.stringify({
              type: "terminal.role",
              payload: { role: "writer" },
            }),
          );
          ws.onMessage((data) => {
            if (typeof data !== "string") inputs.push(Buffer.from(data));
          });
        },
      );
      // Keep the actual browser timeout path, shortening only its duration.
      await context.addInitScript(() => {
        const descriptor = Object.getOwnPropertyDescriptor(
          XMLHttpRequest.prototype,
          "timeout",
        )!;
        Object.defineProperty(XMLHttpRequest.prototype, "timeout", {
          ...descriptor,
          set(value: number) {
            descriptor.set!.call(this, value === 60000 ? 2500 : value);
          },
        });
      });
      // A local HTTP peer consumes the body and delays its response. Browser
      // route interception alone cannot reproduce native upload progress.
      await context.route(
        `**/api/sessions/${SESSION_ID}/files/images`,
        (route) => route.continue(),
      );

      await page.goto(`${storageUrl}/sessions/${SESSION_ID}`);
      await expect(
        page.getByRole("button", { name: "投放圖片", exact: true }),
      ).toBeEnabled();
      const pick = () =>
        page.locator('input[type="file"][accept^="image/png"]').setInputFiles({
          name: "shot.png",
          mimeType: "image/png",
          buffer: Buffer.from("89504e470d0a1a0a", "hex"),
        });
      await pick();
      await expect(page.locator(".drop-status")).toContainText(
        "等待節點儲存確認",
      );
      if (process.env.E2E_SHOT_DIR)
        await page.screenshot({
          path: `${process.env.E2E_SHOT_DIR}/pending-${width}.png`,
        });
      await page.getByRole("button", { name: "取消", exact: true }).click();
      await expect(
        page.getByRole("button", { name: "投放圖片", exact: true }),
      ).toBeEnabled();

      await expect(page.locator(".drop-bar")).not.toContainText("已加入");
      await pick();
      await expect(page.locator(".drop-status[role=alert]")).toContainText(
        "timed out",
      );
      await expect(
        page.getByRole("button", { name: "投放圖片", exact: true }),
      ).toBeEnabled();

      mode = "success";
      await pick();
      await expect(page.locator(".drop-bar")).toContainText("已加入");
      await expect
        .poll(() => Buffer.concat(inputs).toString())
        .toContain(".cliora/uploads/fixture.png ");
      if (process.env.E2E_SHOT_DIR)
        await page.screenshot({
          path: `${process.env.E2E_SHOT_DIR}/retry-${width}.png`,
        });
    } finally {
      timers.forEach((timer) => clearTimeout(timer));
      storage.closeAllConnections();
      await new Promise<void>((resolve) => storage.close(() => resolve()));
    }
  });
}
