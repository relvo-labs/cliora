// The board's state lives in the URL (PX-31/PX-32, plan/26/09 §3, D103).
//
// Six things are shareable and one is not, and the split is the whole design:
//
//   view=   which saved view          shareable
//   f=      the temporary filter      shareable — "look at this filter" is a real
//                                     sentence people say to each other
//   q=      the search string         shareable, and **not** part of `f=`. Search is a
//                                     separate control on the server too, for the reason
//                                     `search_clause` gives: fifteen validated fields
//                                     plus one unconstrained one is not an allowlist
//   g=      grouping                  shareable
//   o=      sort                      shareable
//   task=   the open card             shareable, and survives a reload
//   density                           **localStorage** — a visual preference, and one
//                                     that must not travel to somebody else's screen
//
// **A quick filter writes `f=` and never the view** (D103). Chips that quietly rewrote a
// shared view would mean one person's scan changes what the whole team sees, with no undo.
// The toolbar says *modified* instead, and offers Save as / Revert.

export const MAX_FILTER_URL_LENGTH = 1500;

/** `?view=all` — **"no view", said out loud.**
 *
 *  An absent `view=` means "whatever this project's default is" (`plan/26/06` §2), which
 *  is what makes the first screen useful. But then "show me everything" has no
 *  representation: selecting 全部卡片 deleted the key and landed back on the default, so
 *  the option did nothing and the board could not be un-filtered at all. A sentinel is
 *  the smallest fix that keeps both sentences sayable, and it is a legible one — a
 *  colleague reading `?view=all` in a pasted link knows what it means. It cannot collide
 *  with a view id, which is always a uuid. */
export const NO_VIEW = "all";
const DENSITY_KEY = "cliora.work.density";
const FULL_SCREEN_KEY = "cliora.work.fullScreen";

export type Density = "comfortable" | "compact";

export interface ViewState {
  view: string | null;
  filter: Record<string, unknown> | null;
  search: string | null;
  group: string | null;
  order: string | null;
  task: string | null;
}

/** How long a search may be before the server refuses it. Mirrors
 *  `filters.MAX_SEARCH_LENGTH`; the input is capped here so a paste is trimmed rather
 *  than answered with a 400. */
export const MAX_SEARCH_LENGTH = 200;

function first(value: unknown): string | null {
  if (Array.isArray(value))
    return typeof value[0] === "string" ? value[0] : null;
  return typeof value === "string" && value.length > 0 ? value : null;
}

/** `base64url(json)` → object, or null when it is not decodable.
 *
 *  Null rather than a throw: a truncated or hand-edited URL should show the unfiltered
 *  board with a note, not an error page. The *server* refuses an undecodable filter,
 *  which is where a refusal belongs. */
export function decodeFilter(
  encoded: string | null,
): Record<string, unknown> | null {
  if (!encoded) return null;
  try {
    const padded = encoded + "=".repeat((4 - (encoded.length % 4)) % 4);
    const binary = atob(padded.replaceAll("-", "+").replaceAll("_", "/"));
    const bytes = Uint8Array.from(binary, (character) =>
      character.charCodeAt(0),
    );
    const value = JSON.parse(new TextDecoder().decode(bytes));
    return value !== null && typeof value === "object" && !Array.isArray(value)
      ? (value as Record<string, unknown>)
      : null;
  } catch {
    return null;
  }
}

export function encodeFilter(filter: Record<string, unknown>): string {
  const bytes = new TextEncoder().encode(JSON.stringify(filter));
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary)
    .replaceAll("+", "-")
    .replaceAll("/", "_")
    .replace(/=+$/, "");
}

export function readViewState(query: Record<string, unknown>): ViewState {
  return {
    view: first(query.view),
    filter: decodeFilter(first(query.f)),
    search: first(query.q),
    group: first(query.g),
    order: first(query.o),
    task: first(query.task),
  };
}

/** The query object for a state, dropping empty keys.
 *
 *  Empty keys are dropped rather than set to `""`: `?f=` and no `f` are different
 *  requests to the read model, and "no filter" is what an absent key means. */
export function writeViewState(
  state: Partial<ViewState>,
  existing: Record<string, unknown> = {},
): Record<string, string> {
  const query: Record<string, string> = {};
  for (const [key, value] of Object.entries(existing)) {
    const single = first(value);
    if (single !== null) query[key] = single;
  }
  const assign = (key: string, value: string | null) => {
    if (value === null || value === "") delete query[key];
    else query[key] = value;
  };
  if ("view" in state) assign("view", state.view ?? null);
  // Trimmed, and an all-whitespace search drops the key entirely: `?q=%20%20` and no `q`
  // must be the same board, or a stray space in a shared link changes what it shows.
  if ("search" in state) assign("q", (state.search ?? "").trim() || null);
  if ("group" in state) assign("g", state.group ?? null);
  if ("order" in state) assign("o", state.order ?? null);
  if ("task" in state) assign("task", state.task ?? null);
  if ("filter" in state) {
    const filter = state.filter;
    if (!filter || Object.keys(filter).length === 0) delete query.f;
    else {
      const encoded = encodeFilter(filter);
      // Past the limit the filter stays in the request and leaves the URL, and the
      // toolbar says so (D103). A link that silently carries less than it appears to is
      // worse than one that admits it.
      if (encoded.length <= MAX_FILTER_URL_LENGTH) query.f = encoded;
      else delete query.f;
    }
  }
  return query;
}

/** Whether the current filter differs from the saved view's.
 *
 *  Compared as sorted JSON, so key order cannot make an unmodified view look modified —
 *  the toolbar would then permanently offer "Revert" on a view nobody touched. */
export function isModified(
  current: Record<string, unknown> | null,
  saved: Record<string, unknown> | null,
): boolean {
  return stable(current) !== stable(saved);
}

function stable(value: unknown): string {
  return JSON.stringify(value ?? null, (_key, inner) => {
    if (inner === null || typeof inner !== "object" || Array.isArray(inner))
      return inner;
    const sorted: Record<string, unknown> = {};
    for (const key of Object.keys(inner as Record<string, unknown>).sort()) {
      sorted[key] = (inner as Record<string, unknown>)[key];
    }
    return sorted;
  });
}

/** Density is a personal preference, so it is local and **never audited** (plan/26/06 §3.3).
 *
 *  `PX-28` has a test asserting that changing it writes no audit row: auditing a
 *  preference turns the audit log into telemetry. */
export function readDensity(
  storage: Pick<Storage, "getItem"> = localStorage,
): Density {
  return storage.getItem(DENSITY_KEY) === "compact" ? "compact" : "comfortable";
}

export function writeDensity(
  density: Density,
  storage: Pick<Storage, "setItem"> = localStorage,
): void {
  storage.setItem(DENSITY_KEY, density);
}

/** Full screen is restored across reloads, and **not** through the URL (PX-36).
 *
 *  Local for the same reason density is: it is a property of *this screen*, not of the
 *  board being looked at. A shared link that forced the recipient's board into full screen
 *  would be one person's window preference arriving as somebody else's surprise — and
 *  unlike a filter, there is no sentence anybody says that means it.
 *
 *  Restored rather than reset because the reason people use it is a small laptop, and a
 *  preference that resets on every reload is a preference that has to be re-pressed all
 *  day. */
export function readFullScreen(
  storage: Pick<Storage, "getItem"> = localStorage,
): boolean {
  return storage.getItem(FULL_SCREEN_KEY) === "1";
}

export function writeFullScreen(
  value: boolean,
  storage: Pick<Storage, "setItem"> = localStorage,
): void {
  storage.setItem(FULL_SCREEN_KEY, value ? "1" : "0");
}
