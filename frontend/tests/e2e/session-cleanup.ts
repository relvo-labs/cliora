import { expect, type APIRequestContext, type Page } from "@playwright/test";

// Every session a full-stack test creates is ended after it, pass or fail.
//
// The node's session cap (`sessions_per_node_max`, 10 by default, shells
// included) is shared by every worker and both browser projects. A test that
// stops half-way leaves its session running, and once enough have leaked every
// later create is refused with "This node has reached its session limit" —
// which surfaces as an unrelated failure somewhere else in the run.
//
// Ids come from the page's own successful create responses — `POST
// /api/sessions` and `POST /api/sessions/{id}/shell`, both 201 with the new
// session as the body (#116). Not from the URLs the page visits: a visit
// proves nothing about ownership, so admin cleanup could end a session the
// test merely opened, and a create whose navigation failed was never visited
// and leaked. The body is read the moment the response arrives, and cleanup
// waits for every read still in flight, so a reload later in the test cannot
// cost an id.

const CREATE_PATH = /^\/api\/sessions(?:\/[0-9a-f-]{36}\/shell)?$/;

interface Tracking {
  /** Body reads still in flight. */
  pending: Set<Promise<void>>;
  /** Creates whose body could not be read: sessions cleanup cannot name. */
  unreadable: string[];
}

// Keyed by the returned list, so the public shape stays `string[]` and every
// caller keeps passing that list straight back to `terminateSessions`.
const tracking = new WeakMap<string[], Tracking>();

/** Start recording the sessions this page creates; returns the live list. */
export function trackSessions(page: Page): string[] {
  const ids: string[] = [];
  const state: Tracking = { pending: new Set(), unreadable: [] };
  tracking.set(ids, state);
  page.on("response", (response) => {
    if (response.request().method() !== "POST") return;
    if (response.status() !== 201) return;
    if (!CREATE_PATH.test(new URL(response.url()).pathname)) return;
    const read: Promise<void> = response
      .json()
      .then((body: { id?: unknown }) => {
        if (typeof body.id === "string" && !ids.includes(body.id))
          ids.push(body.id);
      })
      .catch((error: unknown) => {
        // A create the cleanup cannot name is a leak. Say so in the cleanup
        // rather than letting the session cap fail some later test.
        state.unreadable.push(`${response.url()}: ${String(error)}`);
      })
      .finally(() => state.pending.delete(read));
    state.pending.add(read);
  });
  return ids;
}

/**
 * End each session through the API. A fresh sign-in rather than the page's
 * token, because the test may have signed out. Ending one that the test already
 * ended is the expected 409. Every id is attempted before anything is reported,
 * so one bad terminate cannot leave the rest running; then any failure fails
 * the cleanup loudly.
 */
export async function terminateSessions(
  request: APIRequestContext,
  ids: string[],
  credentials: { username: string; password: string },
): Promise<void> {
  const state = tracking.get(ids);
  if (state) await Promise.all([...state.pending]);
  const problems = (state?.unreadable ?? []).map(
    (detail) => `create response unreadable, session may leak: ${detail}`,
  );
  if (ids.length > 0) {
    const login = await request.post("/api/auth/login", { data: credentials });
    expect(login.ok(), `cleanup sign-in: ${login.status()}`).toBe(true);
    const token = (await login.json()).tokens.access_token as string;
    for (const id of ids) {
      try {
        const res = await request.post(`/api/sessions/${id}/terminate`, {
          headers: { authorization: `Bearer ${token}` },
        });
        if (res.status() === 409) {
          const body = await res.json();
          if (body.error?.code !== "SESSION_INVALID_STATE")
            problems.push(`terminate ${id}: 409 ${body.error?.code}`);
        } else if (res.status() !== 200) {
          problems.push(`terminate ${id}: ${res.status()}`);
        }
      } catch (error) {
        problems.push(`terminate ${id}: ${String(error)}`);
      }
    }
  }
  expect(problems, "session cleanup").toEqual([]);
}
