import { expect, type APIRequestContext, type Page } from "@playwright/test";

// Every session a full-stack test creates is ended after it, pass or fail.
//
// The node's session cap (`sessions_per_node_max`, 10 by default, shells
// included) is shared by every worker and both browser projects. A test that
// stops half-way leaves its session running, and once enough have leaked every
// later create is refused with "This node has reached its session limit" —
// which surfaces as an unrelated failure somewhere else in the run.
//
// Ids are read from the workspace URL a create lands on, not from the create
// response: reading a response body from a listener races a reload in the
// test itself, and the URL is where every create flow ends up anyway.

const SESSION_URL = /\/sessions\/([0-9a-f-]{36})$/;

/** Start recording the sessions this page opens; returns the live list. */
export function trackSessions(page: Page): string[] {
  const ids: string[] = [];
  page.on("framenavigated", (frame) => {
    if (frame !== page.mainFrame()) return;
    const match = SESSION_URL.exec(new URL(frame.url()).pathname);
    if (match && !ids.includes(match[1])) ids.push(match[1]);
  });
  return ids;
}

/**
 * End each session through the API. A fresh sign-in rather than the page's
 * token, because the test may have signed out. Ending one that the test already
 * ended is the expected 409, and anything else fails the cleanup loudly.
 */
export async function terminateSessions(
  request: APIRequestContext,
  ids: string[],
  credentials: { username: string; password: string },
): Promise<void> {
  if (ids.length === 0) return;
  const login = await request.post("/api/auth/login", { data: credentials });
  expect(login.ok(), `cleanup sign-in: ${login.status()}`).toBe(true);
  const token = (await login.json()).tokens.access_token as string;
  for (const id of ids) {
    const res = await request.post(`/api/sessions/${id}/terminate`, {
      headers: { authorization: `Bearer ${token}` },
    });
    if (res.status() === 409) {
      const body = await res.json();
      expect(body.error?.code, `terminate ${id}`).toBe("SESSION_INVALID_STATE");
    } else {
      expect(res.status(), `terminate ${id}`).toBe(200);
    }
  }
}
