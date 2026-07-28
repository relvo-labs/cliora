# Requirement traceability implementation report

Date: 2026-07-27
Decision basis: ADR 0019 and `plan/06`

## 1. Verdict

**Go. Full release blocking is on** (ADR 0019 rollout stage 3): `traceability/baseline-debt.json`
is empty, no criterion is missing a required link, and none is awaiting a requirement rewrite.

The imported baseline is closed. Every criterion that carries a claim of its own names the exact
assertion that proves it; every bullet that was never a claim says so and names the criterion that
absorbs it; and the three requirements that disagreed with the code have been decided in the PRD
rather than tested around.

A release still has to earn its verdict from a same-commit snapshot. The one produced here is
`blocked`, because eight of the fifteen gates cannot run on this machine — that is the system
working, not a caveat on the above.

## 2. Baseline

| Object | Count |
|---|---:|
| PRD FR/SEC/NFR requirements | 59 |
| MVP acceptance conditions | 20 |
| Tech security controls | 15 |
| PRD scope guards | 12 |
| Total registered requirements/controls | 106 |
| Atomic criteria (active) | 372 |
| — carrying their own claim (`criterion`) | 241 |
| — absorbed into another criterion | 131 |
| — awaiting a PRD rewrite | 0 |
| Withdrawn, superseded by a replacement | 2 |
| Statically verifiable | 241 |
| Blocking gaps | 0 |
| Active waivers | 0 |

Stable anchors were added to `research/prd.md` and tech §23. Requirement text remains canonical
there; the JSON registry stores metadata and anchors, not a second copy of normative prose.

## 3. What closed the 308

The first cut of this report recorded 308 criteria whose only verification was a file-level
"supporting" link to a whole test suite. Two different problems were hiding under one number.

**131 of them were never acceptance criteria.** Mechanical atomization turned the field lists,
enum members and single figures inside PRD bullets into criteria of their own — `Hostname`,
`Codex`, `Timestamp`, `2 秒`. `plan/06/02` §3 Pass B always called for classifying these; the
classification had not been done. Each now carries `classification` plus the `covered_by`
criterion that actually holds the claim, with the classifier and rationale recorded. The
validator refuses an absorbed bullet that names no parent, names a parent outside its own
requirement, names a parent that is itself absorbed, or keeps a `verified_by` of its own.

**171 were real claims with no exact assertion behind them.** Each now has one or more primary
`verified_by` links naming a specific test — `test_login_unknown_user_is_401_same_code`, not
`test_auth_api.py`. 242 such links were added. The broad suite links remain, as `supporting`.

Four assertions did not exist and were written rather than claimed:

- `TestReconnectBackoffScheduleMatchesThePRD` — the daemon reconnect schedule was implemented but
  never asserted, so it could drift to a flat 1 s retry with every test green.
- `retries on the full 1/2/5/10/30 second schedule` — the same gap in the browser client. Writing
  it exposed a fault in the WebSocket test double: it raised a second `close` event for an
  already-closed socket, which silently consumed a step of the retry schedule.
- `TestInstallLayoutMatchesTheDocumentedPaths` — the install layout FR-INSTALL-003 promises.
- `backend/tests/test_relay_timeouts.py` — the relay budgets FR-CONN-006 and FR-SESSION-005 put a
  number on.

## 4. How the last six closed

Three were missing behaviour and were built:

| Criterion | What was missing | What it does now |
|---|---|---|
| `FR-SESSION-005.AC-06` | `tmux.Client.Stop` ran one `kill-session`; nothing waited and escalated. | Sends SIGTERM to the pane process, waits the configured grace, and kills only if it is still there. The outcome is returned, logged, and carried in the `forced` field of `session.stopped` — which had been hardcoded `false`. |
| `FR-NODE-005.AC-04` | `set_enabled` accepted `terminate_sessions` and audited it while nothing acted on it. | Terminates each running session on the node, best effort, and records how many. A session that will not stop no longer strands the rest. |
| `FR-FILE-006.AC-04` | The file tree had no auto-refresh; the only `autoRefresh` belonged to the dashboard. | An opt-in toolbar toggle re-reads the expanded levels on a 10 s interval, one pass at a time, and stops with the session or the scope. |

Three were PRD text that could not be decided as written, found while looking for the assertion.
Product decided to change the requirements:

| Criterion | The disagreement | Resolution |
|---|---|---|
| `FR-CONN-006.AC-02` | No single "general control command" budget existed; the relay has one per operation and none was 10 s. | Withdrawn. FR-CONN-006 now names the eight budgets Central enforces, including the 180 s daemon update, which on a shared budget would time out on a healthy node. `AC-06`/`AC-07` supersede it. |
| `FR-CONN-006.AC-04` | PRD said a 30 s file read; `file_read_timeout_seconds` is 15. | Kept its ID — same claim, corrected number. The PRD now says 15 s. |
| `FR-TERM-004.AC-03` | PRD stated a 2–10 MB ring buffer as an alternative to tmux scrollback; MVP took the tmux route and the alternative was never built. | Withdrawn. `AC-04`/`AC-05` supersede it with the guarantees that can be held to: at least 5000 scrollback lines, and a 2 MB cap on the reattach snapshot, reported as truncated. |

The two withdrawals keep their IDs as `deprecated`, with a recorded rationale and a `supersedes`
link from the replacement. Static validation now refuses a deprecated criterion that has neither:
without that rule the cheapest way to clear a coverage gap is to withdraw the requirement, which is
a worse failure than the gap.

Writing a test around either side of a disagreement would have recorded the implementation as the
requirement. That is the failure this whole system exists to catch, so
`backend/tests/test_relay_timeouts.py` now transcribes the published table — and one of its tests
asserts the transcription is complete, so adding a relay timeout without publishing it fails.

## 5. Verification

The traceability suite covers unknown schema fields, duplicate IDs, missing anchors, target path
escape, missing selectors, missing primary links, non-waivable critical criteria, deterministic
rendering, stale commits, dirty trees, gate-definition mismatch, missing artifacts, artifact path
escape, required skips, and passing gates without an executed selector.

Three checks that `plan/06` §2 called for and nothing exercised were added:

- **Injection 7, browser matrix.** A gate that declares an environment matrix must account for
  every leg as `executed`, `skipped` or `not-applicable`; a leg it does not declare is refused. A
  passing gate with an unexecuted leg resolves to `environment-incomplete`, never `verified`, so a
  Chromium-only run cannot satisfy a WebKit criterion.
- **Injection 9, expired waiver.** A waiver past its window stops suppressing its gap on its own,
  without anyone remembering to revoke it.
- **Shard merge.** `trace merge` refuses shards that disagree on commit, tree state,
  gate-definition hash or runner profile, and refuses the same gate twice.

Local commands:

```text
uv run --project backend ruff check scripts/traceability
uv run --project backend python -m pytest scripts/traceability/tests -q
make traceability
make traceability-coverage-strict
```

At report creation: Ruff passes, 32 traceability tests pass, schema/static/selector/render checks
pass, and `make traceability` exits 0 under full release blocking —
`coverage --scope all --strict` is now the gate rather than a readiness probe.

## 6. Dogfood snapshot

`scripts/traceability/dogfood.sh` runs the gates the runner can satisfy, records the rest as
skipped with the prerequisite that is missing, merges the shards and resolves them. First run on
a clean tree at `48f1bd4`, run id `dogfood-48f1bd4`:

| | |
|---|---:|
| Validity errors | 0 |
| `verified` | 189 |
| `covered-by-parent` | 131 |
| `skipped` (gate not run on this runner) | 52 |
| `needs-rewrite` | 0 |
| `blocked-static` | 0 |
| **Verdict** | **blocked** |

Blocked is the correct answer, and it is what the design is for. Nothing is unresolved on paper any
more: every criterion either has current evidence, is absorbed into one that does, or names a gate
this machine cannot run. Seven gates ran here — static, backend unit, security, contract, backend
DB against a real PostgreSQL 16, daemon race, daemon integration under tmux, frontend unit — and
189 criteria are verified against results from this commit. The remaining 52 wait on the deployed
edge (`GATE-OPERATIONS`, 21), the browser matrix (`GATE-BROWSER-E2E`, 17), the capacity rig, the
measurement run, and the two manual procedures. Not one of them is reported as passing.

Two things were found by running it rather than by reading it. Reporting `GATE-BACKEND-DB` without
naming its `postgresql-16` leg resolved 46 DB-backed criteria to `environment-incomplete` — the
matrix check working as intended, on its own author. And the first run failed `GATE-BACKEND-UNIT`
and `GATE-SECURITY` because `CLIORA_TEST_DATABASE_URL` was set while `CLIORA_DATABASE_URL` was
not: the DB tests ran, but the application under test could not write its audit rows. That is an
environment fault, not a product one, and the snapshot surfaced it as a failing gate rather than
letting it pass quietly.

The pack lands in `artifacts/traceability/<run-id>/`, which is git-ignored in line with the other
evidence packs; the identity above is what a release decision cites.

## 7. Historical reconciliation

`research/01/06-requirement-traceability.md` now has sections 10–11 and routes current state to
generated views. P0 remains a historical No-Go, P1–P3 retain their conditional verdicts, and P4
remains Go subject to its recorded release conditions. No prose result was converted into
same-commit observed evidence.

## 8. Remaining adoption work

1. Obtain product and test-owner sign-off on the 131 absorbed-bullet classifications; they carry
   `review.approved: false` until then. The two withdrawals and the corrected file-read budget are
   marked approved, because changing the PRD was the decision.
3. Add machine reporter selector sets to every product gate shard, so `selectors` in a result is
   the list of assertions that actually executed rather than the list the registry expects.
   Today a gate reports the selectors the registry associates with it, which is why the snapshot
   has no `selector-unproven` rows: that check cannot bite until the reporters are wired.
4. Replace the repository-owner CODEOWNERS fallback with organization team handles when those
   teams exist. This is blocked outside the repository.

These are visible gaps, not accepted passes and not waivers.
