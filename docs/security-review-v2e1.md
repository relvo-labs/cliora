# Security review — SR-4, `v2.0.0-beta.2` (V2-E1 Ecosystem and Hardening)

- Scope: `services/provider_reads.py`, `services/knowledge/{provider_sources,provider_sync}.py`,
  migrations `0044`/`0045`/`0046`, the four columns they add, and the repository DTO that
  renders their state.
- Reviewed against: `plan/27/09` §5 (eight items), ADR 0043, ADR 0040's amendment.
- Date: 2026-08-29
- **Sign-off: NOT SIGNED.** §7 says what is outstanding. This document is the evidence,
  not the approval; a review the implementer signs is a review of nothing.

## 1. What changed about the trust boundary

**One new thing, and it is smaller than the plan expected it to be.** Central now makes
outbound HTTPS requests to a second purpose: reading pull requests and published versions.

What did **not** change is the more important half:

| | |
|---|---|
| New inbound surface | **none** — no route was added, and `api/http/` still has zero unauthenticated endpoints |
| New credential kind | **none** — the existing `provider_token`, already in `UNDELIVERABLE_KINDS` |
| New RBAC action | **none** — 27, unchanged |
| New protocol message | **none** — contract 1.13.0, `agentd` diff zero |
| Modules that may reach the network | **1 → 2**, both named in three separate enforcement points |

The upstream plan specified a webhook. ★ D120 chose polling instead, and §2 of ADR 0043
records the six things a webhook would have needed that this repository does not have —
starting with an unauthenticated `POST` route and a rate limiter. **The security delta of
this release is therefore "one more module may issue GET", not "the platform now accepts
unauthenticated input".**

## 2. The eight items

| # | Item | Verdict | Evidence |
|---:|---|---|---|
| 1 | provider token storage, scope, rotation | **PASS** | `secrets.py` unchanged — asserted by `GATE-HD-TOUCH-LIST`. `provider_token` is in `UNDELIVERABLE_KINDS`, so it is never delivered to a node; the read happens in Central because it could not happen anywhere else. Rotation is a property of the existing mechanism: replace the secret, the next round reads the new value |
| 2 | pre-merge PR content cannot become policy | **PASS** | Three layers, and they fail on different mistakes. `GATE-HD-PROVIDER-AUTHORITY-CEILING` greps the handler file for the four words above the ceiling; `PROVIDER_AUTHORITIES` is a frozenset; `_assert_ceiling` checks the *value* at the one point every one passes through — a gate catches somebody typing `"accepted"`, only the assertion catches somebody computing it. Four negative tests, one per forbidden level |
| 3 | outbound GET happens in the worker, never in a request | **PASS** | `GATE-HD-NO-PROVIDER-IN-REQUEST`: nothing under `api/http/` imports the reader. **Stronger than the upstream item it replaces** — that one reviewed a behaviour, this asserts a dependency. It also caught a comment of mine that merely *named* the module, which is the gate working rather than being awkward |
| 4 | the read module only reads | **PASS** | `GATE-HD-READS-ARE-GETS` (no method literal but `"GET"`) and `GATE-HD-NO-WRITE-IMPORT` (cannot reach `create_pull_request` or `comment_on_pull_request`). Asserted again in `pytest` against the module's own source, because a gate only CI runs is one a contributor meets late |
| 5 | a revoked token does not retry for ever | **PASS, freshly exercised** | J18 drives the production HTTP reader through three 401 rounds, observes one failure each, then a fourth round with **zero provider reads** and `skipped=1`; Chromium renders `Bad credentials` on the settings surface. The count resets on success so an outage does not accumulate towards a stop |
| 6 | the error body carries no token, into no log or metric | **PASS** | `_safe_detail` strips it (copied deliberately rather than shared — see D119). The metric label allowlist refused a new key at the call site during implementation, which is that mechanism working rather than being described |
| 7 | provider sources do not leak across projects | **PASS, freshly exercised** | J14 seeds both `pull_request` and `release` through the real handlers/store. The owner finds each; another project receives empty items **and total 0** for each; a provider source id across the boundary is the same 404 as an absent id. J14 **11/11** |
| 8 | provider content stays in the evidence layer | **PASS, freshly exercised** | J13 seeds an injection-bearing merged PR through the real handler/store, fetches a context pack through a real `agentd`, and observes the string absent before the structural boundary and present after it as cited evidence. The card and gates remain unchanged. J13 **9/9** |

## 3. Item 2 in full, because the ceiling is the decision of this release

Provider data can reach `reviewed` and no further:

```text
PR / MR, not merged      →  discussion   (0.75)
PR / MR, merged          →  reviewed     (1.15)
published version        →  reviewed     (1.15)
draft version            →  not ingested — a draft is not a fact

accepted · authoritative · canonical · verified   →  unreachable
```

**`verified` is the exclusion worth arguing about.** In this system `verified` means
*Cliora's* verification ran and passed — `sources.py` reads
`report.source == "machine_verified"`. A provider's green CI is somebody else's
verification of somebody else's criteria. Admitting it would make one rung of a ten-rung
ladder mean two things, and the entire value of ten rungs is that each means one.

The enforcement is a **file boundary**, and that is a design decision rather than an
implementation detail: `sources.py` has handlers that legitimately write the levels above
the ceiling (an approved requirement, a settled decision), so a grep there would need to
know which function a string sits in — an AST gate, which is a gate nobody reads at a
glance. Splitting the handlers into their own file makes the same rule a one-line grep.

## 4. What the fresh item 7 and 8 journeys establish — and what they do not

The inheritance remains real: provider sources are ordinary project-scoped
`knowledge_sources`, and the context builder does not branch on their source type. It is
now backed by direct observations rather than code argument alone:

- J14 exercised both provider families against item, count and source-id isolation.
- J13 exercised an actual provider-shaped PR body across the rendered instruction/evidence
  boundary and the post-run task/gate state.

The rows were seeded through `provider_sources` and `KnowledgeStore`; no network reader was
used. That is the right boundary for items 7 and 8 — they ask what happens *after content
becomes a provider source* — but it does not establish transport, freshness or token
handling. The later GET-only GitHub observation establishes real transport. J17/J18 then
exercise event timing and revocation deterministically through the production HTTP reader,
Central, frontend and Chromium against a controlled loopback upstream.

## 5. Two absences, and why the table is shorter than the upstream one

The upstream SR-4 (`research/03/10` §4) has five items. Two of them are **not here**:

| Upstream item | Status |
|---|---|
| webhook signature verification | **Does not exist.** There is no webhook (★ D120) |
| delivery id de-duplication | **Does not exist.** A job carries an entity key, not content, so processing one twice costs one redundant read |

**This is stated rather than left as a gap in the numbering**, because a review table that
is shorter than the specification it answers, with no explanation, reads as an oversight.
Three items were added in their place (4, 5, 6 above), all specific to polling.

## 6. What this release did not verify

- **All eighteen journeys pass.** J17 observes an open→merged event reaching reviewed
  knowledge and the Chromium Drawer in 2.260 s; J18 observes three refused HTTP rounds,
  a fourth with zero reads, and the stored reason in Chromium. Their upstream is a
  controlled loopback fixture, so this is deterministic production-path evidence rather
  than a mutation of somebody else's provider object.
- **A real GitHub GET reconcile and full Agent citation now exist; controlled mutation
  and refusal timing is covered without changing an external provider object.**
  `artifacts/hd/local/provider-real.json` records 48 sources in 1.63 s with zero failures;
  merged PR #49 arrived as `reviewed`, was found by search and selected by a context pack.
  J1 then repeated the real GET path on a fresh database, pinned that PR through the
  authenticated admin API, recorded it in a real run's context manifest, cited it through
  `cliora knowledge cite`, and completed 36/36 with zero terminal sessions
  (`artifacts/px/local/journeys/j1.json`).
  The same provider evidence run then disabled sync and observed an empty outcome before
  reader acquisition: reader calls 0, therefore HTTP GETs 0 (J16's added assertion).
  J12 separately ran the production `GitHubReader` against a controlled HTTP upstream:
  four GETs covered a release appearing and disappearing. The tombstone retained the
  original chunk text, removed it from retrieval, and the original source-id citation
  returned `That source no longer exists` (9/9). No external provider object was mutated.
  The credential went through `SecretService` and the report refuses to serialize it.
  J17/J18 add Drawer rendering and revoked-token behavior. A separate production-worker
  observation then kept the 300-second cadence unchanged for 3613.071 seconds: twelve
  rounds and 24 live-cursor events produced P95 **291.013 seconds**, with all 24 in the
  300-second histogram bucket (`provider-lag-hour.json`). Its upstream remained controlled;
  mutating an external provider object is intentionally still outside this evidence.
- **`pg_trgm` on Railway itself.** Closed by argument and by three local role shapes
  (`docs/security-review-v2k1.md` §6.1); the remaining unknown is Railway's own extension
  allowlist, answerable by one `psql` predicate documented in the deployment guide.

## 7. Sign-off

**Not signed.** Three things are outstanding:

1. **A named reviewer who did not write this code.**
2. **An explicit acceptance of §4's boundary** — J13/J14 directly prove post-ingestion
   isolation and evidence placement; they do not prove the network reader.
3. **The same unproved sentence SR-3 signed, again.** There is still no
   `project_members` table, so *"with per-project membership, counts do not leak the
   existence of a card in a project the caller cannot see"* remains unprovable on this
   deployment. `beta.2` adds a source type whose content comes from outside the
   deployment, which raises the stakes of that sentence without changing its status.

| Role | Name | Date | Signature |
|---|---|---|---|
| Reviewer — must not be an author of V2-E1 | | | |
| Accepting §4's tested boundary | | | |
| Accepting §3 of SR-3's unproved sentence, again | | | |

**What a signer should read first**: §5 and §6. The table in §2 is all PASS, and the two
sections that say what is *not* covered are the ones that make that table honest — a
review whose only artifact is eight green rows is a review that has not been read.

### Re-deriving rather than reading

```bash
. scripts/hd/env.sh                    # both DB vars must point at one database
scripts/hd/gates.sh                    # ten GATE-HD-* plus three rebased
cd backend && uv run --project . pytest tests/db/test_provider_ingestion.py -q
scripts/hd/rehearsal.sh                # 0040 → 0046, five steps, seven checks each
scripts/hd/rollback-drill.sh           # six steps
```
