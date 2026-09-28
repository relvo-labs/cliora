import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import type { BrowserContext, Page, Route } from "@playwright/test";

// Shared by the binary-preview specs (plan/31/05 BP-07 §4).
//
// WHAT THIS IS: the real console bundle, in a real browser, under the real
// Content-Security-Policy string from deploy/nginx/nginx.conf, against a
// deterministic stand-in for Central. It exercises the renderer — PDF.js, the
// canvas, the lifecycle, the CSP — end to end. It does NOT exercise the daemon's
// sniffing or Central's gates; those have their own tests (BP-03/BP-04), and the
// full-stack matrix is BP-09's (`E2E_FULL_STACK=1`).
//
// The fixtures are generated into a temporary directory by
// scripts/p31/gen_preview_fixtures.py, never committed as binaries.

const REPO = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");

/** The production CSP, read from the file nginx serves it from. */
export function productionCsp(): string {
  const conf = readFileSync(join(REPO, "deploy/nginx/nginx.conf"), "utf8");
  const match = /add_header Content-Security-Policy "([^"]+)" always;/.exec(
    conf,
  );
  if (!match) throw new Error("no CSP in deploy/nginx/nginx.conf");
  return match[1];
}

export interface Fixtures {
  dir: string;
  read(name: string): Buffer;
  cleanup(): void;
}

export function generateFixtures(): Fixtures {
  const dir = mkdtempSync(
    join(process.env.E2E_FIXTURE_TMP ?? tmpdir(), "bp-fx-"),
  );
  execFileSync(
    "python3",
    [join(REPO, "scripts/p31/gen_preview_fixtures.py"), dir],
    {
      stdio: "ignore",
    },
  );
  return {
    dir,
    read: (name) => readFileSync(join(dir, name)),
    cleanup: () => rmSync(dir, { recursive: true, force: true }),
  };
}

export const SESSION_ID = "44444444-4444-4444-8444-444444444444";
const NODE_ID = "11111111-1111-1111-1111-111111111111";

export interface PreviewFile {
  name: string;
  /** Workspace-relative path the tree lists it under. */
  path: string;
  /** What Central answers for it: bytes with the daemon's verdict, or a refusal. */
  answer:
    | {
        mime: string;
        kind: "image" | "pdf";
        width?: number;
        height?: number;
        bytes: Buffer;
      }
    | { status: number; code: string; details?: Record<string, unknown> };
}

export interface MockCentral {
  /** Every request the page (and its workers) made, by URL. */
  requests: string[];
  /** Bodies of the binary-preview POSTs. */
  previewBodies: string[];
}

function json(route: Route, status: number, body: unknown) {
  return route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

/**
 * Stand in for Central: a signed-in Viewer, one running CLI session with
 * `can_preview_binary`, one workspace folder holding `files`, and the binary
 * preview endpoint answering with the ADR 0029 §6 header set. Every non-API
 * response gets the production CSP header, as nginx's server-level
 * `add_header` gives it to every static asset — the worker script included.
 */
export async function mockCentral(
  context: BrowserContext,
  files: PreviewFile[],
  options: { canPreviewBinary?: boolean } = {},
): Promise<MockCentral> {
  const csp = productionCsp();
  const state: MockCentral = { requests: [], previewBodies: [] };
  await context.addInitScript(() => {
    localStorage.setItem("cliora.access_token", "e2e-access");
    localStorage.setItem("cliora.refresh_token", "e2e-refresh");
    // Count CSP violations from the first script onwards.
    const w = window as unknown as { __csp: string[] };
    w.__csp = [];
    document.addEventListener("securitypolicyviolation", (event) => {
      w.__csp.push(`${event.violatedDirective} ${event.blockedURI}`);
    });
  });
  context.on("request", (request) => state.requests.push(request.url()));

  await context.route(
    (url) =>
      !url.pathname.startsWith("/api/") && !url.pathname.startsWith("/ws/"),
    async (route) => {
      const response = await route.fetch();
      await route.fulfill({
        response,
        headers: { ...response.headers(), "content-security-policy": csp },
      });
    },
  );

  await context.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    if (path === "/api/auth/me") {
      return json(route, 200, {
        id: "22222222-2222-2222-2222-222222222222",
        username: "viewer",
        display_name: "Viewer",
        role: "Viewer",
        permissions: ["session.view", "file.browse"],
      });
    }
    if (path === `/api/sessions/${SESSION_ID}` && request.method() === "GET") {
      return json(route, 200, {
        id: SESSION_ID,
        node_id: NODE_ID,
        user_id: "33333333-3333-3333-3333-333333333333",
        name: "e2e-preview",
        runtime: "claude",
        workspace: "/srv/work/e2e",
        status: "running",
        rows: 24,
        columns: 80,
        pid: 1,
        started_at: "2026-09-28T00:00:00Z",
        last_activity_at: "2026-09-28T00:00:00Z",
        ended_at: null,
        created_at: "2026-09-28T00:00:00Z",
        exit_code: null,
        error_message: null,
        capabilities: {
          can_view: true,
          can_write: false,
          can_takeover: false,
          can_terminate: false,
          can_browse_files: true,
          can_upload_files: false,
          can_open_shell: false,
          can_preview_binary: options.canPreviewBinary ?? true,
        },
      });
    }
    if (path === `/api/sessions/${SESSION_ID}/files/tree`) {
      const dir = url.searchParams.get("path") ?? ".";
      const entries = files
        .filter(
          (f) =>
            (f.path.includes("/")
              ? f.path.split("/").slice(0, -1).join("/")
              : ".") === dir,
        )
        .map((f) => ({
          name: f.name,
          rel_path: f.path,
          type: "file",
          size: "bytes" in f.answer ? f.answer.bytes.length : 1,
          modified_at: "2026-09-28T00:00:00Z",
          hidden: false,
          symlink: false,
          excluded: false,
          expandable: false,
        }));
      return json(route, 200, { path: dir, truncated: false, entries });
    }
    if (path === `/api/sessions/${SESSION_ID}/files/binary-preview`) {
      const body = request.postData() ?? "";
      state.previewBodies.push(body);
      const wanted = (JSON.parse(body) as { path: string }).path;
      const file = files.find((f) => f.path === wanted);
      if (!file)
        return json(route, 404, {
          error: { code: "FILE_NOT_FOUND", message: "x" },
        });
      const answer = file.answer;
      if ("status" in answer) {
        return json(route, answer.status, {
          error: {
            code: answer.code,
            message: "refused",
            details: answer.details ?? {},
          },
          request_id: "e2e",
        });
      }
      const headers: Record<string, string> = {
        "content-type": "application/octet-stream",
        "x-content-type-options": "nosniff",
        "cache-control": "no-store, private",
        vary: "Authorization",
        "cross-origin-resource-policy": "same-origin",
        "content-security-policy": "sandbox; default-src 'none'",
        "x-cliora-preview-mime": answer.mime,
        "x-cliora-preview-kind": answer.kind,
      };
      if (answer.width)
        headers["x-cliora-preview-width"] = String(answer.width);
      if (answer.height)
        headers["x-cliora-preview-height"] = String(answer.height);
      return route.fulfill({ status: 200, headers, body: answer.bytes });
    }
    if (path === `/api/sessions/${SESSION_ID}/files/content`) {
      const rel = url.searchParams.get("path") ?? "";
      return json(route, 200, {
        success: false,
        rel_path: rel,
        size: 1,
        mime: "application/octet-stream",
        error: { code: "FILE_BINARY", reason: "binary" },
      });
    }
    // The terminal is not under test: refusing the ticket keeps it from opening
    // a socket. Everything else this page might ask for is simply absent.
    return json(route, path.endsWith("/attach") ? 403 : 404, {
      error: { code: "NOT_FOUND", message: "not in this stand-in" },
    });
  });
  return state;
}

/** Open the workspace and, on a phone, the files mode. */
export async function openWorkspace(
  page: Page,
  narrow: boolean,
): Promise<void> {
  await page.goto(`/sessions/${SESSION_ID}`);
  if (narrow) {
    await page.getByRole("tab", { name: "檔案" }).click();
  }
}

/** Activate a file by name in whichever browser the width shows. */
export async function openFile(
  page: Page,
  name: string,
  narrow: boolean,
): Promise<void> {
  if (narrow) {
    await page.locator("#file-panel .entry", { hasText: name }).click();
  } else {
    await page.getByRole("treeitem", { name: new RegExp(`^${name},`) }).click();
  }
}

export async function cspViolations(page: Page): Promise<string[]> {
  return page.evaluate(
    () => (window as unknown as { __csp: string[] }).__csp ?? [],
  );
}
