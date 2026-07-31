# plan/09 report — Layout height and the centre workspace

Date: 2026-07-31 · Plan: `plan/09/` · Tickets: `LY-01` – `LY-08`

## Verdict

**Go.** The reported symptom — "the CLI is only half height, hard to read and hard to
type into" — was literal: the terminal occupied **50.6 %** of its pane at 1440×900,
and did so at *every* window size. It is now **99.9 %**, 24 rows became 49, and the
Session Workspace no longer has the 16 px page scrollbar it has always had. No new
data-plane surface, no protocol change, no RBAC change: eight files of CSS and one
composable accessor.

One exit condition is **not** closed on this host and is CI-gated: the measuring
Playwright test needs the full stack (Central + PostgreSQL + tmux + an online node),
which this environment does not have. What was measured here instead — with the real
Chromium against a mocked REST surface — is reported below with the method stated, so
the numbers can be told apart from the assertions that will guard them.

## What was wrong

Three panels sized themselves with a CSS grid row template plus auto-placement, which
means **the number and order of children decided which one got the `1fr`**:

| | Template | Children | Result |
|---|---|---|---|
| `.terminal-pane` (CLI) | `auto minmax(0,1fr) auto` | 1 (the host) | Host landed in the leading `auto` row |
| `.terminal-pane` (TERMINAL) | same | 3 (notice, host, status) | Correct — by coincidence of the count |
| `.preview` | `auto auto 1fr` | 2 or 3 (`.meta` is `v-if`) | Monaco's container collapsed whenever the meta line was absent |
| `.tree-panel` | `auto auto auto 1fr` | exactly 4 | Correct — and one added line of copy away from breaking |

The CLI case then **stabilised itself**, which is why no amount of resizing helped:

1. xterm is constructed without `rows`, so it defaults to 24.
2. At mount the host is empty and measures 0, and `fitSafely()` correctly refuses to
   measure a hidden container — 24 rows stands.
3. xterm renders 24 rows, so the `auto` row grows to exactly 24 rows tall.
4. The ResizeObserver fires, FitAddon measures the host — and the host is now exactly
   the size of the terminal inside it. It proposes 24 rows.
5. Go to 3.

Separately, the page had **two competing height formulas**: `AppLayout`'s implicit
`100vh − 56 − 24 − 40` and `SessionWorkspaceView`'s explicit `100vh − 56 − 48`. The
16 px difference was the page scrollbar. The root cause was not arithmetic — it was
that `main`'s height was implicit, so any view that wanted to fill it had to re-derive
it.

## What shipped

| | |
|---|---|
| LY-01 | The app shell is a viewport-height grid; the header and rail are no longer `position: fixed`; `main` is the one scrolling container and has a *definite* height. New `AppLayout.test.ts` pins the structural contract the grid depends on |
| LY-02 | `AppLayout` gained `fill` (`main[data-fill]`): `overflow: hidden` and `12px 16px` padding for a page that is itself a fixed layout. `SessionWorkspaceView`'s `calc(100vh …)` is gone — it is now `height: 100%` |
| LY-03 | All three panels are flex columns: only the host/body/tree grows, and no conditional sibling can change that. Pure CSS — no template or script touched |
| LY-04 | `useTerminalSession.proposeSize()`; the system terminal is created at the panel's real size instead of a hardcoded 24×80, clamped to the wire contract's own 2–300 / 2–500 bounds |
| LY-05 | `--layout-sidebar` 280 → 208 px; `research/style.md` §9/§12/§22 synced, including the pre-existing Inspector 360-vs-300 drift |
| LY-06 | A measuring Playwright test (nine assertions at 1440×900, four at 1000×800) plus three text gates in `scripts/ly/layout-gates.sh`, called by both `ci.yml` and the evidence pack |
| LY-07 | `FR-TERM-001.AC-13` / `AC-14` in the PRD, registered with four primary links each; pinned coverage 379/248 → **381/250** |
| LY-08 | `scripts/ly/evidence.sh`, this report, `plan/09/05-implementation-status.md` |

## Measured, before and after

Chromium 149 (Playwright), Vite dev server, REST mocked, `#panel-cli` at 1440×900.
The "before" column is the same harness run against a stashed working tree.

| | Before | After | Predicted in `plan/09/00` §4 |
|---|---|---|---|
| Rail width | 279 | 207 | 280 → 208 (1 px is the border) |
| Centre pane width | 792 | **888** | 792 → 888 ✅ exact |
| Centre pane height | 712 | **736** | ≈712 → ≈736 ✅ |
| CLI host height | **360** | **736** | — |
| xterm screen ÷ pane | **0.506** | **0.999** | — |
| CLI rows | **24** | **49** | ≈43 (cell height is 15 px, not the 17 assumed) |
| Preview body ÷ pane | 0.235 | 0.963 | — |
| Page vertical overflow | **16 px** | **0** | 16 → 0 ✅ exact |
| 1000×800 rows | 24 | 39 | — |

The width and page-overflow predictions were exact; the row count was under-predicted
because the plan assumed a 17 px cell. The interesting number is not any of the
dimensions — it is **0.506 → 0.999**.

## Evidence

| What | How | Result |
|---|---|---|
| Frontend format / lint / typecheck / build | `npm run …` | pass |
| Frontend unit | `npm run test:unit -- --run` | **343 passed** (333 + 4 AppLayout + 4 `proposeSize` + 2 shell size) |
| Three layout gates | `scripts/ly/layout-gates.sh` | pass; and **all three fail on a reverted tree** (verified by stashing LY-03/LY-05: `must be a flex column`, `a view re-derived the page height`, `tokens.css says 280px … style.md says 208`) |
| Traceability | `python -m scripts.traceability.cli validate --level static/selectors`, `coverage --scope all --strict`, `coverage --baseline`, `pytest scripts/traceability/tests` | pass; `criteria=381 verifiable=250 covered-by-parent=131 needs-rewrite=0 blocking=0`; 32 tests |
| The verified_by selector resolves | deliberately corrupted the test name | `selector.unresolved` — the gate has teeth |
| Six other routes still scroll | Chromium, mocked REST, `main.scrollTop = scrollHeight` | `/audit` scrolls 2876 px and `/nodes` 1360 px **inside main**, header stays at `top: 0`, no page-level scroll on any of the six |
| The 900 px breakpoint | 860×700 | rail 63 px, labels hidden, `main` starts at x=64, no horizontal overflow |
| Evidence pack | `scripts/ly/evidence.sh` | 8 executed / 0 failed, 3 skipped (see below) |

`make traceability` was run through the project venv directly
(`backend/.venv/bin/python -m scripts.traceability.cli …`) because this host has no
`uv`; the evidence pack records that as a skip rather than a pass.

## Deliberate gaps

* **The measuring Playwright test has not been executed.** It needs `E2E_FULL_STACK`
  (Central, PostgreSQL, tmux, an online node); this host has none of them. Its
  assertions were chosen from the before/after numbers above, so they are known to
  separate the two states — 0.506 fails `≥ 0.9`, 24 fails `≥ 30`, 16 px fails `≤ 1` —
  but "the assertions discriminate" is not the same claim as "the test ran". CI's
  `wt.yml` browser leg runs the whole spec on Chromium, Firefox and WebKit.
* **WebKit** cannot launch here at all (its system libraries need root). CI only —
  same standing gap as plan/08.
* **No sidebar collapse toggle, no drag handles, no Status Bar.** Non-goals; `§2` of
  `plan/09/00-execution-plan.md` says why.
* **`research/style.md` still specifies Inter / JetBrains Mono** while the app ships a
  system stack (ADR 0016). Recorded, not fixed — it is a font question, not a layout
  one.

## What this phase found

**A test suite can be entirely green while the main working surface is half usable.**
343 unit tests could not see this, because jsdom has no layout. The one existing
layout test — added by plan/08 for exactly this class of bug — measured
`scrollWidth` only. The defect lived in the axis nobody had asserted, and it survived
three phases there.

The correction is not "add a test". It is that a *panel* is now forbidden from
deriving its height from its children, and a *page* is forbidden from deriving its
height from the viewport, and both prohibitions run on every push without a browser.
The browser test proves the geometry; the text gates make the specific mistake
unrepeatable.
