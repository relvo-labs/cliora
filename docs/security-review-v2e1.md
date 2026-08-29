# Security review — SR-4, `v2.0.0-beta.2` (V2-E1 Ecosystem and Hardening)

- Scope: `services/provider_reads.py`, `services/knowledge/{provider_sources,provider_sync}.py`,
  migrations `0044`/`0045`/`0046`, the four columns they add, and the repository DTO that
  renders their state.
- Reviewed against: `plan/27/09` §5 (eight items), ADR 0043, ADR 0040's amendment.
- Date: 2026-08-28
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
| 5 | a revoked token does not retry for ever | **PASS** | Three consecutive failures stop the repository; the count resets on success so an outage does not accumulate towards a stop. `test_three_consecutive_failures_stop_the_repository` asserts the fourth round issues **no call at all** |
| 6 | the error body carries no token, into no log or metric | **PASS** | `_safe_detail` strips it (copied deliberately rather than shared — see D119). The metric label allowlist refused a new key at the call site during implementation, which is that mechanism working rather than being described |
| 7 | provider sources do not leak across projects | **PASS by inheritance**, and §4 | They are `knowledge_sources` rows with a `project_id`, so SR-2's eight isolation tests cover them without modification. **That inheritance is the argument for adding no new table**, and it is also the reason this row is weaker than it looks — see §4 |
| 8 | provider content stays in the evidence layer | **PASS by inheritance**, and §4 | ADR 0039's instruction/evidence split is applied by the context builder to every source type. A pull request body is a `knowledge_chunk` like any other |

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

## 4. What items 7 and 8 do **not** establish

Both are marked "PASS by inheritance", and the inheritance is real: a provider source is a
`knowledge_sources` row, so every isolation predicate SR-2 verified applies to it
unchanged, and the context builder's instruction/evidence split does not know what a
source type is.

**What was not done is a fresh isolation suite against a seeded provider source.** The
plan (`plan/27/09` §4) asks for J14 and J13 to be extended with provider rows, and those
journeys were not run in this environment — see §6. So the honest form of these two rows
is: *the mechanism that protects them is unchanged and tested; the specific rows were not
put through it.*

A reviewer should decide whether inheritance is sufficient here. The argument that it is:
adding no new table was chosen *precisely* so that these questions would not need
re-answering, and re-answering them per source type is the maintenance cost that decision
avoided. The argument that it is not: `pull_request` is the first source type whose
content is authored by somebody outside the deployment, and "the predicate is the same"
is a claim about code rather than an observation about rows.

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

- **The eighteen journeys were not run.** `HD-12` requires them and they need a stack with
  a real daemon. J17 (a merge reaching knowledge within 300 s) and J18 (a revoked token
  stopping) have unit-level equivalents that passed; **the end-to-end versions did not
  run**, so the freshness promise in ADR 0043 §2 is asserted by construction and by a
  metric, not by observation.
- **No call was ever made to a real provider.** Every test injects a fake reader. The
  transport — host allowlist, timeout, token stripping — is covered by unit tests against
  the module's own source and by one `httpx.Response` fixture.
- **`pg_trgm` on Railway itself.** Closed by argument and by three local role shapes
  (`docs/security-review-v2k1.md` §6.1); the remaining unknown is Railway's own extension
  allowlist, answerable by one `psql` predicate documented in the deployment guide.

## 7. Sign-off

**Not signed.** Three things are outstanding:

1. **A named reviewer who did not write this code.**
2. **An explicit acceptance of §4** — that items 7 and 8 pass by inheritance rather than by
   a fresh isolation suite against provider rows.
3. **The same unproved sentence SR-3 signed, again.** There is still no
   `project_members` table, so *"with per-project membership, counts do not leak the
   existence of a card in a project the caller cannot see"* remains unprovable on this
   deployment. `beta.2` adds a source type whose content comes from outside the
   deployment, which raises the stakes of that sentence without changing its status.

| Role | Name | Date | Signature |
|---|---|---|---|
| Reviewer — must not be an author of V2-E1 | | | |
| Accepting §4's inheritance argument | | | |
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
