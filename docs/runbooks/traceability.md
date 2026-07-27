# Requirement traceability runbook

## Purpose

Diagnose and repair ADR 0019 registry, selector, generated-document, impact, and release-evidence
failures. Traceability tooling is development/release infrastructure; it never runs in the
product request path.

## Local reproduction

```bash
scripts/trace validate --level static
scripts/trace validate --level selectors
scripts/trace coverage --scope all --baseline traceability/baseline-debt.json
scripts/trace render --check
uv run --project backend python -m pytest scripts/traceability/tests -q
```

`make traceability` runs the same set. `make traceability-coverage-strict` is the
separate readiness probe for full release blocking; it is advisory until the debt
list empties.

## Criterion classification

Not every PRD bullet is an acceptance criterion. Each carries a `classification`
(`plan/06/02` §3 Pass B):

| Classification | Meaning | Coverage |
|---|---|---|
| `criterion` | A decidable claim | Needs its own primary `verified_by` |
| `data_shape` | A field or enum member of another criterion's payload | Absorbed; must name `covered_by` |
| `constraint` | A bound belonging to another criterion | Absorbed; must name `covered_by` |
| `example` | Illustrative only | Absorbed; must name `covered_by` |
| `needs_rewrite` | The PRD text cannot be decided as written | Blocking; no test may claim it |

Rules the validator enforces: an absorbed bullet must name a `covered_by` inside
its own requirement, that parent must itself be a `criterion` and active, and an
absorbed bullet may hold no `verified_by` of its own. Reclassifying is a
requirement-semantics change — it needs the product and test owners named in
ADR 0019 §6, and `review.approved` stays `false` until they have signed off.

## Baseline debt

`traceability/baseline-debt.json` is the finite, named list of criteria the
changed-scope gate tolerates. It is checked in both directions: a gap that is not
listed fails, and a listed entry that is no longer a gap also fails, so the file
cannot quietly grow back into a backlog. It is **not** a waiver — nobody has
accepted these, and no expiry has been agreed. Full release blocking turns on
when `entries` is empty.

## Producing a release snapshot

```bash
scripts/traceability/dogfood.sh artifacts/traceability/<run-id>
```

It refuses to start on a dirty tree, runs the gates this runner can satisfy,
records the rest as skipped with the missing prerequisite, merges the shards and
resolves them. To assemble shards from separate CI jobs by hand:

```bash
scripts/trace run-gate GATE-DAEMON-RACE --run-id "$RUN" --out shards/daemon.json
scripts/trace merge shards/*.json --run-id "$RUN" --out gate-results.json
scripts/trace snapshot --results gate-results.json --commit HEAD --out trace-snapshot.json
```

`merge` refuses shards that disagree on commit, tree state, gate-definition hash
or runner profile, and refuses the same gate twice.

## Environment legs

A gate that declares an `environment` matrix must have every leg accounted for in
its result, as `executed`, `skipped` or `not-applicable`. Emitters default an
unnamed leg to `skipped`, so pass `--environment webkit` for each leg that really
ran. A passing gate with an unexecuted leg yields `environment-incomplete`, never
`verified`: a Chromium-only run does not verify a WebKit criterion.

## Schema or duplicate ID

1. Read the JSON pointer in the finding.
2. Validate the object against `traceability/schema/`.
3. Never renumber or reuse a merged requirement/criterion ID.
4. If a criterion was split, deprecate it and add new IDs plus `supersedes/refined_by`.
5. Re-run static validation and render.

Do not edit `docs/traceability/*.md`; they are generated.

## Missing source anchor

1. Locate the normative heading/criterion in `research/prd.md` or `research/tech.md`.
2. Preserve the existing `<a id="..."></a>` when rewording or moving text.
3. If the semantic criterion was removed, use lifecycle/supersession rather than deleting the ID.
4. Run `scripts/trace render --write` and review the generated text/link.

## Missing or renamed selector

1. Use the locator in `traceability/links.json`.
2. Confirm whether the test was renamed, deleted, or ceased to assert the criterion.
3. Rename-only: update the locator in the same PR.
4. Deleted assertion: add replacement verification or leave an explicit blocking gap.
5. Run selector validation and the owning gate.

A different test in the same file is not automatically replacement evidence.

## Generated-document drift

Run:

```bash
scripts/trace render --write
git diff -- docs/traceability
```

Review the source registry and generated diff together. If output is non-deterministic, fix the
renderer; do not normalize it by hand.

## Unknown product impact

`scripts/trace impact` reports changed product paths not covered by reverse links.

1. Identify the affected FR/SEC/NFR/SCOPE criteria.
2. Add or correct `implemented_by` links and required verification.
3. If genuinely non-behavioral, record the rationale in the PR and obtain component-owner review.
4. Security-sensitive paths cannot use author-only `no requirement impact`.

## Stale, dirty, or mismatched evidence

- Commit mismatch: run the gate on the release commit; never rewrite the result SHA.
- Dirty tree: commit the intended changes and rerun.
- Gate definition hash mismatch: rerun with the current `gates.json`.
- Artifact digest mismatch: treat the run as invalid and regenerate it.
- Mixed shards: reject the merge; all shards must have the same commit/profile.

## Skip and manual evidence

A skip names a missing runner prerequisite and is not pass. Required skips need a separate
release decision/waiver. Manual evidence is allowed only for `manual_external` criteria and must
record procedure version, actor/reviewer, RFC 3339 UTC instant, commit, environment, result, and
artifact digests.

## Waiver

- Maximum: one release or 90 days, whichever comes first.
- Required: impact, compensating controls, owner, two approvers, expiry, revisit trigger.
- Critical/High boundary findings are not waivable.
- Closing a waiver requires current passing evidence; retain the closed record.

## Tool defect

If the tool itself produces false positives or corrupt output:

1. Keep schema/duplicate/broken-anchor protection active where possible.
2. Temporarily set the affected coverage stage to report-only; do not set criteria to pass.
3. Save the failing input and add a regression test.
4. Fix and rerun before restoring blocking mode.

Traceability failure must not lead to weakening outbound-only WSS, runtime allowlists,
allowed-root containment, content redaction, non-root execution, or any other product boundary.
