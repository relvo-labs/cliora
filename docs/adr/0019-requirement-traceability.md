# ADR 0019: Requirement traceability and release evidence

Status: accepted (2026-07-27). Governs requirement identity, verification claims, evidence,
waivers, and generated traceability views. Implements `plan/06`.

## Context

Cliora has 59 top-level PRD requirements, 20 MVP acceptance conditions, 15 release-blocking
technical security controls, 32 research work packages, and 18 earlier ADRs. The implementation
and its tests are substantial, but their relationships are mostly prose. A file path in a phase
report proves that code or a test exists; it does not prove which atomic acceptance criterion ran,
on which commit, in which environment, or whether the result was skipped.

There is already a concrete consistency failure: `docs/p4-report.md` and `plan/05/07` refer to a
P4 per-requirement section 10 in `research/01/06-requirement-traceability.md`, while that document
ends at section 9. Existing evidence scripts correctly distinguish executed gates from skipped
ones, but do not emit a requirement-resolvable machine manifest.

## Decisions

### Authority and scope

`research/prd.md` remains the product requirement authority. Accepted ADRs refine implementation
decisions and `research/tech.md` section 23 supplies additional release controls. In a conflict,
the PRD wins for product intent; an ADR may refine but not silently reduce it. A real conflict
requires a requirement change.

The registry covers:

- `FR-*`, `SEC-*`, and `NFR-*`;
- `MVP-AC-01` through `MVP-AC-20`;
- `TECH-SEC-01` through `TECH-SEC-15`;
- PRD section 4 non-goals as `SCOPE-*` guards.

Other technical and visual sections are design targets unless they are promoted through a
reviewed requirement change.

### Stable criteria

The smallest status unit is an acceptance criterion. Its ID is
`<requirement-id>.AC-<two digits>`. IDs are never reused or renumbered. Requirements and criteria
use stable Markdown/HTML anchors rather than line numbers. Initial atomization treats explicit
acceptance bullets and normative lists as criteria; broad prose-only requirements receive a
primary criterion. Future semantic splitting deprecates the old criterion and creates new IDs.

Requirement prose stays in its canonical document. `traceability/requirements.json` stores
identity, source anchor, owner, lifecycle, applicability, criticality, and verification profile;
it does not keep a second normative copy of criterion text.

### Not every imported bullet is a criterion

Mechanical atomization of the PRD produced 369 criteria, but many are field names, enum members,
or single numbers lifted out of a list — `Hostname`, `Codex`, `2 秒`. Treating each as a claim
that needs its own test manufactures work without adding assurance, and treating it as covered
because a broad suite exists manufactures the opposite. Each therefore carries a
`classification`: `criterion`, `constraint`, `data_shape`, `example`, or `needs_rewrite`.

Only `criterion` carries verification. `constraint`, `data_shape`, and `example` must name the
`covered_by` criterion that absorbs them, must be in the same requirement, may hold no
`verified_by` of their own, and their parent must itself be a `criterion`. `needs_rewrite` marks
PRD text that cannot be decided as written; it blocks and no test may claim it. Classifications
are recorded with the classifier, date, and rationale, and stay `approved: false` until the
owners in section *Owners and rollout* sign off. Reclassifying is a requirement-semantics change,
not editing.

### Claims, runs, and verdicts are separate

- `links.json` states typed claims from a criterion to plan, design, implementation, and exact
  verification targets.
- `gates.json` defines stable commands, environments, and artifact expectations.
- `gate-results.json` records what actually ran at a clean commit.
- `trace-snapshot.json` resolves claims and results for one commit/release.

Static links can make a criterion specified, planned, implemented, or verifiable. Only a valid
same-commit result can make it verified. Parent status is the worst required child status.
Skipped, stale, manual-pending, and waived are modifiers, never aliases for pass.

### Verification policy

- Functional criteria require implementation plus automated verification; cross-boundary
  behavior requires integration or E2E evidence.
- Security criteria and tech security controls require negative/adversarial verification.
- NFRs require a threshold, profile, environment, and measurement result.
- MVP conditions require their underlying FR/SEC coverage plus journey validation.
- Manual evidence is allowed only where the registry explicitly says `manual_external`; it
  records procedure version, actor/reviewer, UTC instant, commit, environment, observations, and
  artifact digests.

All instants are RFC 3339 UTC with an explicit `Z`. Durations use monotonic clocks inside runners.

### Waivers and skips

A waiver is release-scoped and expires at the earlier of 90 days or the next release. It records
impact, compensating controls, owner, approvers, and revisit trigger. It never hides the original
gap and cannot renew automatically. Critical/High security findings and the core command,
workspace-containment, credential, or content-leakage boundaries cannot be waived.

A skip describes a missing prerequisite. A required skip blocks release unless a separate,
approved release decision accepts it. The decision is not converted to pass.

### Owners and rollout

Long-lived team keys own requirements and links: `product`, `architecture`, `security`,
`central`, `daemon`, `frontend`, `test-infra`, `operations`, and `release`. Individuals may be
assignees but are not the sole durable owner.

Rollout has three explicit modes:

1. report-only for imported baseline debt;
2. changed-scope blocking for new or touched criteria;
3. full release blocking after baseline closure.

Schema errors, duplicate IDs, broken anchors/links, generated-document drift, and newly introduced
changed-scope gaps block from the first mode.

Mode 3 is in force as of 2026-07-27: every active criterion must carry its required links and
none may be awaiting a requirement rewrite. `traceability/baseline-debt.json` is empty and is still
checked in both directions, so an item cannot be added back without stepping the rollout down
deliberately and saying so.

Getting there required deciding three requirements rather than testing around them. FR-CONN-006
named a "general control command: 10 s" budget the relay never had and a 30 s file read where the
code says 15; FR-TERM-004 named a ring buffer in megabytes against a tmux scrollback measured in
lines. In each case the PRD was changed and the withdrawn criterion kept its ID as `deprecated`
with a `supersedes` link from its replacement — a deprecated criterion with no replacement is
refused, because otherwise the cheapest way to clear a gap is to withdraw the requirement.

### Repository format and retention

The source registry is JSON validated by committed JSON Schema. Generated Markdown is never
hand-edited. Release snapshots, result summaries, digests, manual sign-off, and decisions are
retained with the release. Raw logs and screenshots use CI retention and must not contain secrets,
terminal bytes, file content, or private absolute paths.

## Consequences

- Existing P0-P4 prose is historical evidence, not rewritten truth. Claims without a commit/run
  remain `historical_claim` until a new observed run replaces them.
- Initial mapping may expose missing or overly broad tests. The honest state is a gap, not an
  invented link.
- Requirement and test renames acquire intentional friction because their anchors/selectors must
  remain resolvable.
- A percentage is informational only; one blocking security criterion still blocks at 99%.
- Rejected: a production database table for traceability, a SaaS ALM dependency, YAML with
  implicit typing, line-number links, manually maintained pass tables, and waiving missing
  security evidence into a green status.
