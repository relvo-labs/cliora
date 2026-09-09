# ADR 0027 — Visual theming: one semantic token contract, two sources, two themes

- Status: accepted
- Date: 2026-09-08
- Amends: ADR 0005 (its sentence "Naive UI overrides reference those variables instead of
  duplicating hex values"). The rest of ADR 0005 — `tokens.css` is the palette source, the
  terminal composable exclusively owns xterm's lifecycle — is **not** superseded and is
  strengthened here.
- Related: ADR 0015 (read-only preview policy: theming an editor is not granting it a
  capability), ADR 0016 (system font stack, `dist` carries no CDN reference), ADR 0017
  (CSP is `script-src 'self'`, unchanged — §4 exists to work *inside* it), ADR 0023
  (privileged posture labels must stay visible before the user types), ADR 0024 / 0026
  (the two write paths; their display conditions are untouched)
- Requirements: `NFR-006` (new), `FR-TERM-001.AC-15`, `FR-TERM-001.AC-16`,
  `FR-TERM-005.AC-07`
- Contract: unchanged (no wire or schema change; this ADR touches `frontend/src` only)
- Plan: `plan/28/`

## Context

ADR 0005 made `frontend/src/theme/tokens.css` the palette source and expected component
styles to reference it. Three years on, the actual state of the colour system is four
systems, not one:

| Source | Location | State on 2026-09-08 |
|---|---|---|
| CSS custom properties | `theme/tokens.css` | 27 tokens, **one light set**, no theme dimension |
| Literal values in components | 13 files | **69** occurrences (`#hex`, `rgb()`); `StatusBadge.vue` alone holds 12 |
| xterm's own palette | `useTerminalSession.ts:218-223` | 4 hard-coded dark values; ANSI 16 left at xterm's defaults |
| Monaco's own palette | `monaco/setup.ts` `defineTheme()` | 10 hard-coded dark values |

Two consequences follow from that, and only the first is usually noticed.

The obvious one: there is no way to switch themes. `docs/design/visual-refresh/` specifies
five styles, two of which (Graphite, Porcelain) plan/28 delivers; a theme switch under the
current shape means editing 13 files.

The one that matters more: **the palette is not measured anywhere**, so failures accumulate
silently. Measuring the current tokens against their real backgrounds (sRGB relative
luminance, method in `plan/28/02-token-contract-and-themes.md` §6) finds five failures that
exist today, in code that has shipped:

| Pair | Where | Measured | Target |
|---|---|---:|---|
| `--border-focus` / panel | every keyboard focus ring in the app | **2.85:1** | 3:1 |
| `--text-inverse` / `--status-error` | the Terminate confirm button | **4.09:1** | 4.5:1 |
| `--border-default` / panel | every input and secondary button border | **1.37:1** | 3:1 |
| `online` badge fg/bg | `StatusBadge.vue:44` | **3.13:1** | 4.5:1 |
| `degraded` badge fg/bg | `StatusBadge.vue:48` | **2.63:1** | 4.5:1 |

Six of the eight `StatusBadge` pairs are under 4.5:1. That is not carelessness — `style.md`
§17 says "Online Green" and never says *green on what*, so the implementation had to invent
the background, and nothing in the repository could disagree with the invention. The
traceability set has 115 requirements and **none** of them is about legibility, keyboard
operation or visual theming, so these five failures are not waived; they are invisible.

`naive-ui` is a fourth thread in the same knot. The shared design foundation says
integration "retains the existing Vue, Pinia, **Naive UI**, xterm.js, Monaco" — true of
everything in that list except Naive UI, which has never been used: zero `<n-*>` components,
one type-only import in `theme/naive.ts`, and that file is imported by nothing. Its eight
lines would not work if they were wired up, because they set `primaryColor:
"var(--action-primary)"` and Naive UI derives hover/pressed/disabled steps by parsing that
value as RGB.

## Decision

**1. Semantic tokens are the only source of colour, and they have a theme dimension.**

`theme/tokens.css` defines the default theme on `:root` and overrides it on
`:root[data-theme="…"]`. Every theme **defines every token**. Chained `var(…, fallback)` is
forbidden as a way to cover a missing definition: a token missing from one theme shows up as
"that area kept the previous theme's colour", which reads as merely odd in a screenshot
review and is therefore the failure mode most likely to ship. `theme/themes.test.ts` asserts
key-set equality (`toEqual`), not containment.

**2. CSS and JS are two sources, bound by one test.**

`theme/themes.ts` exports the same values as concrete strings, because two consumers cannot
take a custom property: `terminal.options.theme` and `monaco.editor.defineTheme()` both need
resolved colours. `theme/theme.contract.test.ts` parses the text of `tokens.css` and compares
it key-by-key against `THEMES`; any drift is red.

Rejected: **one source, resolved at runtime through `getComputedStyle`.** It returns the
*previous* theme's value during the frame of the switch, and an empty string on an element
inside a `display: none` subtree — which is exactly how the CLI panel is hidden
(`v-show`). Two sources plus a binding test is the only shape that serves both consumers.

The cost is explicit: two files that could drift. `theme.contract.test.ts` is the fuse. Without
it this decision is just two files that *will* drift.

**3. No literal colour anywhere in `frontend/src`** except `theme/tokens.css` and
`theme/themes.ts`. Enforced by `GATE-VR-NO-LITERAL-COLOR`. The gate is only honest once the
token table has an exit for every case that needed a literal — badge fg/bg/border triplets,
terminal colours, on-terminal UI text — so the table lands first and the gate lands with it,
never before.

**4. Themes apply through `<html data-theme>`, set before first paint by
`public/theme-boot.js`.**

An external file, not an inline script: the CSP at `deploy/nginx/nginx.conf:134` and
`deploy/railway/nginx.conf.template:114` is `script-src 'self'` with no `'unsafe-inline'`, so
an inline bootstrap is blocked by the browser and the symptom is "the theme sometimes doesn't
apply". Not in `main.ts` either: that is a deferred module and runs after the stylesheet has
already painted, so a user whose explicit choice differs from their OS preference sees one
flash. In `public/` rather than `src/` so Vite does not hash the name and `index.html` can
reference a fixed path. It stays under 12 lines and imports nothing;
`GATE-VR-NO-GLYPH-ICON` checks that.

Rejected: **pure CSS `@media (prefers-color-scheme)`** — it cannot express "the user
explicitly picked the theme opposite to their OS". **Adding `'unsafe-inline'`** — relaxing a
site-wide security header for eight lines of JavaScript.

**5. Two themes ship: Graphite (default, dark) and Porcelain (light).**

Dark is the default because of what is already on screen, not preference: the terminal and
Monaco are dark, and a light frame around them puts a high-contrast edge around the one
region the user is actually looking at. Porcelain ships in the same release because only a
light theme exposes the hard part — a dark terminal inside a light frame needs its own text
colour (`--text-on-terminal`) — and a dark-only delivery would omit that whole dimension of
the table without noticing.

Midnight, Studio and Industrial keep their values in `themes.ts` (they are already
specified, and the cost of retaining them is near zero) but get **no layout variants, no
entry in the switcher, and no acceptance screens**. The shared foundation permits a reduced
matrix provided the reduction is recorded; it is recorded in
`plan/28/06-verification-and-exit.md` §5 and in the release note.

**6. `naive-ui` is removed from the dependency list, along with `theme/naive.ts`.**

"Retaining" something never used is *introducing* it: it would add a second component
vocabulary and a second theme-override system with its own token names, making the token
table serve two consumers. That is its own ticket, not part of a visual refresh. The four
accessibility behaviours the shared foundation expected from "existing UI component
capabilities" are hand-built instead — two already exist and are correct (`WorkspaceTabs`
roving tabindex, `FileTree` keyboard operation) and two did not exist at all (dialog focus
containment, drawer). ADR 0005's Naive UI sentence is replaced by this clause.

**7. No webfont.** ADR 0016's system stack and its build-time "no CDN reference in `dist`"
grep stand. `useTerminalSession.ts:216` names `"JetBrains Mono"`, which has never been
bundled and has therefore always been a font name that falls back; it is deleted. That makes
the code agree with ADR 0016 — it does not change ADR 0016.

**8. Contrast is a test, not a review.** Every pair that a component actually renders has a
row in `theme/theme.contrast.test.ts` with its measured value. The pair list is generated from
the **component contracts** (`plan/28/04-component-foundation.md`), not from the token table:
the five design documents built their contrast tables from the token list and that is precisely
how they missed `accent.primary` on `accent.subtle` — the selected state of navigation and
tabs — which fails in Porcelain (4.13:1) and Studio (3.37:1). `--accent-strong` exists because
of that measurement.

## Consequences

Good:

- Switching themes is one attribute, not 13 files.
- xterm and Monaco cannot drift from the pages again; they read the same table.
- The five contrast failures above are fixed, and a unit test goes red if someone lightens
  `--text-secondary` two steps.
- `NFR-006` makes legibility and keyboard operation visible to traceability for the first
  time, so the next failure of this kind is a red gate rather than an invisible one.

Costs, stated rather than discovered later:

- **Two colour sources.** Paid for §2's two consumers; `theme.contract.test.ts` is the fuse.
- **An unbundled script in `public/`.** It must stay tiny, import nothing, and do nothing but
  read `localStorage` and set an attribute.
- **Dialog focus containment and the drawer are ours to build** (~120 lines, one shared
  `useFocusTrap`), because §6 removes the library that was assumed to provide them.
- **The terminal gets shorter.** A real status bar (28px), a fixed-height tab strip and a
  taller work header cost roughly 60px, and 13px→14px changes the cell height. Measured in
  chromium at the gate geometry: `14px/1.2` gives **35 rows** against plan/09's floor of 30.
  The five design documents' literal "line-height 1.6" gives **26** and is revised
  (`research/style.md` §18) — that is a hard conflict with plan/09's gate, not a preference.

## Alternatives rejected

| Alternative | Why not |
|---|---|
| Fix only the five contrast failures, no theming | The failures are symptoms of "the table has no exit for badge fg/bg", so the fix is the table. Patching five values leaves the next 30 literals to be invented the same way. |
| One source of colour, `getComputedStyle` at runtime | Wrong value during the switch frame; empty string in a `display: none` subtree, which is how the CLI panel is hidden. |
| Deliver Graphite only | Omits `--text-on-terminal` and the whole light-frame/dark-terminal problem without noticing it was omitted. |
| Deliver all five themes | ~2.5× the work, three layout variants means triple the responsive acceptance, and Porcelain's and Studio's contrast corrections both have to land anyway. |
| Wire up Naive UI as the shared foundation's text implies | Introduces a second component vocabulary and a second token system; "tokens are the only source" becomes "tokens plus Naive overrides are two sources". |
| Keep `naive-ui` as a dependency, unused | Pays install time, lockfile weight and supply-chain surface for zero value, and leaves the next reader believing the shared foundation's sentence. |
| Store preferences server-side | A visual refresh has no reason to touch the authorization surface. Preferences live in `localStorage`; the cost is that they do not follow the user across machines, and that is written into the release note. Cross-device preferences are a separate ticket whose real question is "do preferences enter the audit log", not "shall we add a column". |
