# ADR 0033 — Five ways a result leaves a run, two stores that may name a verification command, and the gate a card passes to be done

- Status: **proposed** (2026-08-14) — waiting on gate two, which is a person's
  approval. Until it is accepted, `DV-02` onward may not touch `backend/`,
  `frontend/`, `daemon/` or `contracts/` (`plan/21/00-…md` §4). A document that
  marks itself accepted would make that gate meaningless.
- Date: 2026-08-14
- Amends: nothing. Three neighbouring ADRs gain amendments in their own files —
  ADR 0029 (amendment C, the `features` declaration), ADR 0031 (amendment B,
  `existing_pr` and the branch a run ends on), ADR 0032 (amendment A, the first
  code path that uses `provider_token`).
- Related: ADR 0028 (the board's one refusal — this document adds the second, and
  §5 explains why the two are different in kind), ADR 0029 (the run lifecycle; a
  run still never moves a card), ADR 0030 (artifacts are deliverables, logs are
  diagnostics — `delivery: artifact` depends on that distinction), ADR 0031 (the
  five hard push constraints, unchanged here and the reason §1's `existing_pr` row
  is narrower than it looks), ADR 0032 (SEC-002's revised invariant, which §3b
  relies on **without amending again**)
- Requirements: `FR-DELIVERY-001`…`-004`, `FR-PLAN-001`, `FR-VERIFY-001`…`-003`,
  `FR-EVIDENCE-001`, `-002`, `FR-AGENTTOOL-002`
- Contract: **v1.13.0** — and the interesting half is what it does **not** contain:
  `run.offer`'s `spec` gains no field at all (§3, §3b).
- Ships in: Central (minor), `agentd` **0.11.0**, frontend (minor).

## Context

By the end of V2.3 the platform could start a process on a node, hand it secrets,
and push a `cliora/…` branch. Two questions it still could not answer:

1. **In what form is this card's result supposed to leave?** The only shape the
   platform understood was "a branch was pushed, or it was not". A card whose
   outcome is a report, or a decision, or a diff nobody wants merged, had no way to
   say so.
2. **On what grounds is this finished?** A card reached `done` because somebody
   moved it there. An agent saying "complete" and a passing test suite were the same
   kind of fact to the platform: text.

This phase answers both, and each answer opens a surface the platform did not have.
The first opens **an outward side effect that is not git** — Central calls somebody
else's API and, with an identity that is not the person who dispatched the card,
leaves a pull request on their repository. The second opens **an execution
capability**: the daemon runs commands that are not the agent's runtime.

Three rulings were made before this document:

- **2026-08-08** — `source` and `delivery` are two independent fields (D21); the
  outputs are constrained rather than the sandbox (D25); an agent may deliver
  artifacts to a card (D29).
- **2026-08-13** — delivering git credentials is off by default. This phase's
  provider credential is **not** covered by that flag, because it travels a
  different path entirely (§3).
- **2026-08-14** — **verification commands come from two stores, not one** (§3b),
  and **`existing_pr` narrows to pull requests the platform itself opened** (§1).

## Decision

### §1 — `source` and `delivery` are two questions, and the answer to the second has five values

`source` asks *does this card need code, and which*. `delivery` asks *how does the
result leave*. They are separate columns because they are separate questions: an
investigation may need the code and produce no code, and a one-line fix may need no
checkout at all.

| `delivery` | The daemon | Central | The evidence that it is done |
|---|---|---|---|
| `none` | pushes nothing | does nothing | completion summary + verification report + the card's own thread |
| `artifact` | pushes nothing | **counts artifacts** | **at least one card artifact** + completion summary |
| `branch` | pushes `cliora/<card_ref>-<run_seq>` | does nothing | a branch link + a diff summary |
| `pull_request` | pushes the same branch | **opens the PR after the push is confirmed** | a PR link + a diff summary, **or** an explicit "no changes" |
| `existing_pr` | pushes to `base_branch`, which **must already be inside `cliora/`** | comments on the PR | the appended commits + the PR link |

**`artifact` is not the ability to attach one.** Any run may attach an artifact at
any time — that is ADR 0030 and it is unconditional. `delivery: artifact` declares
something else: *the deliverable for this card is a file, not a change to the code*.
A `pull_request` card may attach twenty screenshots while it works; attachments are
process evidence, `delivery` is the shape of the result.

**`existing_pr` is narrower than its name (2026-08-14).** ADR 0031's first hard
constraint is that the platform pushes only inside `cliora/`, and a pull request
somebody opened by hand has a head branch that is not. So this mode continues **the
platform's own** pull requests and nothing else, and a card declaring otherwise is
**refused at dispatch** rather than at the push — refusing at the push would spend
the whole run first. The alternative was to relax the constraint so that the card
names the branch; that is rejected in §Alternatives, and the short form of the
reason is that it turns "where can the platform push" from a constant into a
database column, six weeks after a security review approved the constant.

### §2 — Three honesty rules

These are part of the decision, not commentary on it.

1. **A card that declared no code changes and produced some does not discard
   them.** The result says "this card declared no code delivery, but N files
   changed", **and the diff is attached as an artifact**. The run directory is
   reclaimed on a schedule; without this rule that work vanishes and nobody ever
   learns it existed. The rule covers `none` **and** `artifact` — the first
   implementation covered both in the attach path and only `none` in the sentence
   that explains it, which is the failure mode this rule is about.
2. **No changes, no pull request.** `delivery: pull_request` with an empty diff is a
   **successful** run whose result is "no changes", and **the provider API is never
   called**. The acceptance test asserts the call count, not the absence of a PR:
   "no PR exists" is trivially true on a machine with no network.
3. **A card that declared `artifact` and produced none did not finish.** Declaring a
   deliverable and not delivering it is not completion. **This is decided by
   Central**, at `run.complete`: artifacts arrive over HTTP, so the daemon does not
   know how many there are and a check written there would always pass.

### §3 — Central opens the pull request; the daemon never learns that PRs exist

Two consequences, and the second was not the goal but is worth more than the first.

**`provider_token` is never delivered to a node.** It is already excluded from
delivery (`services/secrets.py`), and this document records why that is permanent:
the five hard constraints bind the daemon's *push path*. A credential that can write
to a repository over HTTPS is not reachable by any of them. Central holds it,
decrypts it in the background worker, and uses it there.

**Therefore `delivery: pull_request` and `existing_pr` are Central's intent, not the
node's instruction.** On the wire both appear as `branch`. The daemon is told to push
a branch; what happens afterwards is not its business — it has no provider
credential and could not act on the knowledge.

That falls out as a compatibility property the phase would otherwise have had to buy:
**`run.offer` gains no new value and no new field**, so a node running the previous
`agentd` keeps working. This matters more than it sounds. The daemon validates
`run.offer` with `DisallowUnknownFields`, and a validation failure produces **no
reply at all** — not a decline, not an error. An unrecognised value would mean the
card is claimed, the offer silently vanishes, the lease expires, the card is retried
to exhaustion and blocked, with no error anywhere. The rule this phase adopts, and
ADR 0029 amendment C generalises, is: **central→node compatibility is not
permissive, and new content in `spec` requires the node to have declared support for
it first.**

**The PR is opened outside the receive loop.** `run.complete` arrives on the socket
that also carries interactive terminal bytes; a 20-second HTTP call there stops
somebody's terminal for 20 seconds. `finish()` records the intent and a background
worker performs it — the same rule `services/runs.py` already documents for
`registry.request()`.

**A creation is not retried.** A timeout may mean the request arrived and the reply
did not; retrying opens a second pull request. A timeout is therefore a failure and
the run is marked `delivered_branch_only`.

**Failing to open the PR does not fail the run.** The branch is pushed and the work
exists. The result records `delivered_branch_only` with a readable reason, and a
person can open it by hand.

### §3b — Two stores may name a verification command, and `origin` records which one did (2026-08-14)

The daemon runs verification commands inside the run directory and reports their
real exit codes. That is what makes `machine_verified` mean anything.

Where the commands come from was specified twice and inconsistently — `research/02/01`
D10 said the card declares them, `research/02/06` DV-04 said the project's settings
do. **The ruling is both**, so the question becomes what keeps the level honest:

> **`machine_verified` means the executor did not choose what to run.** It does not
> mean "the command came from a particular table."

Both stores satisfy that sentence, because of one decision:

| Store | Column | Authorising action |
|---|---|---|
| the project | `projects.verification_commands` | `project.manage` (Admin) |
| the card | `tasks.verification_commands` | **`task.approve`** |

**`task.approve` rather than `task.update`, and that is the whole of it.**
`RUN_TOKEN_SCOPES` is `{project.view, task.update}`, and `services/agent_auth.py`
records that `task.approve` is precisely the half a run credential can never hold —
the two actions are held by the same people on purpose, and were separated for token
scope rather than for role separation. So a person may declare a check on a card and
**an agent may not**. This is not a type check on the principal; it is the boundary
that already exists.

Neither store is a request payload, so **SEC-002's revised invariant is untouched**:
no request payload may name a command or carry a secret's value. A card's list is a
column, written by an authorised request and read back by Central from its own
database — structurally identical to the argument ADR 0032 §1 made for
`spec.secrets`.

**`origin` is a second axis, not a third level.** `source` answers *who observed
this*; `origin` answers *who chose to run it*. They are orthogonal, and collapsing
them into one enum was a simplification the two-store ruling exposed. Both origins
render in the same style, because their credibility is equal; `origin` appears
beside them in words, because the reviewer's next question after "a machine ran it"
is "who set the standard".

**Commands are argv arrays and never a shell string**, in both stores, with the same
validator. A shell string is an injection path, and it would sit on the platform's
own storage surface. The card store makes this stricter rather than looser: it is
the easier of the two to change.

**The cost, stated rather than footnoted:** two cards in one project may now assert
completion against different standards. Three things converge that rather than
forbid it — `origin` is visible in four places (the report, the evidence list, the
run page, the PR body), a project may require at least one project-level check
(`require_project_verification`, **off by default**), and a metric reports the share
of card-declared checks. Off by default is deliberate: a switch that blocks people on
day one teaches them to stop using the feature it guards.

**If the card store is ever moved to `task.update`, the card-declared rows must be
downgraded to `agent_reported`.** Keeping the name while removing the property is
the one outcome this section forbids.

### §4 — Red line 5, written as paths that do not exist

Each row is verified by absence rather than by a check, because a check has a second
call site and a table does not contain a word.

| Not done | The form of its absence | Verified by |
|---|---|---|
| auto-merge | `merge`/`rebase` are not in the daemon's git verb table; no merge action exists on the provider adapter | `GATE-SC-PUSH-ARGV`, `GATE-DV-PROVIDER-VERBS` |
| approving our own PR | no review action on the adapter | `GATE-DV-PROVIDER-VERBS` |
| closing anyone's PR | no close action on the adapter | as above |
| tags, releases | in neither table | as above |
| running an arbitrary command on a node | no request field names a command; both stores are Central's own | a test that Central never reads commands from a payload, and a test that the card store requires `task.approve` |
| a sixth `delivery` | `DELIVERIES` is a closed set, and every value must have a branch in four places | `GATE-DV-DELIVERY-COVERAGE` |

The provider adapter has **three** actions: create a pull request, find one, comment
on one. `find` is in the table deliberately — "a PR already exists for this head" is
one of the four creation failures, and detecting it by parsing somebody's error
message is a path that breaks when they reword it.

### §5 — The Done Gate, and why it is a different kind of refusal from ADR 0028's

ADR 0028 said the board **refuses exactly one thing**: a card entering `ready` or
beyond with an unfinished dependency. Everything else reports. This document adds the
second refusal, and the distinction is worth stating because "the board refuses
things now" is the fastest way to make a board nobody writes to.

The dependency rule refuses a card **entering work**. The Done Gate refuses a card
**claiming to be finished**. The first is about whether work can start usefully — a
judgement the platform can be wrong about. The second is about whether a claim is
supported — and the platform holds every fact involved.

Six conditions:

```text
✅ a completion summary exists
✅ every acceptance criterion has a result        ← the four values are closed for this
✅ a verification report exists
✅ no unhandled critical failure                  ← "handled" = named as a remaining risk
✅ every dependsOn is done                        ← ADR 0028
✅ the delivery evidence that this card's mode implies
```

Three notes that are decisions rather than details:

- **"Every criterion has a result" required closing the value set.** It was a free
  string, so the check would have passed on any text at all. Existing rows whose
  value is not one of the four become `not_verified`, and the migration prints how
  many it changed.
- **"Handled" means somebody said they accept it**, not that it was fixed. A failing
  check listed in `remaining_risks` has been handled. Defining it as "fixed" would
  block every card behind a known environment problem, and people would route around
  the gate — which is the failure this gate exists to avoid.
- **The gate has one entrance.** A run does not move a card, and a test asserts that
  `services/runs.py` never assigns `task.stage`. Without it, somebody eventually adds
  a helpful "advance the card when the run succeeds", and the gate is bypassed by a
  door nobody thinks to check.

**`--force` exists, and it is Admin-only with its own action.** `task.force_done`
rather than a reuse of `task.approve`: approving one review gate and skipping the
completion criteria are not the same authority. A reason is required, it is stored
on the card as well as on the timeline — a timeline entry scrolls away, and "this
card was forced" must be visible whenever the card is — and it cannot be cleared on
its own. The only way to remove it is to move the card out of `done` and take it
through the gate.

**There is no `--force` in the `cliora` CLI, and there will not be.** The reason is
the one already recorded for the absent `approve` subcommand: a subcommand that
exists invites an agent to try it, and what it gets back is a 403 it must then
interpret.

**Process configurability cannot reach the Done Gate.** A project may disable
readiness items, disable gates, and adjust WIP advice. The six conditions are not in
`process_definitions` — they are constants in the service layer. Otherwise the first
person who finds the gate inconvenient turns it off, and turning it off leaves no
trace, while `--force` leaves three.

## Consequences

- **The platform now leaves a mark on somebody else's repository under an identity
  that is not the dispatcher's.** The pull request's author is whoever owns the
  provider token. The PR body says so on its last line, an audit row records the
  creation, and the run page links it — because the people reading that PR do not
  have Cliora accounts and the platform owes them a way to trace it.
- **Central makes outbound HTTP for the first time.** A host allowlist defaulting to
  `api.github.com` alone, connect and total timeouts, no retries, at most two
  creations in flight, and a bounded backlog that surfaces rather than accumulates —
  a queue nobody can see becomes fifty pull requests the moment the provider
  recovers.
- **The daemon gains an execution capability that is not a runtime.** It is bounded
  to the run directory, to argv arrays from two platform-side stores, without a
  shell, with a per-command and a whole-group timeout, and — because the group runs
  after the agent exits and inside the same wall clock — it is skipped **with an
  explanation** when too little of that clock remains.
- **A verification command's output can carry a secret**, and does not, because the
  redactor wraps the outbound frame rather than the log sink. That was V2.3's
  decision and this phase is the first thing to benefit from it without asking.
- **Three tables are append-only and nothing enforces it in the database.** Plans,
  reports and evidence have no update path, and a gate scans for one, because
  append-only is their only integrity property and it has no other trace in the code.
- **A disagreement between what the agent reported and what git observed is
  stored twice.** The platform shows both with their sources and does not adjudicate.
  Implementing this costs nothing; the reason it is written down is that adding a
  reconciliation check is the natural instinct, and its verdict would be a judgement
  nobody owns.
- **GitLab is refused at dispatch, not at delivery.** An unsupported host stops the
  card before the work happens.
- **`existing_pr` will look like a bug** to somebody who tries to point it at a
  hand-made pull request. Three places say so in words: the dispatch refusal, the
  card editor, and the release note.

## Alternatives rejected

| Option | Why not |
|---|---|
| **The daemon opens the pull request** | `provider_token` would have to be delivered to the node, where the agent's sandbox can reach it and none of the five hard constraints apply to an HTTPS request. It also costs the compatibility property in §3: `delivery` would need two new wire values, and every un-upgraded node would silently drop those offers |
| **Adding `pull_request`/`existing_pr` to the wire and requiring nodes to upgrade** | The failure mode of an old node meeting a new value is silence, not a version error. This would have been the first phase to make an un-upgraded node fail invisibly, and node updates are opt-in |
| **Deciding compatibility from `nodes.daemon_version`** | V2.3 already set the precedent in the other direction: capability is declared, not inferred. A version number says what shipped, not what is configured |
| **Relaxing the `cliora/` push constraint so `existing_pr` can continue any branch** | It would turn "where can the platform push" from a compiled-in constant into a database column, weeks after a security review approved the constant. If it is ever wanted, it needs its own review, not a widened field |
| **Dropping `existing_pr` entirely this phase** | Considered, and closer to honest than a half-built mode. Rejected because the loop it serves — an agent revising its own pull request after review — is the loop V2.5 depends on most |
| **Adding `spec.verification` as a new field** | The receiving decoder rejects unknown fields and answers nothing. The existing `allowed_verification_commands` field was added in V2.2 for exactly this, and an old daemon ignores a non-empty value instead of dropping the offer |
| **Verification commands declared only in project settings** | Rejected 2026-08-14. It makes a per-card check impossible without editing settings that apply to every card, and the flexibility was asked for |
| **Verification commands on the card, authorised by `task.update`** | The agent being verified would choose what verifies it. Every exit code would still be real and every one would be worthless, and `machine_verified` would have to be renamed |
| **A shell string instead of argv** | Convenient, injectable, and stored on the platform's own surface. `sh -c` would also make the "no pipelines, split them up" explanation unnecessary — which is exactly the convenience that makes it dangerous |
| **Retrying a failed pull-request creation** | Creation is not idempotent. A timeout that actually arrived becomes two pull requests |
| **Letting the agent choose `delivery`** | It is the card's intent, not the executor's choice — the same shape of error as letting the verified party choose the verification |
| **`merge` as a sixth delivery mode** | Red line 5. `version2.md` §13 lists it as not built, and §4 above makes its absence checkable |
| **Recomputing `origin` on Central instead of echoing the daemon's** | Central can look it up and would get a different answer whenever somebody edits either store mid-run. A value that travels with its result cannot drift from the command that produced it |
| **Making the Done Gate configurable per project** | The first person who finds it inconvenient would disable it, and that leaves no trace. `--force` leaves three, and a metric counts them |
| **Requiring a project-level check from day one** | It would block cards in every project that has not configured verification yet, and teach people that card-declared checks are pointless. Off by default, with a metric to decide later |
| **A reconciliation rule for contradictory evidence** | The platform would be issuing a verdict on which of two sources to believe, with nobody accountable for it. Show both, name both sources |
