# ADR 0040 — Four state faces, and the two attention levels that are not in the database

- Status: **accepted** (2026-08-27) — with SR-3, recorded from the repository owner's
  instruction of 2026-08-27. Adopted as `plan/26`'s D92, D102 and D107 on 2026-08-23.
- **An amendment is owed and does not exist yet.** §1's stage projection is a stated
  transition, not an end state: `stage='blocked'` still projects onto blocked regardless
  of `tasks.is_blocked`, because three writers set the stage and not the column. `beta.2`'s
  `HD-06` either repays that or records that it will not — and **either outcome must appear
  here as an amendment** (`plan/27/01-…md` D123 and D139). Its absence is `beta.2` exit
  condition 3, so that "nobody mentioned it again" cannot become the answer.
- Date: 2026-08-23
- Amends: ADR 0028 (**amendment C** — §1 there made `tasks.stage` the board's single
  axis; this keeps the column and stops it carrying four questions at once).
- Related: ADR 0029 §1 (a runner has no stored online state — §2 below is that rule
  reaching the read model), ADR 0033 (the Done Gate's one entrance, which §3 protects),
  ADR 0035 §8 (`waiting_for_actor`, the projection this reuses rather than re-derives).
- Requirements: `FR-WORK-001`, `-002`, `-003`.
- Contract: **v1.13.0, unchanged.** Nothing here reaches the wire.
- Ships in: Central (minor), frontend. `agentd` **0.14.1, zero diff**.

## Context

`tasks.stage` has six values — `backlog blocked ready implementing verify done` — and by
V2.4 it was answering four different questions at once:

> How far has this work got? Is the card executable? What is the agent doing? Does a
> person still owe it a decision?

The clearest symptom is `blocked`. A card moved there loses its position in the work: the
board can no longer say whether a blocked card had been started, and moving it back is a
guess. Worse, **the platform is the thing that writes it** — `run_reaper.py` twice (lease
expiry, retries exhausted) and `runs.py` once (a question unanswered for 24 hours) — so
the loss happens to cards nobody touched.

The second problem is the one this phase actually collided with. `beta.1` wants
"why does this card need me" as a first-class, filterable, countable fact. Eight levels
were specified. **Two of them cannot be columns**, and the reason is written down in the
module that owns them:

```python
# services/runners.py — module docstring
# A runner has no online state of its own. There is no `status` column and no
# `last_seen_at`: a runner is online exactly when its node is… A stored copy would be a
# second answer that can go stale, and this module deliberately does not create one
# (ADR 0029 sec 1).
```

`no_eligible_runner` and `assigned_runner_offline` are decided by
`NodeConnectionRegistry`, a `dict[UUID, NodeConnection]` in the Central process. The
upstream plan offered two options — compute them in a LATERAL join, or materialise them
into `tasks.attention_primary` — and **neither works**. Materialising is exactly the
stale second copy ADR 0029 §1 refuses: a node disconnecting writes no row, so the column
stops at the answer from before the disconnect, and keeping it correct means fanning out
an update to every queued run's card on every connect and disconnect. Joining does not
work either, because the input is not in SQL at all.

## Decision

### 1. Four orthogonal faces, all projected, none stored

| face | values | derived from |
|---|---|---|
| work lifecycle | `backlog ready in_progress review done` | `tasks.stage` |
| readiness | `draft needs_clarification ready` | `tasks.readiness` against the **effective** process |
| execution | `task_runs.status`, or `not_queued` | the newest active run, else the newest run |
| human decision | `not_required pending approved` | `tasks.gates` against the **enabled** gates |

**No new column stores any of these.** `0043` adds `is_blocked` and three neighbours
because being blocked needs a reason and a message that the stage cannot carry — but the
four faces above are computed on read, for the same reason ADR 0029 §1 gives about
runners: a stored projection is a second answer that goes stale.

`blocked` projects onto lifecycle `ready` **and** `is_blocked = true`. Being blocked is
its own face, so a blocked card keeps a position in the work instead of losing it.

Two projections are unconditional, and both exist because the legacy writers are still
there:

- **`stage='blocked'` is always blocked**, even when the column says otherwise. The three
  platform writers above are not changed in this phase, so the column and the stage can
  disagree, and the stage was written by the thing that knew.
- **`stage='done'` is never blocked.** A finished card is not waiting on anything, and
  the backfill can otherwise leave that pair behind.

Both rules disappear when `beta.2`'s `HD-06` moves the three writers. Until then they are
the repayment plan, not a bug.

### 2. Attention is evaluated in two phases, and the split is visible in the API

```text
phase A — SQL, one query, filterable / groupable / countable
  1 waiting_for_your_input    open_question_count > 0 AND execution = waiting_for_input
  2 pending_human_approval    lifecycle = review AND human_decision = pending
  3 verification_failed       newest report result in (failed, partial)
  4 run_failed                newest run status = failed
  7 dependency_blocked        blocking_count > 0
  8 over_wip_or_stale         untouched past the threshold, or the lane is over WIP
  ── and the queued candidate set

phase B — Python, one runner query and one registry snapshot, over the queued set only
  5 no_eligible_runner
  6 assigned_runner_offline
```

Level 2 carries a condition the specification did not have: **only in review**. Every
card starts with six unapproved gates, so "any gate unapproved" would mark the entire
board, and a badge that is always on is a badge nobody reads. A card reaches review
precisely when it is asking somebody to look.

Three consequences are accepted, and each is a cost rather than a detail:

1. **Levels 5 and 6 cannot be sort keys.** They are not in SQL. The order-by allowlist
   therefore does not contain them, which is where this decision is observable from
   outside.
2. **Under more than one worker process they are per process.** Central runs a single
   uvicorn worker today (`Makefile`, and the compose file agrees), which is the only
   reason this is currently harmless. It is recorded as an open measurement rather than
   solved, because solving it means the stored copy ADR 0029 §1 refuses.
3. **Absent is not false.** When no registry was consulted, levels 5 and 6 are missing
   from the signal set and the response says so. "We did not look" and "we looked and
   there is a runner" are different facts; a caller that cannot tell them apart will
   eventually render the second when it means the first. The two runtime-dependent quick
   filters are therefore shown disabled with a reason, never as zero rows — zero rows
   reads as *fixed*.

Phase B's cost is bound to the dispatch queue, not to the board. Measured on the fixed
dataset (200 cards): 0.222 ms at 6 queued and 0.261 ms at 60. Ten times the queue for
1.18 times the time — the cost is dominated by the single runner query, which is flatter
than the decision assumed.

**Phase B and the console must agree.** `resolve_runtime_signals` (a page) and
`RunService.resolve_waiting_reason` (one card) apply the same four predicates in the same
order and are pinned together by one test on a shared fixture. The failure that pairing
prevents is the console saying "no machine has `docker`" beside a card the board calls
"waiting" — the same class of drift `GATE-SC-TAG-BOTH-QUERIES` already guards between the
SQL and Python tag matchers.

### 3. There is one ordering, and the frontend renders it

`ATTENTION_ORDER` is a tuple in `services/work/attention.py` and the browser does not
rebuild it. The order is by **what a person can do about it now**, not by severity:

| | level | why here |
|---:|---|---|
| 1 | `waiting_for_your_input` | the only state one sentence clears — and it is burning a lease while it waits |
| 2 | `pending_human_approval` | also waiting on a person, but nothing is stalled |
| 3 | `verification_failed` | there is a conclusion and it is bad |
| 4 | `run_failed` | there is no conclusion; a retry may be enough |
| 5 | `no_eligible_runner` | a configuration problem; the card is not degrading |
| 6 | `assigned_runner_offline` | the same, but more likely to fix itself |
| 7 | `dependency_blocked` | waiting on another card, which has attention of its own |
| 8 | `over_wip_or_stale` | a trend, not an event |

A card shows its **primary level and a count**, never the full set (D107). The full list
is in the card detail. Eight badges on a card is a wall of warnings; one badge and "＋2"
is a sentence.

### 4. `changes_requested` is not emitted, because nothing can write it

The specification listed a fourth human-decision value. `tasks.gates` stores
`{gate_key: {approved_by, approved_at}}` and un-approving **removes the key**, so "a
reviewer asked for changes" and "nobody has looked yet" are the same row. A value the
data cannot distinguish is a name in a document that no code can produce — the mistake
`plan/25` §2.12 made with `CROSS_PROJECT_DENIED` and `plan/26` D97 avoided with
`STAGE_TRANSITION_REFUSED`. Restoring it needs a schema change and a decision about what
un-approving means, which is another question.

## Consequences

**Good.** One function answers "how is this card doing" for six screens, and it is a pure
function of a row — measurable (0.08 ms for 200 calls), testable without a database, and
impossible to fork by accident. A blocked card keeps its position in the work. The two
runtime levels are honest about being per-process and about not being sortable, rather
than being a column that is quietly wrong after a restart.

**Bad.** Attention cannot be indexed, so a future "sort by attention" needs six of the
eight levels or a different design. Two of the levels are only as correct as the process
that answers the request, and a second worker breaks that silently — the mitigation is a
recorded measurement, not a guard. The two unconditional stage projections mean the
`is_blocked` column is not the whole truth about being blocked until `HD-06` lands, and
anyone reading the column directly will be wrong about the cards the reaper touched.

**Rejected: materialise `attention_primary`.** It requires withdrawing ADR 0029 §1,
fanning out card updates on every node connect and disconnect, and accepting that every
card's attention is wrong after a Central restart until the next fan-out. The column is
never created, and `0043` does not reserve it — a reserved column is one somebody fills.

**Rejected: return `null` for levels 5 and 6.** Then My Work loses its "no eligible
runner" section and the board loses two quick filters, which is the differentiating
argument of the whole phase.
