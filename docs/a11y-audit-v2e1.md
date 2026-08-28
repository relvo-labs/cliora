# Accessibility audit — `v2.0.0-beta.2` (V2-E1), WCAG 2.2 AA

- Scope: the eight screens in `frontend/tests/hd/screens.ts` — Active Board, Backlog,
  three Drawer states, My Work, Project Overview, Home.
- Method: `@axe-core/playwright` for the automatic half (§2), a person for the six
  things it cannot see (§3).
- Date: 2026-08-28
- **Sign-off: NOT SIGNED.** §4 says what is outstanding. This document is the evidence,
  not the approval.

## 1. What the automatic half found, in the order it found it

**Two rounds, and the second one is the reason this section is written as a sequence
rather than as a table.**

| Round | Screens genuinely scanned | critical | serious |
|---|---:|---:|---:|
| 1 — first run | **5 of 8** | 0 | 12 |
| 2 — after the placeholder guard | **8 of 8** | **8** | 0 |
| 3 — final | 8 of 8 | **0** | **0** |

Round 1 reported five screens and claimed eight. The three Drawer URLs are built from
task ids resolved at run time, `page.request` carried no Authorization header (the app
keeps its token in `localStorage`, ADR 0006/0007), the resolver returned nothing, and the
literal `?task=__WAITING__` reached the router — which dropped it and rendered the plain
board. **Three of the eight screens were the board, and the run was green.**

Nothing failed, because every individual check passed. The suite's own comment warned
about the neighbouring version of this (screenshotting a spinner) and the audit walked
into a different one anyway.

`assertResolved` in `screens.ts` is the fix: an unsubstituted `__PLACEHOLDER__` is a
**failure**, never a skip. A skip would restore the silence exactly.

**What round 2 then found was the worst class in the whole audit** — three unlabelled
`<select>` elements in the Drawer, `critical`, the card's Source, Delivery and dispatch
Agent controls. A screen-reader user could not tell what any of them set.

## 2. The automatic half — final state

Threshold: **0 `critical`, 0 `serious`**. Tags: `wcag2a wcag2aa wcag21a wcag21aa wcag22aa`.

| Screen | critical | serious | moderate | minor |
|---|---:|---:|---:|---:|
| Active Board | 0 | 0 | 0 | 0 |
| Backlog | 0 | 0 | 0 | 0 |
| Drawer — waiting for input | 0 | 0 | 0 | 0 |
| Drawer — no eligible runner | 0 | 0 | 0 | 0 |
| Drawer — blocked by dependency | 0 | 0 | 0 | 0 |
| My Work | 0 | 0 | 0 | 0 |
| Project Overview | 0 | 0 | 0 | 0 |
| Home | 0 | 0 | 0 | 0 |

**`moderate` and `minor` are zero, and that is a measurement rather than a claim** —
`plan/27/04` §5 requires the counts in the release note precisely so that "we know there
are N" and "we did not look" stay distinguishable. Here N is 0.

Evidence: `artifacts/hd/local/w1/axe-before.json` (round 1, under-counted — read §1
before quoting it) and `axe-after.json` (round 3).

### 2.1 What was fixed

| Violation | Where | Fix |
|---|---|---|
| `color-contrast` × 16 | four palette tokens, on 7 screens | §2.2 |
| `aria-prohibited-attr` × 8 | `MetricCard.vue` — `aria-label` on a `<p>` | accessible name moved into a `.sr-only` span |
| `scrollable-region-focusable` × 3 | `.lanes`, the board's horizontal scroller | `tabindex="0"` + `role`/`aria-label` + a visible `:focus-visible` outline |
| `select-name` × 8 | `TaskDetail.vue` ×2, `TaskAgentPanel.vue` ×1 | `aria-label` on each `<select>` |

Two of these are worth more than their line:

**The `<p aria-label>` had never worked.** ARIA prohibits `aria-label` on a `<p>` with no
role, so the accessibility tree discarded it and the reader heard the bare number — the
exact thing the attribute was added to prevent. A unit test asserted the attribute was
*present* and passed for months. Checking that an attribute exists is not checking that
it does anything; the test now reads the rendered text.

**The `<dt>` beside a `<select>` is a visual label only.** A definition list associates
nothing programmatically. Three controls that look labelled were not.

### 2.2 The palette did not meet the standard the same document mandates

All sixteen `color-contrast` violations traced to four values, and **all four are in
`research/style.md`'s own semantic palette**:

| | style.md, before | vs white | after | vs white | vs Gray-100 |
|---|---|---:|---|---:|---:|
| Success | `#3E8C6A` | 4.07 | `#377C60` | 4.98 | 4.60 |
| Warning | `#C08B3E` | **3.00** | `#93692F` | 4.88 | 4.51 |
| Error | `#C45C5C` | 4.17 | `#BE4B4B` | 4.89 | 4.51 |
| Info | `#4A7FB8` | 4.18 | `#4272A9` | 4.99 | 4.60 |

**Not one of them could legally be used as small text**, and this system's status text is
11–12px throughout. The same document's *«顏色以外的辨識線索»* section says a state
distinguished only by colour "does not exist" for a colour-deficient user — while the
colours it supplies do not guarantee the text is legible at all. Six phases read past it.

Hue and saturation are unchanged; only lightness moved (`plan/27` §4: change existing
token values, do not add tokens). The original values remain valid for **large text
(≥18pt, or ≥14pt bold), fills and borders**, where the threshold is 3:1.

**Warning moved furthest** (`#C08B3E` → `#93692F`, visibly browner) because 3.00 is too
far from 4.5 for any lightness-only change to preserve. Choosing a brighter compliant
warm tone is a *palette decision* and belongs in `style.md` with this table, not in
`tokens.css` alone.

`tokens.css` had also drifted from `style.md` independently (`#2f9b63` vs `#3E8C6A`); the
two now agree.

## 3. The manual half — six things axe cannot see

**This section is why the audit is not finished by §2.** A report that is green above and
silent here reads as "the screens are accessible", which is a stronger claim than was
tested.

| # | Item | WCAG | Status |
|---:|---|---|---|
| 1 | Focus order matches visual order; Drawer returns focus to the card that opened it | 2.4.3 | ☐ **not performed** |
| 2 | State changes are announced — move, filter apply, attention change — recorded as **the words actually heard** | 4.1.3 | ☐ **not performed** |
| 3 | Drag has a keyboard equivalent: Backlog → Ready without a mouse | 2.1.1 | ☐ **not performed** |
| 4 | No horizontal scrollbar at 200% zoom on any of the eight | 1.4.10 | ☐ **not performed** |
| 5 | `prefers-reduced-motion` stops the Drawer slide, the optimistic move and skeleton pulses | 2.3.3 | ☐ **not performed** |
| 6 | Attention remains distinguishable in greyscale | 1.4.1 | ☐ **not performed** |

**All six require a person at a browser** — a screen reader for 2, a keyboard for 1 and 3,
the OS motion setting for 5, and eyes for 6. None of them can be delegated to the suite
in §2, which is the entire reason `plan/27` D125 lists them separately instead of
declaring the audit done when axe is green.

Item 3 has a partial automated proxy: `plan/26` states the Move dialog is "a real path,
not a fallback". That is a claim about the code, not a demonstration that a person can
finish the task; it does not close the row.

## 4. Sign-off

**Not signed.** Two things are outstanding:

1. **The six rows in §3.** Not performed — not "performed and passed".
2. **A named person.** The same shape as SR-1/SR-2/SR-3 in this repository: the evidence
   is this document, the signature is a separate act.

| Role | Name | Date | Signature |
|---|---|---|---|
| Performed §3's six manual checks | | | |
| Accepting the audit for `v2.0.0-beta.2` | | | |

**What a signer should read first**: §1, not §2. The final table is green; the sequence
that produced it contains a run that was green while auditing five screens and reporting
eight. The number that matters for trusting §2 is not "0 violations" — it is that the
suite now fails when a screen cannot be reached.

### Re-running

```bash
. scripts/hd/env.sh && hd_stack_env         # both DB vars must point at one database
cd frontend
E2E_HD_PROJECT=<uuid> npx playwright test --config tests/hd/playwright.config.ts a11y
```

The project is seeded by `scripts/px/seed-attention-demo.py`, which produces the three
attention levels the Drawer screens select on. Without them `assertResolved` fails and
names the seed script.
