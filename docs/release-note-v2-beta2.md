# `v2.0.0-beta.2` — V2-E1 Ecosystem and Hardening

**Status: not released.** The tag does not exist. §9 lists what is outstanding, and two of
those items are decisions rather than work.

---

## What this release is for

`alpha.2` made a sentence provably happen once. `alpha.3` made every sentence an agent
reads say where it came from. `beta.1` made one fact look the same on six screens.

**This one is about handing the system to somebody who did not build it.** Three things
that requires:

> A fact from the outside world — a pull request merged, a version published — reaches the
> project's memory carrying a trust level that is *lower* than anything Cliora approved
> itself. `blocked`, which has meant two things since V2.0, means one. And everything on
> screen has a path that needs no mouse, no colour, and survives 200% zoom.

---

## What changed

### Provider sync, by polling

Cliora reads pull requests and published versions from GitHub. It does this by **polling
inside the existing reconcile pass**, not by accepting webhooks.

- **Freshness is 300 seconds, and that is a commitment rather than an implementation
  detail.** A merge becomes visible within one reconcile interval. `provider_reconcile_lag_seconds`
  is the metric that proves it; without that metric the sentence would be a claim.
- **Per project**, off by default (`provider_sync_enabled`). Turning it off stops updates
  and deletes nothing.
- **Trust has a ceiling.** An unmerged pull request is `discussion`; a merged one and a
  published version are `reviewed`. Nothing from a provider can reach the levels Cliora
  uses for its own approvals and its own verification — a provider's green CI is somebody
  else's verification of somebody else's criteria.
- **The state is visible.** A repository that has stopped being read says so, says why,
  and says what fixes it. Without that, a revoked token looks exactly like a week with
  nothing merged.

Why polling and not webhooks: a webhook needs an unauthenticated endpoint, HMAC
verification, a delivery de-duplication table, a rate limiter, a new credential kind and
its rotation, and a security review of a new ingress. None of those exist here, and every
piece polling needs already did. **What is given up is freshness, and it is a number.**
ADR 0043 §2 records the webhook design as designed-and-not-implemented, so the next person
does not have to re-do the analysis.

### `blocked` is no longer a stage

Since V2.0 a card could be blocked in two different ways, and `tasks.is_blocked` gave the
wrong answer when read directly — a defect ADR 0040 recorded with a scheduled repair date.
This is that repair.

- `0045` moves the data and gives every blocked card a reason.
- `0046` removes `blocked` from the stage's value set. **This is the first irreversible
  migration in the V2 series** — see §5.
- The three platform writers that used to set the stage now set the column *and say why*.
  "An agent asked and nobody answered" and "this run exhausted its attempts" are different
  facts; the stage said neither.

### Accessibility

Eight screens, WCAG 2.2 AA, **0 critical and 0 serious** violations.

Two of the fixes are worth naming because both had been silently broken:

- Fleet metric cards carried an `aria-label` on a `<p>`, which ARIA prohibits — so the
  accessibility tree discarded it and a screen reader announced the bare number, the exact
  thing the label was added to prevent. A unit test asserted the attribute was *present*
  and passed for months.
- Three `<select>` controls in the task drawer had no accessible name at all. They have a
  `<dt>` beside them, which associates nothing programmatically.

**`research/style.md`'s four semantic colours were all below AA as small text** — Success
4.07, Warning 3.00, Error 4.17, Info 4.18, against a 4.5 requirement. The same document
mandates that colour is never the only cue. Hue and saturation are unchanged; lightness
moved. The original values remain valid for large text, fills and borders.

### Visual regression

Eight screens pinned with Playwright's built-in screenshot comparison, threshold
`maxDiffPixelRatio: 0.01`, chromium only, baselines in the repository. A reverse test
proves the suite can fail.

### `/board` is deleted

The V1 board endpoint, its three DTOs, its repository method and the frontend client
method — all removed. It had zero callers. ADR 0044 preserves the measurement its pinned
test carried, because three live decisions were argued from it.

---

## Compatibility manifest

```text
Central commit     255e8d5
agentd             0.14.1        zero diff — asserted by a gate
contract           1.13.0        unchanged — asserted by a gate
migration head     0046_stage_blocked_check
RBAC actions       27            unchanged
requirements       205 in 30 families   (+FR-PROV-001…004)
frontend tokens    72            unchanged in count; four values darkened
```

---

## Migration and rollback

| Revision | What | Reversible? |
|---|---|---|
| `0044` | two source types into **two** CHECK constraints, four columns | ✅ downgrade deletes provider sources; one reconcile pass rebuilds them |
| `0045` | blocked cards move off the stage; `legacy_blocked_at` witnesses the move | ✅ **completely** — that column exists for this |
| `0046` | `blocked` leaves the stage's value set | ❌ **the value set returns; the data does not** |

**What `0046` costs, precisely.** A card blocked *after* it went through `is_blocked` and
has no `legacy_blocked_at`, because that column is written once, by `0045`, for the rows it
moved. After a downgrade those cards are `is_blocked = true` on their real stage — correct,
and invisible to a six-lane board. `/board` being deleted first is what makes that
harmless: there is no six-lane screen left to hide them.

Rehearsed on a database built from empty: `0040` → `0046` → `0043` → `0046` → `0040` →
`0046`, plus a dump/restore round trip, with seven verifications after every step. **The
rehearsal found a real defect on its first run** — `0046` worked only on a database that
had already run it.

Before any rollback: **export saved views**. `beta.1` deliberately shipped without a
version flag, so there is no switch that turns the new interface off, and nothing else
preserves a person's saved views. `scripts/hd/rollback-drill.sh` step 2 is that export.

---

## Known limitations

| # | Limitation | Who carries it |
|---:|---|---|
| 1 | **Provider sync is 300 seconds, not instant.** A merge takes up to five minutes to appear | Users. The webhook design is in ADR 0043; implementation is not scheduled |
| 2 | **GitHub only.** GitLab has no reader, deliberately | Deployments on GitLab cannot use provider sync at all |
| 3 | **Nothing above 2000 cards / 20000 chunks has been measured.** Database size, GIN rebuild time and queue depth are known only to that point | Operations |
| 4 | **Visual regression covers eight screens.** A ninth screen's layout regression has nothing watching it | Development |
| 5 | **Visual baselines bind the font environment, not just the browser.** The first set was captured without CJK fonts and pinned a page of tofu boxes. CI must use an image with the same fonts or the first run is eight failures | Development / CI |
| 6 | **50 repositories use 36% of GitHub's hourly quota** (1800 of 5000 GET). Around 140 repositories reaches the ceiling | Operations |
| 7 | **`legacy_blocked_at` is a transition column**, scheduled for removal after `rc` | Development |
| 8 | **`?tab=` redirect is not removed and its usage is not measurable.** The SPA is served by nginx, so the application never sees it. It is removed in `rc.1` regardless of usage; evidence, if wanted, is `grep -c 'tab=' access.log` | Operations |
| 9 | **No project membership**, so "cards from a project the caller cannot see are absent from counts" remains unprovable on this deployment | Whoever signs the security review |
| 10 | **The eighteen journeys were not run.** They need a stack with a real daemon | Release |
| 11 | **No call was ever made to a real provider.** Every test injects a fake reader | Release |
| 12 | **`pg_trgm` on Railway itself is still unverified** — closed by argument and three local role shapes, with a one-line `psql` predicate to answer it on a real deployment | Operations |

**A short known-limitations list is not good news.** This one is twelve items, four of
which (10, 11, 12, 5) are things this environment could not do rather than things the
design chose.

---

## Security delta

**The one sentence that matters**: `httpx` is now reachable from **two** modules instead
of one. That is the first change to the shape of Central's outbound connectivity since
V2.4, and it is stated here rather than buried inside "added provider sync".

What did **not** change: no new inbound surface, no new credential kind, no new RBAC
action, no protocol change, no `agentd` diff. Three separate enforcement points hold the
two-module boundary — two gate scripts and one ordinary test — and the third of those was
found only when it went red.

Full review: `docs/security-review-v2e1.md`. **It is not signed**, and §5 and §6 of it are
the sections to read before signing.

---

## Data retention delta

- Provider sources follow ADR 0038 §6 — **knowledge has no clock**. A pull request ingested
  today is stored until somebody deletes the project or the repository.
- A pull request closed *unmerged* is retained as `discussion`: "this proposal was
  rejected" is worth keeping.
- A published version deleted upstream keeps its content with `deleted_at` set, so a
  context pack that cited it can say the source was later removed rather than hold a
  dangling id.
- Measured: **~7.5 KB of database per knowledge chunk**, of which 2.5 KB is index. 20,000
  chunks is ~150 MB and **none of it is ever reclaimed**.

---

## Feature flag matrix

| `PROJECTS_ENABLED` | `AGENT_RUNS_ENABLED` | `projects.knowledge_enabled` | `projects.provider_sync_enabled` | Behaviour |
|---|---|---|---|---|
| `false` | — | — | — | Identical to V1. Project routes 404, not 403 |
| `true` | `false` | `false` | `false` | Projects and the work views; no agent runs, no memory |
| `true` | `true` | `false` | `false` | …plus agent runs |
| `true` | `true` | `true` | `false` | …plus project memory from Cliora's own data |
| `true` | `true` | `true` | `true` | …plus provider sync. **No outbound request is made in any row above this one** |

The last two are per project, not per deployment: the cost and risk of indexing a
repository, or of calling somebody else's API, belong to a project rather than to an
installation.

---

## Evidence

```text
scripts/hd/gates.sh                     ten GATE-HD-* plus three rebased
backend: pytest tests                   2144 passed
frontend: npm run test:unit             852 passed
artifacts/hd/local/w1/axe-after.json    eight screens, 0 critical / 0 serious
artifacts/hd/local/w1/visual-negative.md the reverse test
artifacts/hd/local/w3/provider-sync-states.png  four sync states on a real screen
artifacts/hd/local/w5/README.md         seven EXPLAIN plans, volumes, cost
artifacts/hd/local/w6/rehearsal-compose.log     five steps, seven checks each
artifacts/hd/local/w6/rollback/drill.log        six steps
```

---

## Outstanding before this can be tagged

| ☐ | Item | Kind |
|---|---|---|
| ☐ | **SR-4 signed**, including §4's inheritance argument and §7's third row | A person |
| ☐ | **The a11y audit's six manual checks** — focus order, announcements, keyboard drag, 200% zoom, reduced motion, greyscale. All six say *not performed*, not *performed and passed* | A person at a browser |
| ☐ | **The eighteen journeys**, against a real daemon | A stack |
| ☐ | **The Railway `psql` predicate**, on a real Railway deployment | One command |
| ☐ | **`v2.0.0-alpha.3` and `v2.0.0-beta.1` tags** — both have all exit conditions green and neither exists | A person |
| ☐ | **`v2` → upstream approval** | A person, and never automation |

**The last row is always last, and it is never automatic.** Every exit condition being
green earns the right to propose a merge; it is not the merge.
