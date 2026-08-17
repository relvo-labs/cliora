# ADR 0036 — Conversation delivery: cursors, idempotency, and at-least-once without duplicate work

- Status: **proposed** (2026-08-16), together with ADR 0035.
- Date: 2026-08-16
- Related: ADR 0035 (the nouns; this document is its delivery half), ADR 0029 §2
  (`claim()` — the same single-statement race argument), ADR 0030 (run logs are a
  different medium with different guarantees).
- Requirements: `FR-CONV-001`, `-004`, `-005`.
- Contract: **v1.13.0, unchanged.**
- Ships in: Central (minor), `agentd` **0.13.0** (CLI only).

## Context

Once a conversation outlives the process reading it, "who has read what" stops being
a property of that process's memory and becomes data. The failure modes change shape
accordingly: nothing crashes, and either a message is never acted on, or it is acted
on twice.

Acting on it twice is the expensive one. A duplicated continuation means a second
agent turn: a second set of LLM calls, possibly a second push, and two replies to one
question in a thread a person is reading.

## Decision

### 1. The database is the source of truth; nothing is a queue

There is no in-memory delivery structure anywhere in this design. A consumer's
position is a row (`conversation_consumers`), a question's state is a row, a turn's
input range is two columns on the run. Central may restart between any two steps and
every party recovers by reading.

### 2. Delivery is at-least-once; de-duplication is the consumer's, keyed on `seq`

Cursor reads (`?after_seq=`) are naturally idempotent: re-reading a range returns the
same rows because the sequence is monotonic and gapless per card (ADR 0035 §2). A
consumer that crashes mid-turn re-reads and re-processes; nothing is lost and nothing
needs an acknowledgement to be correct.

`last_acked_seq` therefore **controls nothing**. It exists so the UI can say
`agent_seen`, and it is a diagnostic. A flow that waited for an ack would stall
whenever an agent died between reading and acknowledging — which is exactly the case
the design is supposed to survive.

`CHECK (last_acked_seq <= last_delivered_seq)` makes the meaningless ordering
unrepresentable. The `CONVERSATION_CURSOR_AHEAD` error guards the other direction: a
caller presenting a cursor beyond the card's own sequence has broken state, and
returning an empty page would leave it stuck there permanently with no signal.

### 3. Writes are idempotent by unique index, not by read-then-write

`uq_task_messages(task_id, idempotency_key)` partial index. On violation the existing
row is loaded and compared:

| | response |
|---|---|
| same `body` + `kind` + `reply_to` | **200** with the original message |
| different content | `409 MESSAGE_IDEMPOTENCY_CONFLICT` |

Read-then-write double-writes when two requests arrive together. This is the same
conclusion the search index reached for the same reason, and it is worth stating as a
rule rather than a case: **in this codebase, uniqueness is enforced by an index and
handled on violation; a pre-check is an optimisation, never the mechanism.**

One deliberate exception, in the answer path: the idempotency key *is* checked before
the question CAS. Not for correctness — losing the race there produces a 409 whose
details carry the existing answer, from which the caller recovers — but because
"replay returns the original result" is a better answer than "replay conflicts", and
only a pre-check can give it.

### 4. The key is a content hash, not a UUID

The CLI derives `sha256(run_id + kind + body)[:32]`.

An agent's retry is usually *the whole command run again*, not the same HTTP request
resent. A fresh UUID per invocation would make every retry a new message — an
idempotency key that is never the same twice is not one. The browser, whose retry
*is* a resend, generates a UUID once per composition instead.

### 5. Exactly one continuation per question, enforced by the database

```sql
CREATE UNIQUE INDEX uq_task_runs_continuation
  ON task_runs(parent_run_id, resumed_question_id)
  WHERE parent_run_id IS NOT NULL;
```

The CAS in ADR 0035 §3 already serialises answers, so this index should never fire.
That is the point: the counter behind it (`cliora_conversation_duplicate_turn_total`)
is expected to stay at zero, and a non-zero value means a code path reached
continuation without going through the CAS. There is no other symptom of that bug —
the system would keep working, and someone's agent would answer twice.

Alerting threshold is **greater than zero**, not a rate.

### 6. Nine stable machine codes

```text
QUESTION_ALREADY_PENDING      409   (existing, re-homed from a message scan to a table)
QUESTION_ALREADY_ANSWERED     409   details: answered_by, answered_at, answered_message_id
QUESTION_NOT_OPEN             409   details: state
RUN_NOT_WAITING_FOR_INPUT     409
CONVERSATION_CURSOR_AHEAD     409   details: current seq
MESSAGE_IDEMPOTENCY_CONFLICT  409   details: existing seq
TURN_ALREADY_QUEUED           409   details: run id
MESSAGE_TOO_LARGE             400   details: limit, actual
AGENT_CANNOT_DECIDE           403
```

`QUESTION_ALREADY_ANSWERED` carries enough for a UI to say *who* answered and *when*,
and to offer a jump to the reply. Two people answering the same question is a normal
event in a team, not an error state, and the loser of that race should end up reading
the answer rather than reading "operation failed".

`MESSAGE_TOO_LARGE` replaces a Pydantic `max_length` rejection. A 422 has no machine
code, so a client cannot distinguish "too long" from any other validation failure —
and the correct UI for the first is "your text is safe, shorten it", which is not the
correct UI for the others.

### 7. `--since` is deprecated for one release, not removed

Timestamp pagination is the defect (ties are unordered), so it cannot stay. But
`cliora task messages --since` may be embedded in an agent prompt or a wrapper
script, and the platform's own context pack never mentioned the subcommand, so the
exposure is small but not zero.

For one release: both parameters are accepted, `Deprecation`/`Sunset` headers are
returned, the CLI prints one line to stderr, and **supplying both is a 400**. Guessing
which the caller meant is worse than refusing.

## Consequences

Every conversation write path takes an optional idempotency key, and every read path
takes a cursor. The response shape of `GET /messages` changes from a bare array to a
page object — the one breaking API change in this phase, taken rather than adding a
permanent compatibility flag, because both consumers are in this repository and both
are modified in the same phase. `GATE-CV-NO-THIRD-CONSUMER` asserts that premise
rather than assuming it.

Two counters are expected to remain zero for the life of the release
(`duplicate_turn_total`, and `CONVERSATION_CURSOR_AHEAD` responses). They are worth
more as alarms than as statistics.
