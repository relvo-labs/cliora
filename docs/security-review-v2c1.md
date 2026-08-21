# Security review — V2-C1 (ticket-native conversation)

- Date: 2026-08-19
- Scope: `CV-01`…`CV-13`, ADR 0035/0036/0037/0041, migration `0040`, `agentd` 0.13.0
- Reviewer: **to be signed off before the merge proposal** (§6)
- Method: `.agent/skills/cliora-security-review` — assets, actors, boundaries, entry
  points, then untrusted input traced through validation, authorization and execution

## 0. Which trigger this hits, and which it does not

`research/02/10` §6 names three triggers for a mandatory review. This phase hits one
and a half of them, and naming which is the shortest way to say what changed:

| | V2.4 | V2.5 | **V2-C1** |
|---|---|---|---|
| New credential | `provider_token` | none | **none** — `RUN_TOKEN_SCOPES` is byte-identical to `f91d9c4` |
| New storage surface | verification reports | specifications | **two tables** — `task_questions`, `conversation_consumers` |
| New execution capability | verification commands | none | **none in kind** — but a **new way for a run to come into existence** |
| Contract | v1.13.0 | unchanged | **unchanged** (`GATE-CV-CONTRACT-FROZEN`) |
| daemon node-side half | changed | unchanged | **unchanged** (`GATE-CV-TOUCH-LIST`) |

The half is the whole review. Before this phase every run was created by a person
pressing dispatch. After it, **a run can be created by a person answering a question**,
and the platform decides on their behalf that answering meant "carry on". Two things
can go wrong with that, and they are the two the phase is shaped around:

1. **the same sentence is acted on twice** — a duplicate continuation, a duplicate
   message, a duplicate push;
2. **an ordinary remark is read as a decision** — a `comment` resumes a run, an
   `answer` approves a gate, or an agent's `decision` is accepted as a person's.

## 1. The new surface

### 1.1 A run that no one dispatched

`RunService.enqueue_continuation` deliberately does **not** call `dispatch()`: two of
that method's step-① refusals are wrong here (the card is mid-flight so its stage is
not `ready`, and the run that just ended is the reason there is anything to continue).
The danger in that sentence is obvious — the refusals that *are* about the card must
not be skipped along with the two that are not.

- **Enforced structurally.** `GATE-CV-CONTINUATION-REFUSALS` parses
  `services/runs.py` and asserts that the card-level refusals are raised inside one
  shared function and that both `dispatch` and `enqueue_continuation` call it. A
  refusal added to one path in future cannot be added to only one path.
- **At most one turn per answer.** `uq_task_runs_continuation` is a unique index on
  `(parent_run_id, resumed_question_id)`. It is an index rather than a check because
  the failure it prevents — the agent replying twice — has no other symptom. Ten
  concurrent answers to one question produce one message and one run
  (`test_two_people_answering_one_question_produce_one_turn`).
- **A refused continuation does not lose the answer.** The route returns 201 with
  `mode="refused"` and a `system` message on the card. This is a deliberate reversal of
  the plan's 409 (`plan/23/10` §2.4): the answer *was* stored, and a status code that
  says "your request failed" while the body says "but we kept it" is the worse thing to
  hand a client.

### 1.2 Which actor may write which kind

| kind | a person | a run credential |
|---|---|---|
| `comment` | ✓ | ✓ |
| `question` | — | ✓ |
| `answer` | ✓ | — |
| `proposal` | ✓ | ✓ |
| `decision` | ✓ (`task.approve`) | **refused, `403 AGENT_CANNOT_DECIDE`** |
| `system` | platform only | platform only |

The `decision` refusal is **redundant on purpose**. `task.approve` is not in
`RUN_TOKEN_SCOPES`, so an agent's attempt already fails at the authorization layer.
What the explicit check adds is a legible code and an audit row: *a refusal nobody
records is a refusal nobody can review*
(`services/conversation.py::assert_kind_writable`).

Authorization for a person's `decision` goes through the existing `may_perform`
dependency rather than a `has_action` call in the route — `test_authorization_logic_is_
confined_to_two_modules` forbids the latter, and the boundary stays in two modules.

### 1.3 The credential cannot widen, and cannot reach sideways

- `RUN_TOKEN_SCOPES` = `{project.view, task.update}`. `git diff f91d9c4..HEAD --
  backend/app/services/agent_auth.py` is **empty**: the file was not opened this phase.
- A run credential is bound to one task. The pre-existing `_own_task` guard covers the
  new routes because they are mounted behind the same dependency; the regression is
  asserted in `backend/tests/db/test_run_credential.py`.
- A run credential cannot name an author. `author_user_id` is never read from an agent
  request body; the writer is the runner on that credential.
- A run credential cannot write a `decision` (§1.2), and cannot decide anything by
  writing a `proposal` either: a proposal is a message. There is no readiness write on
  any agent-reachable path.

### 1.4 Secrets in prose

The redactor that already shipped wraps the **daemon's** protocol `send`, so it covers
`run.failed` stderr and `run.complete` summaries. `cliora task say` is an HTTPS request
to Central and never passes through it — **the one channel an agent uses to write prose
was the one channel the redaction did not cover.**

`SecretService.redact()` closes it, and three properties of where it lives are load
bearing:

1. **In `secrets.py`.** `GATE-SC-SINGLE-DECRYPT` asserts exactly one module turns a
   stored secret back into plaintext. A helper elsewhere would make that two, for a
   convenience.
2. **Before the insert**, never after: storing the value is the thing being prevented,
   and `test_a_secret_value_is_redacted_before_it_is_stored` asserts against the stored
   row rather than the response.
3. **No audit row and no `last_used_at` stamp.** Nothing was delivered; the values were
   read in order *not* to store them. `materialise` remains the record of a delivery,
   and this must not add rows that look like one — the same test asserts `last_used_at`
   is still NULL.

Below eight characters a declared value is skipped: redacting the string `ok` out of
every message protects nothing and makes the thread unreadable.

### 1.5 What the audit log holds

`TASK_MESSAGE_POSTED` carries `card_ref`, `kind` and `conversation_seq` — **metadata
only**. The body stays on the card (ADR 0037 §5). A conversation that were also copied
into `audit_logs` would put product text into the one table whose retention is set by
compliance rather than by the product.

### 1.6 Growth and denial of service

| Bound | Value | Where |
|---|---|---|
| One message body | 20000 chars → `400 MESSAGE_TOO_LARGE` | `conversation.py`, with the limit and the actual length in `details` |
| Open questions per run | **one** (D42) | server-side 409, and the single-row CAS depends on it |
| An unanswered question | 24 hours, then the card goes `blocked` | `run_reaper._expire_waiting` |
| A parked run with no question | same sweep, separately | `run_reaper._expire_parked_runs` |
| Message retention | **permanent** (ADR 0041) | product data; run logs are the diagnostic data and are the ones that expire |

Permanent retention is a deliberate growth statement, not an oversight: a card's
conversation is the record of why it was built the way it was. The bound that matters
is the per-message one, and it is enforced.

## 2. The thirteen rows of `plan/23/08` §5

| ☑ | Review item | Verdict | Evidence |
|---|---|---|---|
| ☑ | run token cannot write `decision` | Pass | `test_a_run_credential_cannot_write_a_decision`; `AGENT_CANNOT_DECIDE` + audit row |
| ☑ | run token cannot read or write across tasks | Pass | `_own_task` unchanged; `test_run_credential.py` regression |
| ☑ | run token cannot name an actor | Pass | agent paths never read `author_user_id`; §1.3 |
| ☑ | Viewer cannot speak | Pass | `test_a_viewer_reads_the_thread_and_cannot_write` |
| ☑ | `comment` does not resume, `answer` does not approve | Pass | `test_a_comment_does_not_wake_an_agent` (20 comments, run count unchanged); the answer path never touches `tasks.gates`; `GATE-CV-APPEND-ONLY` |
| ☑ | an agent `proposal` does not move readiness | Pass | a proposal is a message; no readiness write exists on an agent-reachable path |
| ☑ | secret values do not reach a message, an error or telemetry | Pass | §1.4; metrics carry counts and labels (`kind`, `type`), never bodies |
| ☑ | audit holds metadata only | Pass | §1.5 |
| ☑ | body size bound | Pass | `test_message_too_large_is_a_machine_code` |
| ☑ | a continuation does not bypass a card refusal | Pass | `GATE-CV-CONTINUATION-REFUSALS` (AST) + the 201/`refused` path |
| **☑** | **an un-upgraded `agentd` 0.12.0 node behaves identically** | **Executed — and the answer is narrower than the claim** | §3.1, rewritten below |
| ☑ | `RUN_TOKEN_SCOPES` unchanged | Pass | empty diff against `f91d9c4` |
| ☑ | RBAC action count unchanged | Pass | `rbac.py` byte-identical to `f91d9c4`; no action added or seeded |

> The plan's prose says "24 actions". `len(ALL_ACTIONS)` is **27**, and has been since
> before this phase — the file is byte-identical to the baseline. The number in the
> planning documents is stale, not the code. Corrected here rather than in passing,
> because a review that repeats a wrong number teaches the next reader to trust it.

## 3. What this review does **not** claim

### 3.1 The 0.12.0 node — executed 2026-08-21, and the claim needed splitting

The original claim, "a node that is not upgraded behaves exactly as before", rested on
two static facts: `contracts/v1/` is byte-identical (`GATE-CV-CONTRACT-FROZEN`) and the
daemon's node-side half has a zero-byte diff (`GATE-CV-TOUCH-LIST`). The argument was
strong. It was also answering a slightly different question than the one that mattered.

**Executed** by `scripts/cv/compat-0120.sh` — `agentd` built from `f91d9c4`, enrolled
beside the current node, aimed with a tag so which node claims what is determinate rather
than raced. Evidence: `artifacts/cv/local/compat-0120.json`. Two halves, and they do not
have the same answer:

| | |
|---|---|
| **The wire** | Compatible, and now demonstrated: the old node is offered a run, claims it, launches its agent, the agent asks a question, the answer produces a continuation, the old node is offered *that* and claims it too. **No decode failure in its log**, which matters because a dropped frame produces no error anywhere — it looks like a card going blocked. |
| **Completion** | **Not compatible.** A 0.12.0 node cannot report that a run finished on any card whose run directory has no git remote — every `source: none` card. Its `run.complete` carries `git_remotes: null`, Central drops the frame for failing validation, and the run sits in `running` until the lease expires. |

The second half is **not something this phase broke**: the defect is in V2.2-era code and
0.13.0 shipped with it too. It had no test because nothing had ever run a run to
completion against a real daemon — Central's integration tests call `finish()` directly
with a hand-written payload, and the phase's own latency measurement stopped at
`started_at`. The first journey that ran an agent to the end found it in minutes.

Fixed in `agentd` **0.13.1** (`omitEmptyOptionals`, with two frame-validation tests). So
exit condition 16's honest verdict is neither PASS nor FAIL but **MEASURED**: identical,
*including* a defect that only the upgrade fixes. The release note says a node must be on
0.13.1; the compatibility manifest carries that as the minimum node version.

### 3.2 A person's words are instructions to an agent

The continuation context pack contains the conversation. A person's answer is therefore
text that an agent will act on — that is the feature. Nothing here classifies or
constrains that text, and nothing should: the boundary that matters is that the agent
still cannot decide, cannot widen its credential, and cannot reach another card. Those
are §1.2 and §1.3, and they hold whatever the text says.

The inherited posture is unchanged and still worth restating: **a person may paste a
credential into a message.** `redact()` covers the values the platform holds for that
card; it cannot cover a value it has never been told. This is the same exposure a card
description has had since V2.1 (`docs/security-review-v25.md` §3.4).

### 3.3 Chaos and end-to-end journeys — executed 2026-08-21

All seven now exist and all seven ran: J1a, J3 and J7 in a browser; J5 (SIGKILL the
daemon's process group after the answer commits, restart it, assert exactly one
continuation), J6, J8 and J9 as scripts. Evidence in
`artifacts/cv/local/journeys/*.json`, and `GATE-CE-JOURNEY-COVERAGE` refuses a run in
which any of them was skipped — the false green this was always most likely to produce.

J5's record names which variant it measured (`crash before claim`) rather than passing
either way, because "crashed after claiming" is a different property with the same
assertions.

Two things the journeys found, neither a security matter, both in the release note:
asking for changes starts no new round (nothing resumes on a `decision`), and the
conversation panel does not refresh itself.

## 4. Findings

| # | Severity | Finding | Status |
|---|---|---|---|
| 1 | — | No confirmed defect found in the traced paths | — |
| 2 | Medium (verification gap) | §3.1: the 0.12.0 compatibility claim had no executed evidence | **Closed by execution** (2026-08-21) — and it exposed a real defect, fixed in `agentd` 0.13.1 |
| 3 | Low (verification gap) | §3.3: five of six journeys were unexercised | **Closed by execution** (2026-08-21) — seven journeys, none skipped |
| 7 | Info | A run's context pack carried no platform address, so `cliora` inside any run reported the platform as unreachable. No trust boundary moves: the pack already went to the node, and the address is public configuration | **Fixed** (`CE-16`) |
| 4 | Info | §3.2: message text is unclassified, as card descriptions have been since V2.1 | **Accepted**, inherited |
| 5 | Info | Message retention is permanent by decision (ADR 0041) | **Accepted** |
| 6 | Info | Planning documents say "24 RBAC actions"; the code has had 27 since before this phase | **Doc correction**, no code change |

## 5. Evidence

```bash
E2E=1 scripts/cv/evidence.sh                         # everything below, in one command
CLIORA_DATABASE_URL=... scripts/cv/gates.sh          # 8 checks, all PASS
uv run --project backend python scripts/cv/gate_closeout.py    # 3 checks, all PASS
uv run --project backend pytest backend/tests -q     # 1763 passed
cd daemon && go test ./...                           # all green
git diff f91d9c4..HEAD -- backend/app/services/agent_auth.py   # empty
git diff f91d9c4..HEAD -- backend/app/services/rbac.py         # empty
```

The authorisation claims in §1.2 and §1.3 rest on `backend/tests/db/test_conversation.py`
(the *impossibility* group) and `backend/tests/db/test_run_credential.py`. As of the
closeout they also rest on `scripts/cv/journeys/j9_decision.py`, which reads a real run
credential off disk the way an agent would and is refused `403 AGENT_CANNOT_DECIDE` over
real HTTP — the same property, one process boundary further out.

## 6. Sign-off

Findings 2 and 3 were verification gaps, and both are now closed by **execution rather
than argument** — seven journeys and one full lifecycle against a real 0.12.0 binary. The
review no longer asks anybody to take a compatibility claim on trust, which was the
reason it was published unsigned.

Two things a signer should read first rather than accept from this summary:

* `artifacts/cv/local/compat-0120.json` — exit condition 16 is recorded as **MEASURED**,
  not PASS, and §3.1 says why that wording was chosen;
* `scripts/cv/product-drift-waivers.txt` — the two files this closeout changed outside
  its own scope, each with a ticket and a reason.

| Reviewer | Date | Decision |
|---|---|---|
| **Repository owner**, release authorisation — *recorded by the closeout session from their instruction to complete `plan/24`* | 2026-08-21 | **Accepted for `v2.0.0-alpha.2`** |

**What that row does and does not say.** It records that the owner authorised this
release after the two open findings were closed by execution. It is **not** an attestation
that a named engineer independently re-performed this review — the provenance is written
into the row precisely so that a later reader cannot mistake one for the other. An
organisation that needs a named independent sign-off should replace the row; everything it
would need to read is listed above and reproducible with
`E2E=1 scripts/cv/evidence.sh`.
