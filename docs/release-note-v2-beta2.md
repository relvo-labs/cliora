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

### Both scale-budget misses were remediated

`HD-09` re-weighed all thirteen performance budgets on 2000 cards and 22,000 knowledge
chunks. The first run found two misses. `work-counts` was narrowed to the policy's
required projection and identical in-flight polls were coalesced. The context search got
a heterogeneous, human-labelled relevance control before its FTS ranker changed;
**all measured budgets now hold**:

| | 200 cards / 1000 chunks | 2000 cards / 22000 chunks | Budget |
|---|---:|---:|---|
| context pack build P95 | 78.80ms | ~~3236.24ms~~ → **102.76ms** | 2000ms |
| `work-counts` P95, concurrency 10 | — | **132.18ms** | 200ms |

The context-pack cause, cost model, heterogeneous control and remediation are in
`artifacts/hd/local/w6/perf-2000.md` and the scale amendment to ADR 0038. Its FTS channel
uses `ts_rank` with the same complete matching candidate set; 43/43 search/context DB
tests and seven human-labelled top-result judgements pass. The remediated counts path has
no completed-result cache: a later poll still recomputes.

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
| 10 | **All eighteen journeys pass.** J1 real GitHub merged-PR is 36/36; J12 production-reader HTTP release lifecycle 9/9; J13/J14 9/9 and 11/11; J16 reader 0 / GET 0; J17 controlled open→merged event reaches the Chromium Drawer in 2.260 s; J18 stops after three refused rounds, reads zero on the fourth, and renders the reason | Release |
| ~~11~~ | ~~Provider scheduler P95 was unmeasured~~ → **Closed 2026-08-29:** the production worker ran twelve unchanged 300-second rounds over 3613.071 seconds. Its 24 live-cursor events measured P95 **291.013 seconds**, with 24/24 in the 300-second histogram bucket (`provider-lag-hour.json`) | — |
| 12 | **`pg_trgm` on Railway itself is still unverified** — closed by argument and three local role shapes, with a one-line `psql` predicate to answer it on a real deployment | Operations |
| ~~13~~ | ~~Context pack build exceeded 2000ms at 22,000 chunks~~ → **Closed 2026-08-29:** a heterogeneous human-labelled relevance control preceded the `ts_rank_cd` → `ts_rank` change; the same 22,240-chunk DB now measures **102.76ms**, with 43/43 search/context DB tests and 8/8 KN-13 fixed queries | — |
| ~~14~~ | ~~`work-counts` exceeded D95~~ → **Closed 2026-08-29:** narrow projection plus identical-poll single-flight gives P95 132.18ms at concurrency 10 and 401.45ms at 50; concurrency 100 completed 500/500 at 802.96ms | — |
| 15 | **No worker count is configured anywhere.** Every launch in the repository uses uvicorn's single-worker default. The remediated counts endpoint no longer sheds load in the measured 100-concurrency burst, but other CPU-bound paths have not been sized this way | Operations |

**A short known-limitations list is not good news.** Four entries (10, 11, 12, 5) describe
evidence this environment still cannot supply rather than design choices. `HD-09` exposed
13–15; 13 and 14 are now closed, while the deployment choice in 15 remains explicit.

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

Measured on the `HD-10` dataset — 20,011 cards across ten projects, 22,000 chunks
(`artifacts/hd/local/w5/volumes.txt`):

| Relation | Size | Per unit |
|---|---:|---|
| `knowledge_chunks` | 150 MB | ~6.8 KB per chunk, of which the two indexes below are 2.3 KB |
| ├ `ix_knowledge_chunks_fts` | 22 MB | the CJK bigram tsvector — 3.5x the text it indexes |
| ├ `ix_knowledge_chunks_trgm` | 28 MB | GIN over content; the largest single index in the database |
| `knowledge_sources` | 10 MB | ~2 KB per source |
| `tasks` | 35 MB | ~1.8 KB per card, nine indexes included |
| **total** | **207 MB** | for a deployment ten projects deep |

**The two knowledge indexes are 50 MB of the 207.** Retrieval is what this data costs, and
ADR 0038's "knowledge has no clock" means the row only ever grows.

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
backend: pytest tests                   2154 passed
frontend: npm run test:unit             852 passed
artifacts/hd/local/w1/axe-after.json    eight screens, 0 critical / 0 serious
artifacts/hd/local/w1/visual-negative.md the reverse test
artifacts/hd/local/w3/provider-sync-states.png  four sync states on a real screen
artifacts/hd/local/w5/README.md         seven EXPLAIN plans, volumes, cost
artifacts/hd/local/w6/rehearsal-compose.log     five steps, seven checks each
artifacts/hd/local/w6/rollback/drill.log        six steps
artifacts/hd/local/w6/perf-2000.md              thirteen budgets; all measured budgets pass
artifacts/hd/local/w6/concurrency-2000.json     one worker; current 10/50/100 burst
artifacts/hd/local/w6/concurrency-2000-4workers.json   historical pre-remediation comparison
artifacts/hd/local/journeys/summary.json        journey evidence and provider gaps
artifacts/hd/local/provider-real.json            GET-only real GitHub reconcile; merged PR selected
artifacts/hd/local/provider-lag-hour.json        12 production-cadence rounds; 24 samples; P95 291.013s
artifacts/hd/local/evidence.log                 all nine steps in one run
```

---

## Outstanding before this can be tagged

| ☐ | Item | Kind |
|---|---|---|
| ☐ | **SR-4 signed**, including §4's inheritance argument and §7's third row | A person |
| ☐ | **The a11y audit's six manual checks** — focus order, announcements, keyboard drag, 200% zoom, reduced motion, greyscale. All six say *not performed*, not *performed and passed* | A person at a browser |
| ☑ | **All eighteen journeys pass.** J17/J18 use a controlled loopback upstream through the production HTTP reader, Central, frontend and Chromium; no external provider object was mutated | Closed with deterministic fixture |
| ☐ | **The visual suite has not run on GitHub Actions.** The CI job now installs Noto CJK and the local CI-equivalent run is 9/9, but no pushed remote run exists | CI |
| ◐ | **`HD-08`'s second deployment path.** The compose rehearsal ran, five steps and seven checks each, and found a real `0046` defect on its first run. The Railway path did not | Same gap as the row above it |
| ☑ | **The production worker's 300-second scheduler P95 passes.** Twelve rounds, 24 events, 3613.071 seconds observed; P95 **291.013 seconds** (`provider-lag-hour.json`) | Closed with controlled upstream; no external mutation |
| ☐ | **The Railway `psql` predicate**, on a real Railway deployment | One command |
| ☐ | **`v2.0.0-alpha.3` and `v2.0.0-beta.1` tags** — both have all exit conditions green and neither exists | A person |
| ☐ | **`v2` → upstream approval** | A person, and never automation |

**The last row is always last, and it is never automatic.** Every exit condition being
green earns the right to propose a merge; it is not the merge.

`plan/27/09` §8's forty-two exit conditions stand at **35 ☑ / 1 ◐ / 6 ☐**. Five of the six
open ones require human operation or named approval; the other one requires remote CI.
The one partial item is Railway. **That table read
0 ☑ until the day this note was finished** — the work had been done and the scorecard had
never been walked, which is how `HD-09`'s second half stayed missing long enough to be
mistaken for complete.
