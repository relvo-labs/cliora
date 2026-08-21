# ADR 0035 — A Ticket is a durable conversation; a run is one replaceable execution of it

- Status: **accepted** (2026-08-21) by the repository owner, recorded by the closeout
  session from their instruction to complete `plan/24` — **not** an independent review
  meeting, and said so here because a status line is exactly the place a later reader
  would assume otherwise.
- **Ratification of work done while this was `proposed`.** The superseded status line read:
  *"proposed (2026-08-16) — waiting on a person's approval. Until it is accepted, `CV-03`
  onward may not touch `backend/`, `frontend/` or `daemon/`."* That order was not
  followed: the implementation landed in `e777674`…`ac3dfef` while this ADR was still
  proposed. The acceptance above ratifies it. It is kept as a recorded **process
  deviation** rather than tidied away, because the sentence it broke is the only thing
  the deviation can be measured against (`plan/24/01` D74).
- Date: 2026-08-16
- Amends: ADR 0029 (**amendment E**, a run may end while the card is still waiting,
  and a run may have a parent), ADR 0030 (**amendment A**, the log/artifact
  distinction gains a third member: a *message*), ADR 0034 (**amendment A**, the
  one-open-question rule moves from a message scan to a table).
- Related: ADR 0028 (the session token that never resolves into a `User` — a run
  token inherits that property here), ADR 0031 (the isolated run directory —
  unchanged, and §7 records what that costs a continuation), ADR 0032 (secrets — a
  continuation re-runs the refusals, §6), ADR 0033 (five delivery shapes — a
  continuation adds no sixth and inherits the branch, §5).
- Requirements: `FR-CONV-001`, `-002`, `-003`, `-006`, `-008`.
- Contract: **v1.13.0, unchanged — not one byte.** §4 is why that is possible rather
  than merely desirable. `GATE-CV-CONTRACT-FROZEN` is what stops it drifting.
- Ships in: Central (minor), `agentd` **0.13.0** (CLI subcommands only; the node half
  has a zero-byte diff), frontend (minor).

## Context

V2.5 gave the platform a way for an agent to ask a person a question and for the
person to answer on the card. It works, and it has one structural limit that is easy
to miss because nothing reports it:

**the conversation only survives while the agent's process does.**

The mechanism, as built:

1. `cliora task ask` posts a message with `kind='question'` and returns immediately.
2. Central sets `task_runs.status = 'waiting_for_input'` and starts a 24-hour timer.
3. The agent keeps polling `cliora task messages` until an answer appears.
4. If the agent instead exits, the daemon sends `run.complete`, and `finish()` sets
   `status = 'succeeded'` unconditionally. **The card is now done, and the question
   nobody answered is a message in a list.**

So the only way to hold a conversation open is to keep an OS process alive for up to
a day, holding a lease and a `max_waiting` slot, on a machine the platform does not
own. A daemon restart ends it. A node reboot ends it. A crash ends it, and the card
looks finished.

Three smaller defects sit underneath that one:

- **Pagination is by timestamp.** `list_for(since=)` compares `created_at`, and two
  messages written in the same millisecond either repeat or vanish.
- **An answer is not linked to its question.** `pending_question()` treats *any* user
  message written after the question as the answer. That rule is defensible for a
  human reading a thread — and it makes "did this specific question get answered"
  unanswerable by the database.
- **There is no idempotency key.** A retried POST is a second message.

None of these is a bug in what V2.5 built. They are the consequences of building a
comment thread and then asking it to be an execution input.

## Decision

### 1. Three nouns, and only one of them is durable

```text
Ticket   a durable work item and a durable conversation      platform fact
Run      one controlled execution                            replaceable
Turn     one run's response to a range of the conversation   replaceable
```

A Ticket outlives any number of runs. A run may fail, be lost, be retried, be
cancelled, be reclaimed by a different runner, or end while the card is still
waiting — **and none of those may lose a message.**

This makes the log/artifact distinction of ADR 0030 into a three-way one:

| | lifetime | source of truth for |
|---|---|---|
| **run log** | expires (3 days / 14 days) | diagnostics |
| **artifact** | follows the card, never expires | deliverables |
| **message** | **never expires** | *what was said* |

A message is never parsed out of a log, and a log is never rendered into the thread.
`GATE-CV-NO-LOG-IN-THREAD` asserts the second half in the frontend; the first half
has no code to guard because there is none to remove — but the exit criterion
"delete every `run_log` row for a card and the conversation is intact" is the
machine form of the sentence.

### 2. A per-card monotonic sequence, held on the card

`tasks.conversation_seq` is a counter; every message takes its number in the same
transaction that inserts it:

```sql
UPDATE tasks SET conversation_seq = conversation_seq + 1
WHERE id = :task_id RETURNING conversation_seq;
```

Rejected alternatives, and why:

| | rejected because |
|---|---|
| PostgreSQL `SEQUENCE` | globally monotonic but **holed per card**; a rolled-back insert consumes a number, so a cursor cannot tell "nothing new" from "one was skipped" |
| `SELECT max(seq)+1` | duplicates under concurrency; adding `FOR UPDATE` locks the message table instead of the card |

The chosen form locks the card row — which the write was going to touch anyway,
because `tasks.updated_at` has `onupdate`. `uq_task_messages(task_id,
conversation_seq)` is the backstop, not the mechanism: it exists so that a future
second writer fails loudly instead of quietly renumbering.

### 3. A question is a row, not a pattern over messages

`task_questions` has four states (`open`, `answered`, `cancelled`, `expired`) and
carries the two message ids. This replaces the message-scan rule of ADR 0034 §4 with
a single-row compare-and-set:

```sql
UPDATE task_questions SET state='answered'
WHERE id = :id AND state = 'open'
```

Zero rows affected is the conflict; one row is the go-ahead. **The whole of the
concurrency argument is that statement**, exactly as it is for `claim()` in ADR 0029
§2 — the race is closed inside one statement rather than narrowed across a handshake.

The one-open-question-per-run rule of ADR 0034 §4 **is kept** (`plan/23` D42). It is
what makes the CAS single-row; relaxing it turns "two of three answered, do we
resume" into a product question that no data currently answers.

Backfill preserves the old rule rather than the new one: every historical
`kind='question'` message gets a row, and whether it counts as answered is decided by
the V2.5 predicate (any later user message). A card must not change its mind about
answered questions because it was upgraded.

### 4. A continuation is a child run, so the wire does not change

When a person answers and asks to continue, Central creates a **new `task_runs` row**
with `parent_run_id` set, and that row is queued like any other. It is offered
through `runner.poll` → `run.offer` → `run.accept`, claimed by `claim()`, leased,
retried and cancelled by the code that already does those things.

This is the reason the contract does not move. The alternative the planning document
proposed — two new central→node notifications — costs more than it looks like:

- The daemon decodes with `DisallowUnknownFields` and dispatches message types
  through an exhaustive `switch`; an unknown type is a decode failure.
- The 1.13.0 changelog already records what that failure looks like from the outside:
  *the card is claimed, the offer vanishes, the lease expires, the card is retried to
  exhaustion and blocked, and nothing anywhere mentions compatibility.*
- So a new type needs a `runner.register.features` declaration, a version on both
  sides, and a fixture proving an undeclared node never receives it.

And it buys only latency. `runner.poll` runs every 5 seconds by default, so the
answer→turn path is bounded by that plus a claim plus a process start. The target is
**P95 < 10s**, and `plan/23/08-…md` §6 requires it to be recorded in three segments
so that a miss says which of the three to fix. If the first segment is the one that
misses, *that* is the evidence for a notification — not a prediction made now.

**Not `run_turns`.** A separate table would mean two lifecycles to keep in step, and
the UI has to collapse them into one thread either way. `task_runs` already has the
state machine, the lease, the retry counter, the log, the cancellation path and the
audit trail. `turn_seq` distinguishes "third round of conversation" from `attempt`'s
"third try at this round"; conflating them would make neither answerable.

### 5. A continuation inherits the root run's branch

`run_branch()` composes `cliora/<card_ref>-<run_seq>`. A card that delivers a pull
request and asks a question mid-run would, without this clause, push turn two to a
different branch than turn one — and the pull request points at the first.

`task_runs.root_run_id` is stored rather than walked, so the lookup is one `get()`
instead of a recursive CTE. The chain length is the number of conversation rounds; it
is single digits in practice, and storing the root is still cheaper than the query
that avoids storing it.

This adds no sixth delivery shape and changes no constraint in ADR 0031: the same
namespace, the same five compiled-in rules, the same refusal to touch a base or
protected branch.

### 6. A continuation re-runs the card's refusals

`dispatch()` checks three groups: ① can this card start (stage, dependencies, no
active run), ②a what the card's *kind* forbids, ② whether its declared secrets are
allowed and exist.

A continuation skips ① — the card is mid-flight by definition — and **re-runs ②a and
②**. The card is editable while it waits, and a clarification card that gained a
`required_secrets` entry between turns would otherwise carry a secret into a run
whose kind is refused one. That refusal (ADR 0034 §3) has never been bypassed, and
this is the one new execution path that could bypass it.

The two groups are extracted into `_assert_card_dispatchable()` and called from both
sites; `GATE-CV-CONTINUATION-REFUSALS` asserts the extraction held, in two layers —
statically that the six error codes are raised only there, and dynamically that both
call sites return the same code for the same violation. The static layer alone would
not catch a continuation that simply never calls it.

When the re-check fails, **the answer is still written**. It is what a person said;
a misconfigured card is not a reason to discard it. The continuation is refused, the
card gets a `system` message naming the reason, and the API returns 409.

### 7. What a continuation cannot inherit

The isolated run directory of ADR 0031 is per-run: `<state>/.cliora/runs/<run_id>/`.
A continuation is a new run id and therefore a new, empty directory. **Uncommitted
work from the previous turn does not carry over.**

For the two kinds that produce no code this is nothing. For an implementation card it
is real, and the answer is not a mechanism but a sentence in the context pack: commit
or push before asking. That sentence goes where the agent will actually read it — the
"how to report" section that `render_run_context` puts first — and the limitation is
recorded in `plan/23/09-…md` rather than being discovered later.

The alternative (reusing the parent's directory) would mean a run directory outliving
its run, which contradicts the quota and cleanup model ADR 0031 was written to
establish. It is not worth reopening for a case that has never been observed.

### 8. Six message kinds, and two of them are not writable by everyone

| kind | who may write | resumes | approves |
|---|---|---:|---:|
| `comment` | human ＋ runner | no | no |
| `question` | human ＋ runner | depends on target | no |
| `answer` | human ＋ runner | **yes**, with `resume` | no |
| `proposal` | **runner only** | no | no |
| `decision` | **human only**, needs `task.approve` | depends | **only for that proposal** |
| `system` | system only | no | no |

`message` and `event` — the V2.5 values — are read as `comment` and `system`. **No
migration rewrites them.** A whole-table `UPDATE` on a table that audit references,
in order to change a display string, is a worse trade than two lines of mapping at
the one place the DTO is assembled.

`decision` written with a run token is `403 AGENT_CANNOT_DECIDE` plus an audit row.
It would already fail, because `task.approve` is not in `RUN_TOKEN_SCOPES` and never
will be; the explicit refusal exists so the failure is legible and recorded rather
than generic.

## Consequences

**A run may now end while its card is still waiting.** `finish()` derives
`result='awaiting_input'` when the completing run left an open question. `status`
stays `succeeded`, because the run *did* finish normally — it is the card that is
waiting, not the run. Six places read run status (`ACTIVE_STATUSES`,
`LEASED_STATUSES`, the reaper's three sweeps, `active_for_task`); inventing a new
status value would require all six to learn it, and the first one that did not would
strand a card.

Two consequences follow, both handled in `plan/23/04-…md`:

- The `delivery: artifact` completeness check must skip `awaiting_input`, or every
  round of clarification records a complaint that is not true.
- The 24-hour sweep must key on the **question**, not on run status — otherwise a run
  that ended releases the timer along with the lease.

**Two kinds of waiting now exist** — a live process still polling, and a released one
— and they must not produce two answers. `tasks.waiting_for_actor` and
`open_question_count` are projections maintained in exactly one function, asserted by
`GATE-CV-PROJECTION-ONE-WRITER`. A second writer's first missed branch shows a card
that says "waiting for your reply" after the reply arrived, and nothing errors.

**A continuation may be claimed by a different runner.** There is no
`project_agents`, tags decide the machine, and `ORDER BY queued_at` is the only
ordering (ADR 0029 §3). This is what "the conversation is durable, the execution is
replaceable" actually looks like in the queue, and it holds only if the context pack
is self-sufficient — which is why §7's limitation is a limitation rather than a
detail.

**A continuation does not jump the queue.** Changing the ordering would contradict
ADR 0029's stated posture of no priority and no load balancing. Whether it should is
an open measurement, and the three-segment latency record is what will answer it.

## Alternatives considered

**Keep the process alive (status quo).** Requires a node to hold an OS process, a
lease and a capacity slot for up to a day, and loses the conversation on any restart.
It is the thing this ADR exists to stop.

**A long-lived PTY or a resumable vendor session id.** Both make correctness depend
on a runtime's own persistence. A vendor session id may be used as an optimisation
where it exists; it may not be the reason continuation works, because the platform
supports more than one runtime and must behave the same on all of them.

**A `run.pause` message from the daemon.** Honest and explicit, and it costs a
contract version plus a feature declaration plus an upgrade on every node — to tell
Central something it can already derive from its own database.

**A `run_turns` table.** Two lifecycles, one thread. Rejected in §4.
