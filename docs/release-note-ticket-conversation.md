# Release note — `v2.0.0-alpha.2`: ticket-native agent conversation

- Phase: V2-C1 (`CV-`), ADR 0035/0036/0037/0041, PRD §8.17
- Ships: Central (minor), `agentd` **0.13.0** (CLI subcommands only), frontend (minor)
- Contract: **v1.13.0, unchanged — not one byte**
- Migration: `0040_ticket_conversation`, additive, reversible
- Flags: `CLIORA_PROJECTS_ENABLED`, `CLIORA_AGENT_RUNS_ENABLED` (both from earlier phases)

## What this adds

**A conversation on a card no longer depends on a process staying alive.**

Before this release, an agent that asked a question had exactly one way to stay in the
conversation: not exit. It posted the question and then kept polling `cliora task
messages`, holding a lease and a `max_waiting` slot for up to 24 hours. The moment the
process ended, `run.complete` marked the run `succeeded` and the card was done — with an
unanswered question sitting in the thread.

```text
Agent 問一個問題  → 行程可以直接結束
                    run 收成 succeeded / result=awaiting_input
                    「在等人」搬到 task_questions 上，租約與 compute 釋放
人在卡片上回覆    → 「回覆並繼續」
                    一個 continuation run 進佇列，沿用第一輪的分支名
                    Agent 讀得到完整對話與這一輪的新訊息範圍
```

The conversation lives in the database, so it survives the process, a daemon restart,
and the deletion of every run log.

## What it deliberately does not add

**No new outward side effect, no new execution capability, no new credential, no
contract change, and no new RBAC action.** A continuation is an ordinary queued run: it
reaches a node through `runner.poll` → `run.offer` → `run.accept`, all of which
`agentd` 0.12.0 already speaks. **A node does not have to be upgraded.**

The phase's only new risk is one of delivery semantics — that one sentence gets acted on
twice, or that an ordinary remark is read as approval. Every gate in it is shaped around
those two sentences.

## New

| Area | What |
|---|---|
| Conversation | `conversation_seq` per card: a monotonic message number, so paging is by cursor and never by timestamp |
| Questions | `task_questions`: a question is a row with a life (`open` → `answered` / `expired` / `cancelled`), not an inference over message order |
| Answering | `POST /tasks/{id}/questions/{qid}/answer` — closes the question, records the answer and queues **at most one** continuation, in one transaction |
| Idempotency | Every message write takes a key. The same key with the same body writes one row; with a different body it is refused |
| Turns | A continuation is a child run: `parent_run_id`, `root_run_id`, `resumed_question_id`, and the input range it must read |
| Branches | A continuation pushes to the **root run's** branch, so two turns of one card do not land on `-2` and `-3` with the PR pointing at one of them |
| CLI (0.13.0) | `cliora task messages --after <seq>`, `cliora task wait`, `cliora task say --reply-to --kind`, `cliora task propose-spec`. `--since` is deprecated |
| Console | A real message thread, a question card with two actions, per-message delivery state, and a composer whose draft survives a failed send |
| Proposals | An agent proposes a specification; a person accepts, or requests changes with a reason. Only the person's decision moves readiness |

## Changed behaviour (read this one)

**A run can now finish while its card is still waiting.** `run.complete` on a run with
an open question stores `status='succeeded'` with `result='awaiting_input'`. The status
is unchanged on purpose — the run did finish normally; it is the *card* that is waiting,
and that is now `tasks.waiting_for_actor`, a column, rather than something each screen
worked out for itself.

**An ordinary comment still unblocks an agent that is still running.** This was not in
the plan and is the one rule that changed during implementation. Under the new rules a
question stays open until somebody answers it, and a person who replies with a plain
comment rather than "reply and continue" would leave a live agent permanently unable to
ask anything else — it holds one open question forever. So a comment closes the question
**when the asking run is still parked and polling**, and does not when that run has
ended. A comment never creates a turn, either way (ADR 0037, D67).

**`GET /tasks/{id}/messages` returns a page object** (`items` plus a cursor) rather than
a bare list. All three consumers in this repository are updated.

## Verified

| | |
|---|---|
| `make check` | green |
| Central | 1762 tests |
| frontend | 686 tests |
| daemon | green |
| Gates | 8, all PASS (`scripts/cv/gates.sh`) |
| **answer → next turn starts** | **P95 5.00s**, worst 5.59s, against the target of 10s — 20 samples, `artifacts/cv/local/answer-to-turn.json` |

The latency splits the way the phase predicted, and the split is more useful than the
figure:

```text
answer commit            median 0.014s   ← Central
queued → claimed         median 4.912s   ← the runner's 5-second poll
claimed → child started  median 0.016s   ← the runtime
```

**Essentially all of it is the poll interval**, which is the evidence D44 asked for: the
decision to leave the contract alone and let continuations ride the existing
`runner.poll` costs about half the poll interval on average and nothing else. If that
becomes too slow, the lever is the interval or a notification path — not Central.

## Known limitations

Six, and each is a decision or a measurement that is not yet possible, not an omission.

1. **A late answer does not start a turn.** After 24 hours an unanswered question
   `expire`s and the card goes `blocked`. A reply that arrives afterwards is recorded in
   the thread — nothing is lost — but it does not resume anything: the action offered is
   "dispatch again", and that run reads the whole conversation from the beginning. The
   three possible fixes all need to know how often expiry actually happens, and on a
   single-person deployment that number means nothing.

2. **A continuation does not inherit the previous turn's uncommitted working tree.**
   Isolated run directories are per-run (`FR-AGENT-011`), so a new turn is a new
   directory. Clarification cards are unaffected. For implementation cards it depends on
   how often an agent stops to ask mid-edit, and that count is currently zero.

3. **There is no `POST /conversation/resume`.** Continuing without an answer would start
   a turn whose input range is empty — an agent reading nothing new. The action that is
   actually wanted is "dispatch again", and it already exists.

4. **A person cannot edit or delete a message.** Append-only, asserted by
   `GATE-CV-APPEND-ONLY`. Messages are retained permanently: a card's conversation is
   the record of why it was built this way. Run logs remain the diagnostic data, and
   they are still the ones that expire.

5. **Two of the six metrics are counters short of what they should be.**
   `answer_to_turn_seconds` and `turns_per_task` are histograms that need a real agent
   on a real workload; the four counters ship. The number in "Verified" above comes from
   the measurement script, not from a histogram in production.

6. **The compatibility claim for un-upgraded nodes is argued, not exercised.** Two gates
   assert that `contracts/v1/` and the daemon's node half are byte-identical, and a
   continuation uses only messages 0.12.0 already handles. What has not been run is one
   full lifecycle against an actual 0.12.0 binary. See `docs/security-review-v2c1.md`
   §3.1.

## Security

`docs/security-review-v2c1.md`. No new credential (`RUN_TOKEN_SCOPES` is byte-identical),
no new RBAC action, audit records metadata and never a message body, and secret values
declared for a card are redacted **before** a message is stored.

The review is published **unsigned**: its two open findings are limitation 6 above and
the unexercised end-to-end journeys, both of which are exit conditions of this phase.

## Upgrading

```bash
alembic upgrade head        # 0040_ticket_conversation
```

Existing questions are backfilled with the rule V2.5 already used ("any later message
from a person answered it"), so no card changes its mind about what is unanswered
across the upgrade. The migration is reversible; `GATE-CV-MIGRATION-ROUNDTRIP` asserts
that downgrading restores the schema byte for byte.

**Nodes do not need to be upgraded.** `agentd` 0.13.0 adds CLI subcommands an agent may
use; a 0.12.0 node runs continuations without knowing they are continuations.
