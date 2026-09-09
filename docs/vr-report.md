# plan/28 — visual refresh: what shipped and what it cost

- Date: 2026-09-08
- Plan: `plan/28/`
- ADR: 0027 (accepted); amends ADR 0005's Naive UI clause
- Requirements: `NFR-006` (new, 8 criteria), `FR-TERM-001.AC-15/AC-16`,
  `FR-TERM-005.AC-06`
- Gates added: `GATE-VR-NO-LITERAL-COLOR`, `GATE-VR-NO-LEGACY-TOKEN`,
  `GATE-VR-NO-GLYPH-ICON`, `GATE-VR-THEME-CONTRACT`
- Evidence: `artifacts/vr/local/` (13 legs green, 7 named skips)
- Security review: `docs/security-review-p28.md` (no finding)

## What this phase actually was

The five style documents in `docs/design/visual-refresh/` each end with the same
sentence: "this document does not claim browser acceptance". The shared
foundation's integration checklist step 3 is "bring the tokens and the showcase
components into Vue". This phase is that step, and steps 4 and 5 after it.

Three things had to be admitted before any of it could start.

**The colours were not one system.** They were four: 27 CSS custom properties
with a single light set and no theme dimension; 69 literal values across 13
files; xterm's own four hard-coded colours plus xterm's default ANSI palette;
and Monaco's own ten. Switching themes was never "change some variables" — it
was first collecting the other three back into the first.

**Five legibility failures had already shipped, and they were measurable.**
Not "a bit pale" — measured sRGB ratios:

| Pair | Where | Measured | Target |
|---|---|---:|---|
| `--border-focus` / panel | every keyboard focus ring in the app | **2.85** | 3.0 |
| `--text-inverse` / `--status-error` | the Terminate confirm button | **4.09** | 4.5 |
| `--border-default` / panel | every input and secondary button border | **1.37** | 3.0 |
| `online` badge | `StatusBadge.vue:44` | **3.13** | 4.5 |
| `degraded` badge | `StatusBadge.vue:48` | **2.63** | 4.5 |

Six of the eight badge pairs were under 4.5:1. None of them was waived. The
traceability set held 115 requirements and **not one** was about legibility,
keyboard operation or visual theming, so there was nothing that could go red.
That is the gap `NFR-006` closes, and it is the most durable thing this phase
delivered: the next failure of this kind is a red gate rather than an invisible
one.

**The design documents themselves were wrong in two places.** Their contrast
tables verified three pairs each and omitted the selected state of navigation
and tabs — accent text on the accent tint — which fails in Porcelain (4.13) and
Studio (3.37). And their third row, "prototype primary button text /
accent.primary", was computed using `surface.canvas` as the button's text colour,
on a page that says two paragraphs below "do not derive every button text colour
from the canvas". Both are corrected in all five documents, with the measured
values in place.

## What shipped

Two themes: **Graphite** (dark, default) and **Porcelain** (light). Dark is the
default because of what is already on screen rather than taste — the terminal
and the editor are dark, and a light frame draws a high-contrast edge around the
one region the user is looking at. Porcelain shipped in the same release because
only a light theme exposes the hard part: a dark terminal inside a light frame
needs its own text colour, and a dark-only delivery would have omitted that whole
dimension of the table without noticing.

Midnight, Studio and Industrial have values in the table and pass every test.
They are **not** offered in the switcher, have no layout variant, and have no
acceptance screens. Passing arithmetic is not the same as having been looked at.

- **44 colour tokens per theme**, five themes, one table generated into two files
  bound by `theme.contract.test.ts` — 220 measured pairs, all passing, every
  ratio printed rather than summarised.
- **11 new shared components** plus `useFocusTrap` and `useToast`; `StatusBadge`
  and `ConfirmDialog` rewritten; `AsyncState` split and deleted.
- **The status bar exists.** Specified in `style.md` §9 since P0, never built —
  `tokens.css` even carried a `--layout-status` token commented "Not in use".
- **Zero literal colours** under `frontend/src` outside the two theme files, and
  a gate that keeps it that way.
- **22 packages left the supply chain** with `naive-ui`.

## What it cost, stated plainly

**The terminal is shorter.** A 28px status bar, a fixed 44px tab strip, a taller
work header and a 13px → 14px font change. Measured in chromium at the gate
geometry (1440×900, a 674px CLI panel):

| font / line-height | cell | rows | |
|---|---:|---:|---|
| 13 / 1.0 (what shipped before) | 15px | **44** | |
| **14 / 1.2 (shipped now)** | **19px** | **35** | 5 rows of headroom over plan/09's floor of 30 |
| 14 / 1.4 | 22px | 30 | exactly on the line; not chosen |
| 14 / 1.6 (what the design documents said) | 25px | **26** | under the floor |

The design documents' "line-height 1.6" is a UI body-copy convention; xterm's
`lineHeight` multiplies the measured cell height. Taking it literally would have
cost 18 rows and broken the gate plan/09 spent a whole phase earning. All five
documents were revised.

At **1024×768** the panel is 542px and 14px/1.2 gives only **28** rows. plan/09
sets no floor there, but it is a real finding: the work header collapses to one
row at that width (recovering about one row) and the rest is the user-adjustable
font size — 13px/1.2 gives 30. **This is why the font-size control exists**, and
it is why the release note tells people about it rather than leaving it to be
found.

**Two other honest costs.** Colour lives in two files that could drift, and
`theme.contract.test.ts` is the fuse — three drift modes were each verified to go
red. And `public/theme-boot.js` is an unbundled script, kept to 9 lines with a
gate on its size and contents, because the CSP is `script-src 'self'` and an
inline bootstrap would be silently blocked.

**Preferences do not follow the user between machines.** Theme, nav collapse,
terminal font size and file-panel width are in `localStorage`. No preferences
API was added: a visual refresh has no reason to touch the authorization surface,
and "add a column while we're here" is how a display setting acquires an audit
question. Cross-device sync is a separate ticket, and the right question there is
"do preferences enter the audit log", not "shall we add a field".

## Six places the implementation differs from the plan

Every one is a measurement that disagreed with a proposal, which is what
"contrast is measured, not claimed" is supposed to produce. Full detail with the
numbers is in `plan/28/07-implementation-status.md`.

1. **The status pill's outline target was wrong.** The plan filed it under the
   3:1 non-text rule and no theme reaches it (1.30–1.70). The outline carries no
   meaning — the label does, at ≥ 4.5:1 — so the target was corrected in the
   open, to "the outline must be the strongest edge the pill has". This is the
   second place this phase reduces a target; the first is the ANSI dim colours.
2. **`border.control` needed a third surface.** Dialogs and menus are
   `surface.raised` and they contain inputs; the plan's values measured 2.80 and
   2.92 there. The values changed, not the target.
3. **`accent.primary` now carries no text at all.** Porcelain's measures 4.20 on
   a raised surface. Anything with a label uses `accent.strong`.
4. **Four on-terminal tokens were added.** The terminal is its own surface with
   real UI on it, and nine of the sixty-nine literals existed because the table
   had no row for that.
5. **`StatusBadge` needed five vocabularies, not three.** Separating node,
   connection and session state immediately exposed two views borrowing the node
   palette for enrolment-token lifecycle and runtime availability — which worked
   only while one label table served everything. An active token would have read
   as "線上": right colour, false sentence.
6. **Monaco's theme reaction belongs in `PreviewPane`.** Putting it in the
   workspace view static-imports Monaco and undoes the async boundary that keeps
   the editor out of the bundle for users who never open a file.

## Verified here, and not verified here

Green on this host (13 legs, `artifacts/vr/local/commands.txt`): format, lint,
typecheck, 746 unit tests, build, the four new gates, plan/09's three gates
unmodified, the 220-pair contrast table, the xterm geometry probe, and
`make traceability` (451 criteria, 0 blocking).

Each of the four gates was verified to fail on the change it exists to catch —
a literal colour, a retired token name, a text glyph, and four separate ways of
breaking `theme-boot.js`.

**Not verified here**, and named in `skipped.txt` rather than omitted:

1. The theme switch leaving the session, scrollback, scroll position and unsent
   input intact. The assertion is written (`tests/e2e/theme.spec.ts`) and needs a
   full stack with an online node. **This is the phase's central claim and it is
   currently an argument supported by a bare-xterm probe, not an end-to-end
   measurement.**
2. No CSP violation from the boot script against a real edge.
3. The 36-cell acceptance matrix (2 themes × 3 breakpoints × 6 states).
4. The ANSI 16 comparison on real Claude and Codex screens. Its criterion is "can
   a person still read this", which has no numeric answer.
5. Firefox and WebKit for the geometry probe — this host lacks the system
   libraries. Quantified argument: 30 rows at the gate geometry needs a cell
   ≤ 22.4px, and chromium measures 19px at 14/1.2, so another engine would have
   to be more than 18% taller with the same local monospace stack.

Until (1) runs, the exit report should say so — and this one does.

## The v2 replay cost is not mechanical

`plan/28` §7's last row asks for `git diff master...v2 --stat -- frontend/src` and
a human judgement on what it costs. The answer is worth more than the file count.

130 files, +25275 lines — but the number is not the finding. The finding is that
**both lines built a UI primitives layer in the same directory**:
`frontend/src/components/ui/`. v2 has `UiButton.vue`, `DataTable.vue`,
`EmptyState.vue`, `ToastHost.vue`, `useToast.ts`, `UiCard.vue`, `PageHead.vue`,
`BaseBadge.vue` and five domain badges. This phase has `UiButton.vue`,
`UiDataTable.vue`, `UiEmptyState.vue`, `UiToastHost.vue` and seven more.

**Exactly one filename collides — and that is the half that will be noticed.**
`UiButton.vue` exists in both, with variant vocabularies that differ by one word
(`ghost` in v2, `quiet` here), so a merge reports a conflict and a person deals
with it. The other four *will not conflict*: a merge would leave two DataTables,
two EmptyStates and two toast systems side by side in one directory, all green,
all passing their own tests. Silent duplication is the harder half.

The token strategies are also **opposed rather than merely different**:

| | this phase (ADR 0027) | v2 |
|---|---|---|
| `tokens.css` | rewritten: 5 themes × 44 semantic tokens, with a theme dimension | keeps the old 27 and adds ~20 domain tokens (`--stage-*`, `--run-*`, `--attention-*`, `--work-*`) |
| retired token names | all gone; `GATE-VR-NO-LEGACY-TOKEN` blocks them | still in use, including `--status-error`, which that gate now rejects |
| chained `var()` fallback | forbidden; the contract test asserts none exists | `checkTokens.test.ts` has an explicit **migration flag** permitting it |
| `theme/naive.ts` | deleted | still present |

So: the **data layer replays** — D0's constraints held, and no store shape,
`api/` type or `protocol/` file changed. The **presentation layer does not**.
Merging is a decision, not a merge:

1. which primitives layer survives, and which side's components get rewritten
   against it (eleven here, or fifteen there);
2. which token strategy wins — this phase's gate turns v2's current front end
   red, and v2's migration flag is the thing ADR 0027 forbids;
3. v2's domain tokens (stage / run / attention / work) need a value per theme
   and a contrast row each; they currently have one set.

**This is a report, not a gate.** This phase neither depends on nor blocks v2.
But "v2 just replays this diff" is not true, and the cheapest moment to know
that is now.
