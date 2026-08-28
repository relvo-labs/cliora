import { expect, type Page } from "@playwright/test";

// **One list of screens, two consumers** (`a11y.spec.ts` and `visual.spec.ts`).
//
// `plan/27/04` §2 and `/05` §3 both name eight screens and say they are deliberately the
// same eight. Two copies of that list would drift, and the drift would be silent: the
// a11y suite would be auditing a screen the visual suite no longer pins, and neither
// report would say so. So the list lives here and both import it.

export const USER = process.env.E2E_ADMIN_USER ?? "e2e-admin";
export const PASSWORD = process.env.E2E_ADMIN_PASSWORD ?? "e2e-admin-pw";
export const PROJECT = process.env.E2E_HD_PROJECT ?? "";

export interface Screen {
  /** Stable file name for the baseline and the axe report. Never change it casually:
   *  a renamed screen looks like a deleted baseline plus a new unreviewed one. */
  readonly id: string;
  readonly title: string;
  /** Built from the project id at run time. */
  readonly path: (project: string) => string;
  /** Waited on before the screenshot or the scan. Without it both suites race the
   *  skeleton loader and produce a picture of a spinner — which is stable, so it
   *  passes for ever. */
  readonly ready: (page: Page) => Promise<unknown>;
}

const railVisible = (page: Page) =>
  expect(page.locator('nav[aria-label="Primary"]')).toBeVisible();

export const SCREENS: readonly Screen[] = [
  {
    id: "active-board",
    title: "Active Board",
    path: (p) => `/projects/${p}/work`,
    ready: railVisible,
  },
  {
    id: "backlog",
    title: "Backlog",
    path: (p) => `/projects/${p}/work?layout=list`,
    ready: railVisible,
  },
  {
    id: "drawer-waiting",
    title: "Drawer — waiting for input",
    path: (p) => `/projects/${p}/work?task=__WAITING__`,
    ready: railVisible,
  },
  {
    id: "drawer-no-runner",
    title: "Drawer — no eligible runner",
    path: (p) => `/projects/${p}/work?task=__NO_RUNNER__`,
    ready: railVisible,
  },
  {
    id: "drawer-blocked",
    title: "Drawer — blocked by dependency",
    path: (p) => `/projects/${p}/work?task=__BLOCKED__`,
    ready: railVisible,
  },
  {
    id: "my-work",
    title: "My Work",
    path: () => "/my-work",
    ready: railVisible,
  },
  {
    id: "project-overview",
    title: "Project Overview",
    path: (p) => `/projects/${p}/overview`,
    ready: railVisible,
  },
  {
    id: "home",
    title: "Home (fleet health)",
    path: () => "/",
    ready: railVisible,
  },
];

export async function signIn(page: Page): Promise<void> {
  await page.goto("/login");
  await page.locator('input[name="username"]').fill(USER);
  await page.locator('input[name="password"]').fill(PASSWORD);
  await page.getByRole("button", { name: /sign in/i }).click();
  // The rail, not a URL — `plan/26` moved the landing route once already and the two
  // specs that asserted a URL went stale silently.
  await expect(page.locator('nav[aria-label="Primary"]')).toBeVisible();
}

/** Resolve the three `__PLACEHOLDER__` task ids from the seeded project.
 *
 *  The three drawer screens are worth pinning precisely because each shows a *different*
 *  reason a card is stuck; picking them by index would silently follow whatever the seed
 *  happened to order first.
 *
 *  **Reads the token out of `localStorage`.** `page.request` is a separate context from
 *  the page and carries no Authorization header of its own, and the app keeps its access
 *  token in `localStorage` (ADR 0006/0007) rather than in a cookie — so the obvious
 *  `page.request.get(...)` returns 401 and this function returns nothing. It did exactly
 *  that on the first run, and **nothing failed**: `withTasks` left the placeholders in
 *  the URL, the router ignored `?task=__WAITING__`, and axe scanned the board three
 *  times and reported it clean. `assertResolved` below is what makes that loud. */
export async function resolveDrawerTasks(
  page: Page,
  project: string,
): Promise<Record<string, string>> {
  const token = await page.evaluate(() =>
    window.localStorage.getItem("cliora.access_token"),
  );
  const response = await page.request.get(
    // `limit=100` is `MAX_LIMIT` (`services/work/items.py`); 200 is a 422, which the
    // guard above reports as "the drawer screens would be the board again" rather than
    // as a validation error — the message names the consequence, not the parameter.
    `/api/projects/${project}/work-items?limit=100`,
    { headers: token ? { Authorization: `Bearer ${token}` } : {} },
  );
  if (!response.ok()) {
    throw new Error(
      `work-items returned ${response.status()} while resolving the drawer cards; ` +
        `without them three of the eight screens are the board again`,
    );
  }
  const body = await response.json();
  const items = (body.groups ?? []).flatMap(
    (group: { items?: unknown[] }) => group.items ?? [],
  ) as Array<{ id: string; primary_attention?: string }>;
  const byAttention = (attention: string) =>
    items.find((item) => item.primary_attention === attention)?.id ?? "";
  return {
    __WAITING__: byAttention("waiting_for_your_input"),
    __NO_RUNNER__: byAttention("no_eligible_runner"),
    __BLOCKED__: byAttention("dependency_blocked"),
  };
}

export function withTasks(path: string, tasks: Record<string, string>): string {
  return Object.entries(tasks).reduce(
    (acc, [key, value]) => acc.replace(key, value),
    path,
  );
}

/** Fail loudly when a placeholder survived substitution.
 *
 *  **This is the assertion that the first run of this suite needed and did not have.**
 *  An unsubstituted `__WAITING__` produces a URL the router quietly drops, so the screen
 *  renders as the plain board — a valid page, which passes every check that follows. The
 *  suite then reports eight screens audited when it audited six, and the two reports are
 *  indistinguishable.
 *
 *  A screen that cannot be reached is a failure, never a skip: a skip here would restore
 *  exactly the silence this replaces. */
export function assertResolved(id: string, url: string): void {
  const leftover = url.match(/__[A-Z_]+__/);
  if (leftover) {
    throw new Error(
      `${id}: ${leftover[0]} was not substituted — the seeded project has no card with ` +
        `that attention level, so this screen would silently be the board. ` +
        `Re-seed with scripts/px/seed-attention-demo.py.`,
    );
  }
}
