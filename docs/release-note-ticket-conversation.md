# Release note — `v2.0.0-alpha.2`: ticket-native agent conversation

- Phase: V2-C1 (`CV-`) plus its closeout (`CE-`), ADR 0035/0036/0037/0041, PRD §8.17
- Ships: Central (minor), `agentd` **0.13.1**, frontend (minor)
- Contract: **v1.13.0, unchanged — not one byte**
- Migration: `0040_ticket_conversation`, additive, reversible
- Flags: `CLIORA_PROJECTS_ENABLED`, `CLIORA_AGENT_RUNS_ENABLED` (both from earlier phases)
- **Required configuration:** `CLIORA_PUBLIC_BASE_URL` — see Upgrading

> **`agentd` 0.13.1, not 0.13.0.** The closeout ran a full lifecycle against a real
> daemon for the first time and found that **no run on a card without a git remote could
> report that it finished**: the completion frame carried `git_remotes: null`, Central
> dropped it for failing validation, and the run sat there until its lease expired. The
> defect is older than this phase — 0.12.0 has it too — and it had no test because
> nothing had ever run a run to the end against a daemon. Fixed here; **nodes must be on
> 0.13.1** for that card shape.

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
`agentd` 0.12.0 already speaks.

**On upgrading nodes, two sentences that used to be one.** Nothing *about conversation*
requires a node upgrade — a 0.12.0 node is offered a continuation, claims it, runs it and
lets its agent ask questions, and this was measured rather than argued
(`artifacts/cv/local/compat-0120.json`). What a 0.12.0 node cannot do is **report that a
run finished**, on any card whose run directory has no git remote. That is the pre-existing
defect in the header, and it is why the minimum node version for this release is 0.13.1.

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
| Central | **1763** tests |
| frontend | 686 tests |
| daemon | green |
| Gates | 8 phase gates ＋ **3 closeout gates**, all PASS (`scripts/cv/gates.sh`, `scripts/cv/gate_closeout.py`) |
| **Journeys** | **7 of 7 executed and passed** — J1a, J3, J7 in a browser; J5, J6, J8, J9 as scripts. `artifacts/cv/local/journeys/` |
| **answer → next turn starts** | **P95 4.97s**, worst 4.98s, against the target of 10s — 20 samples |
| Un-upgraded 0.12.0 node | **Measured**, not argued: the wire is compatible, completion is not (see the header) |
| message commit P95 | 8ms (target 500) |
| conversation reopen P95 | 5ms (target 500) |
| cursor pagination P95 | 28ms (target 300), depth 500, pages of 200 |
| 20 concurrent writes | 0 errors, 0 gaps in the sequence |

The last four are on the fixed dataset (`scripts/cv/seed-dataset.py`, seed
20260819: 200 cards, one of them carrying
500 messages). They are **not** exit conditions —
they exist so `beta.1` has something to be a regression from.

The latency splits the way the phase predicted, and the split is more useful than the
figure:

```text
answer commit            median 0.013s   ← Central
queued → claimed         median 4.921s   ← the runner's 5-second poll
claimed → child started  median 0.013s   ← the runtime
```

**Essentially all of it is the poll interval**, which is the evidence D44 asked for: the
decision to leave the contract alone and let continuations ride the existing
`runner.poll` costs about half the poll interval on average and nothing else. If that
becomes too slow, the lever is the interval or a notification path — not Central.

## Known limitations

Ten. Each is a decision, a measurement that is not yet possible, or a defect this
release found and chose not to fix — and which one it is, is said in each case.

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

6. **A node below 0.13.1 cannot report that a run finished** on a card whose run
   directory has no git remote — every `source: none` card, which is every clarification
   card. This is now measured rather than argued
   (`artifacts/cv/local/compat-0120.json`): the old node is offered the run, claims it,
   asks its question and is offered the continuation, and never fails to decode a frame.
   It just never says it is done, and the lease expires three minutes later. The defect
   predates this release; the fix is in it.

7. **Asking for changes does not start a new round.** Accepting or rejecting a spec
   proposal writes a `decision`, and a decision resumes nothing — only an answer to a
   question does. After "要求修改" a person has to dispatch the card again. ADR 0035's
   state machine draws that edge, and nothing implements it; how it *should* work is a
   product decision (when does a half-typed reason start a run?) rather than a bug fix.
   `beta.1`.

8. **The conversation panel does not update itself.** It loads when the card opens and
   after you write something; there is no polling and no notification, by decision
   (`CV-06`, no WSS). Waiting for an agent's question means reloading the page.

9. **A run's context pack needs `CLIORA_PUBLIC_BASE_URL` to be set.** It is where the
   `API：` line comes from, and the CLI inside a run has no other source for the address.
   Unset, every `cliora task …` in a run reports the platform as unreachable while the
   platform is answering the daemon perfectly well. `compose.yaml` already refuses to
   start without it; a hand-rolled deployment can still get this wrong.

10. **The run DTO does not expose the continuation chain.** `turn_seq` and
    `parent_run_id` are stored and used, but not returned, so no screen can say "this is
    round three". `beta.1`'s Drawer will need them.

## Security

`docs/security-review-v2c1.md`. No new credential (`RUN_TOKEN_SCOPES` is byte-identical),
no new RBAC action, audit records metadata and never a message body, and secret values
declared for a card are redacted **before** a message is stored.

SR-1's two open findings were both verification gaps, and both are now closed by
execution rather than by argument: the seven journeys ran (exit conditions 5 and 11) and
the 0.12.0 lifecycle ran (exit condition 16). **The review's sign-off block is still
empty** — signing it is a person's act, and the closeout's job was to leave nothing for
them to take on trust.

## Upgrading

```bash
alembic upgrade head        # 0040_ticket_conversation
```

Existing questions are backfilled with the rule V2.5 already used ("any later message
from a person answered it"), so no card changes its mind about what is unanswered
across the upgrade. The migration is reversible; `GATE-CV-MIGRATION-ROUNDTRIP` asserts
that downgrading restores the schema byte for byte.

**`CLIORA_PUBLIC_BASE_URL` must be set**, and it is what a run's `cliora` calls back to.
`compose.yaml` refuses to start without it and the Railway pre-deploy check fails a bad
value, so a deployment on either path already has it; a hand-assembled one may not, and
the symptom is an agent reporting the platform as unreachable while the platform is fine.

**Nodes: upgrade to 0.13.1.** Two separate reasons, and only the second is new:

| | |
|---|---|
| 0.13.x's CLI | `messages --after`, `wait`, `say --reply-to`, `propose-spec`. A 0.12.0 agent has none of them — its `cliora` reports `unknown flag`, which is not a compatibility problem, just an older toolbox. |
| **0.13.1's fix** | Below it, a run on a card with no git remote never reports completion (limitation 6). This is the reason the upgrade is required rather than merely useful. |

Everything on the wire is unchanged, and that half was measured: a 0.12.0 node is offered
a continuation, claims it, runs it and lets its agent ask a question, with no decode
failure anywhere (`artifacts/cv/local/compat-0120.json`).

## Compatibility manifest

```text
Central          this commit (v2 branch; ahead 64 / behind 6 of master — NOT mergeable as-is)
agentd           0.13.1          minimum for a node: 0.13.1 (see Upgrading)
contract         v1.13.0         byte-identical to v2.0.0-alpha.1
migration head   0040_ticket_conversation   (downgrades to 0039, schema byte-for-byte)
PostgreSQL       16              no new extension
RBAC actions     27              unchanged (older planning documents say 24; the code has
                                 had 27 since before this phase)
Feature flags    CLIORA_PROJECTS_ENABLED, CLIORA_AGENT_RUNS_ENABLED
                 CLIORA_PROJECT_EXPERIENCE_V2 does **not** exist yet — it arrives in beta.1
Required config  CLIORA_PUBLIC_BASE_URL, CLIORA_SECRET_MASTER_KEY (runner mode)
```

## Feature flag matrix

| `PROJECTS` | `AGENT_RUNS` | Behaviour |
|---|---|---|
| `false` | anything | V1: every `/api/projects/*` and `/api/agents/*` route answers 404, and the console has no Projects tab. Asserted by `scripts/pj/gate-flag-off.sh` and by the `projects=false` CI leg. |
| `true` | `false` | The board works; dispatch answers 404. **The conversation API still reads and writes** — it is mounted on the project router, not the agent one — so people can talk on a card with no agent to wake. Reasonable, and previously never written down. |
| `true` | `true` | Full `alpha.2`, and what the seven journeys run against. |

## Data retention

| Data | Kept | Removed by |
|---|---|---|
| `task_messages` (comments, questions, answers, proposals, decisions, system events) | **Permanently** (ADR 0041) | Project deletion only |
| `task_questions` | Permanently | Project deletion |
| `conversation_consumers` | Permanently; one row per consumer, bounded | Project deletion |
| `task_runs`, including continuations | Existing run retention | The retention sweep |
| `run_logs` | 14 days, unchanged | The existing sweep |

A card's conversation is the record of why it was built the way it was, so it does not
expire; a run log is a diagnostic, so it does. Exit condition 12 — delete every log and
re-read the thread — is the assertion that keeps those two apart.

## Rollback

```bash
alembic downgrade 0039_requirements_agent_driven
```

`GATE-CV-MIGRATION-ROUNDTRIP` asserts the schema returns byte-for-byte. What is **lost**
on the way down:

| Dropped | Consequence |
|---|---|
| `task_questions` | Which questions were open, who answered them and when. The questions themselves survive as messages. |
| `conversation_consumers` | Every consumer cursor resets; an agent re-reads from the start once. |
| `task_messages.conversation_seq` and the idempotency key | Pagination falls back to timestamps, and a retried write can produce a duplicate message again. |
| `task_runs.parent_run_id` / `turn_seq` / `input_from_seq` / `input_to_seq` | The continuation chain. Each turn becomes an unrelated run. |
| `tasks.waiting_for_actor` / `open_question_count` | The projection. Nothing displays it yet, so nothing on screen changes. |

**No message is lost** in either direction. Downgrading loses the *structure* around the
conversation, never the conversation.

## Evidence

Everything above is reproducible with two commands:

```bash
scripts/cv/evidence.sh              # tests, make check, 8 + 3 gates
E2E=1 scripts/cv/evidence.sh        # and the stack: 7 journeys, 0.12.0, 5 measurements
```

Outputs land in `artifacts/cv/local/` (git-ignored, uploaded by the `conversation` CI
leg): `journeys/*.json`, `answer-to-turn.json`, `conversation-perf.json`,
`compat-0120.json`, `dataset.json`, `environment.txt`, `playwright.json`.

`GATE-CE-EVIDENCE-FRESH` refuses to accept any of them if they were produced at a
different commit — the failure it prevents is a number from two weeks ago being quoted as
this release's.

## Sign-off

| What | Who | Date |
|---|---|---|
| SR-1 security review (`docs/security-review-v2c1.md` §6) | Repository owner — provenance recorded in that section | 2026-08-21 |
| ADR 0035 / 0036 / 0037 / 0041 → `accepted` | Repository owner; ADR 0035's block also ratifies the work done while it was `proposed` | 2026-08-21 |
| `v2.0.0-alpha.1` annotated tag at `f91d9c4` | Created locally | 2026-08-21 |
| `v2.0.0-alpha.2` annotated tag | Created locally, on the closeout commit | 2026-08-21 |
| Pushing either tag, and the GitHub pre-release | **Not done.** Both publish, and publishing is a separate decision from tagging: `git push --tags` and the release page are outward-facing, and a tag that has been pushed cannot be quietly corrected. |
| `v2` → `dev` merge proposal | **Not part of this release.** Green exit conditions earn the right to propose it; a person decides, and no automation may perform it (`research/03/00` §8). |
