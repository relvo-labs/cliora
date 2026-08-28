# ADR 0029 — The V2.2 Agent Runner: a mode of `agentd`, a pull-based claim, and a run that is not a session

- Status: **accepted** (2026-08-11). The decisions below are the written form of
  the rulings of 2026-08-10 and 2026-08-11 (`plan/18/README.md` §裁決紀錄).
  Acceptance clears **gate two** of the phase: `backend/`, `frontend/`, `daemon/`
  and `contracts/` were held untouched until this point (`plan/18/00-…md` §4).
- Date: 2026-08-11
- Amends: nothing. ADR 0027 made the platform the source of truth for the work,
  ADR 0028 turned that work into cards a person can move. This records who moves
  them when nobody is watching. It **narrows one thing ADR 0028 left open**: the
  execution settings 0028 declared inert (`source`, `delivery`) stop being inert
  for two of their values, and §9 of that ADR should be read against §6 here.
- Related: ADR 0023 (node execution posture — a runner is a node, and the
  `dedicated` report in ADR 0031 is the same "report the posture, never set it"
  rule as `sandbox_bypass`), ADR 0016 (RBAC is one table with two authorization
  layers; the four new actions are rows, not a third layer), ADR 0027 (every
  holder of `project.view` already sees every project — §Consequences explains
  what actually changes and what does not), ADR 0028 (the agent principal gains a
  *second kind*, not a second identity model), ADR 0030 (what a run emits and how
  long it lives), ADR 0031 (where a run's code lands on disk and how it gets
  there)
- Requirements: `FR-AGENT-001`, `FR-AGENT-003`…`FR-AGENT-008`
- Contract: **v1.11.0** — `runner.register` / `runner.poll` / `runner.status` and
  eight `run.*` messages. Every existing message is byte-for-byte unchanged.
- Ships in: Central minor, frontend minor, **`agentd` 0.9.0**, `cliora` CLI 0.2.0
  (the same binary as `agentd`). Migrations `0029` (tables), `0030` (seed),
  `0031` (`nodes.agent_runner`).
- Plan: `plan/18/`

## Context

V2.1 gave an agent everything it needs to work on a card except the one thing
that makes the card move on its own: somebody has to start it. Today a person
opens a session, types into a terminal, and the agent inherits a human's
attention for the whole of its work.

V2.2 removes the human from the middle of that loop and nowhere else. A
Developer presses "dispatch to Agent" on a `ready` card; a runner on an enrolled
node claims it, pulls the project's repository into a directory the daemon owns,
runs `claude` or `codex` non-interactively there, streams the log back, talks to
the card, and attaches its output as artifacts. Kill the runner process and the
lease expires, the card is re-queued, and a second runner finishes it.

**This is the first thing the platform does with nobody watching**, which is why
it is split across three ADRs rather than one. This one is the model and the
lifecycle. ADR 0030 is what a run emits — logs and card artifacts, which have
deliberately different retention. ADR 0031 is where the code lands and how git
fetches it, which is the surface that triggered the fifth section of
`docs/security-review-v22.md`.

## Decision

### 1. A runner is a mode of `agentd`, not a new binary and not a new trust chain

`agentd --runner` reuses, unchanged: enrollment, the Ed25519 node credential, the
single outbound WSS, heartbeat, `doctor`, and the release/update path. **No new
way for a machine to become trusted is introduced by this phase.** That is the
most important sentence in this ADR, and everything below is downstream of it.

Two consequences follow directly, and both are load-bearing:

**A runner's online state *is* the node's online state.** There is no second
heartbeat, because there is no second connection. A field that could only ever be
derived from the node's status would be a fake indicator light.

**One node holds exactly one runner row.** `agent_runners` is unique on
`node_id`; `runtimes` is a set rather than a row per runtime, and
`max_concurrent` / `max_waiting` are node-level. Several rows sharing one
WebSocket would immediately raise "which row is online" — and the answer is
always the node. Concurrency has the same shape: several rows share one machine's
CPU and one machine's **disk**, so summing per-row limits means nothing.

### 2. Claiming is pull-based, and the atomic claim happens at `runner.poll`

The platform never pushes work at a runner. `runner.poll` carries capacity, and
Central answers with at most one offer. Backpressure is therefore structural: a
runner at `max_concurrent` simply does not poll, and there is no scheduler to
write.

**The claim happens in the poll, not in the acceptance**, and this is the one
decision in this ADR that is dictated by two specific lines of this repository
rather than by the shape of the problem:

- `registry.request()` awaits a future that is resolved by `resolve_response()`
  **inside the same receive loop** that would have to await it
  (`services/registry.py:276`, `api/ws/nodes.py:276`). Awaiting a node response
  from within that loop is a guaranteed timeout, not a slow path.
- The daemon keeps no correlation table for requests **it** originates:
  `connection.go:494` is a single `switch`, and nothing on the Go side maps a
  reply back to an outstanding call.

So the sequence is `runner.poll` → eligibility query → `UPDATE task_runs SET
runner_id = … WHERE id = … AND runner_id IS NULL` → on a hit, and only then,
`run.offer`. **`run.offer` means "this card is already yours and the lease has
started."** `run.accept` is a report that work began; `run.decline` is a release,
not a refusal of an offer that was still open.

The race that matters — two runners polling in the same event-loop tick — is
settled by the `WHERE runner_id IS NULL` clause, in the database, once.

### 3. Eligibility is four conditions, and the authorization boundary is enrollment

A card is offered to a polling runner when all four hold:

1. the card is in `ready`;
2. every `dependsOn` card is complete;
3. the runtime the card needs is one the runner reports;
4. `assigned_runner_id` is null, or equal to this runner.

Two conditions a reader of the V2.3 plan might expect are **not** here — a
project↔agent binding, and label matching — and their absence is a posture, not
an omission:

> **V2.2's authorization boundary is enrollment.** A runner on any enrolled node
> can claim a card from any project and pull any project's code. Per-project
> authorization arrives in V2.3.

That sentence appears in three places on purpose — here, in the comment above the
new actions in `services/rbac.py`, and on the Agents page in the console —
because it is the kind of design that gets filed as a bug when it is not written
down. `agent_runners.labels` and `tasks.required_labels` are **displayed and not
compared** in this phase.

**Specifying an agent is a `WHERE` clause in that agent's own poll query, never a
push.** Three boundaries follow, each with its own test: an unspecified card can
be claimed by any runner; a specified card by only that one; and a specified card
that is re-queued after a lost lease is still offered only to the runner it names
— a card is usually specified precisely because only that machine has what it
needs, and executing on the wrong machine is worse than waiting.

`sessions.authorize_workspace()` is **not** on this path, and that is a
subtraction rather than a complication: a run does not use a workspace binding at
all, so red line 2 keeps exactly one caller group.

### 4. Three timers, three different questions

The first draft of this phase had one wall clock and it was wrong, in a way worth
recording: **a one-shot command exceeding a deadline does not mean it stopped
working.** It usually means the agent is still thinking.

| Timer | Asks | Judged by | On expiry |
|---|---|---|---|
| `lease_expires_at` (renew 30 s, expire 180 s) | is the **runner** alive? | Central (`RunReaper`) | `lost`, `attempt + 1`, re-queue |
| `runner.idle_timeout_seconds` | is the **child** making progress? | daemon | `RUN_IDLE_TIMEOUT`, no re-queue |
| `spec.timeout_seconds` (6 hours) | will it *ever* stop? | daemon | `RUN_TIMEOUT`, backstop only |

Liveness is decided by the **event stream**, not by the clock: both CLIs expose a
machine-readable one (`claude -p --output-format stream-json`, `codex exec
--json`), and every line advances `last_event_at`. Byte-level activity would be
weaker — a spinner redrawing proves the renderer is alive and nothing else.

**`run.lease_renew` stays unconditional on purpose.** Making renewal conditional
on child activity would make "the runner died" and "the child hung" look
identical to Central, and they converge along different paths: one is re-queued
by Central, the other is killed and reported by the daemon.

Re-queue is capped at 3 attempts; the fourth failure moves the card to `blocked`
with the reason recorded.

### 5. Lease semantics for a run that is waiting on a person

`waiting_for_input` renews its lease, does **not** accrue execution timeout, and
does **not** occupy `max_concurrent` — it occupies a separate `max_waiting`. A run
waiting for a reply is not running a process, and letting three of them exhaust a
node's execution capacity would be a self-inflicted outage. Unanswered after 24
hours, it moves the card to `blocked`.

Lease reclamation is a periodic sweep (`RunReaper`: started from `lifespan`,
interval `lease_timeout / 3`, driven by `ix_task_runs_lease`, reconciling once at
startup) rather than a per-item timer in the shape of `shell_reaper.py`. That
file's "This is not a scheduler" comment is right about shells, which have one
idle trigger each; a lease is reset every 30 seconds, a 24-hour wait outlives a
Central restart, and `lease_expires_at` is already a column.

### 6. An Agent Run is not a session, and it does not use a workspace binding

A run does not write `terminal_sessions`, does not traverse the terminal relay or
queue, holds no writer slot, gets no tmux, and lives in **no allowed root**. The
two execution paths are separate in the code, and that separation is asserted by
machine — `GATE-AR-TOUCH-LIST` plus `GATE-AR-NO-WORKSPACE-IN-RUNS` — rather than
by review.

The card's `source` and `delivery` settings, declared inert by ADR 0028 §9, stop
being inert for exactly the values this phase can honour: `source ∈ {none, repo,
existing_branch}` and `delivery ∈ {none, artifact}`. Everything else is refused at
dispatch with a message that says "from V2.3", because a declaration the platform
silently ignores is worse than one it refuses.

### 7. Old daemons stay useful

`node.register` gains an `agent_runner` capability flag (migration `0031`),
following `context_projection` (`0027`) and `image_upload` / `file_upload` before
it. A node running 0.8.0 keeps serving interactive sessions and is simply never
offered a run. Nothing about this phase forces a fleet-wide update, and
`node_update`'s existing staged rollout is neither changed nor triggered by it.

## Consequences

**Any runner can pull any project's source code, and that is a change in *where
code lands*, not a regression in access control.** What is not new: there is no
`project_members` table, and `api/http/projects.py:109` already records that
"every holder of `project.view` sees every project… two teams sharing one Cliora
see each other's project names — a real disclosure, accepted deliberately" (ADR
0027). A person could already open a session on any node's allowed root and read
the code there. What *is* new: `project_workspaces` was an Admin's deliberate
record of "this project's code lives on these machines", and a runner bypasses
that record. The disposition is to write it down rather than to add a mechanism —
V2.3's `project_agents` takes it back — and to say so on the Agents page rather
than only here.

**The blast radius of a card is the machine it lands on.** Combined with the
credential posture in ADR 0031 (§5.4: the agent may use the machine's existing git
credentials for anything git can do), a card from project A running on a node that
holds write credentials for project B can reach project B. This is a deployment
posture question, and ADR 0023 already answers the half that matters: a node is a
disposable isolated VM, and enrollment is an Admin-only action. The premise being
accepted here, and written into §1 of the security review, is that **a runner node
should be dedicated** and should not share a machine with things at a different
trust level. `dedicated` is reported by the daemon and shown in the console (ADR
0031 §3.5) so that the mixed-use case is a visible choice rather than an unnoticed
fact.

**A run's log is stored, and an interactive session's bytes still are not.** The
promise in ADR 0004 is unchanged; the distinction and its cost are ADR 0030's
subject, not a footnote here.

**No automatic assignment exists, and none is planned.** Claiming is the runner's
action. The platform issues no `git push` of its own in this phase, at all.

## Alternatives rejected

| Rejected | Why |
|---|---|
| Platform-side push dispatch | It grows into a scheduling engine, and it contradicts red line 4's "no automatic assignment" |
| Building a run as a kind of session | Different lifecycle, and it would pollute a state machine that maps onto a real human process. It also directly violates exit condition 16 |
| A separate runner binary | It duplicates the entire trust chain (enrollment plus the node credential) — the single thing in this system that should least be built twice |
| `offer → accept → claimed{granted}` three-way handshake | One more message type, and the claim window only moves later rather than closing. The deadlock in `registry.request()` is not avoided by it either |
| `asyncio.create_task` inside the node WebSocket loop | That connection holds **one** `AsyncSession`; it cannot be used concurrently |
| A second, runner-only WebSocket | Contradicts §1: it is a second trust surface for a node that already has one |
| Several runner rows per node | Sharing one WSS makes "which row is online" always equal to the node's status; the column becomes a fake indicator light |
| Executing in the user's bound workspace | Rejected by ruling on 2026-08-10: unattended execution plus a person's uncommitted work is not a gap that should exist for even one phase. The agent clones into a directory the daemon owns |
| Creating `project_agents` now, unused | An authorization table that authorizes nothing removes a real checkpoint from V2.3's security review |
| Falling back to any agent when a specified one is offline | The reason for specifying is usually that only that machine has what the card needs. Available as an opt-in card field when someone actually needs it |
| Promoting a run into an interactive session | The run's working directory is reclaimed on a retention schedule; making it a durable tmux would mean redesigning that lifecycle (D26) |
| A wall clock as the liveness test | It kills agents that are working. Both CLIs expose an event stream designed for programs; §4 uses it |
| A PTY, to get live state from the child | The direction is right — bidirectional, immediate stdio — but the mechanism is wrong. It turns a run into a session, and it turns the run log into an ANSI screen recording, which reopens ADR 0030's boundary in the worst possible way |

---

# Amendment (V2.3, 2026-08-13) — tag dispatch, and the fifth eligibility condition

- Status: **accepted** (2026-08-27) — gate two closed by the repository owner, recorded
  from their instruction of 2026-08-27, together with ADR 0031's amendment and
  ADR 0032/0033/0034.
- Scope: this amendment adds the tag half of pairing. The claim model, the lease,
  the three timers and "a run is not a session" are unchanged above.
- Requirements: `FR-RUNENV-008`
- Contract: **v1.12.0** — two optional booleans on `runner.register`.

## B1 — Pairing has exactly two layers

| Layer | Question it answers | Who sets it |
|---|---|---|
| `required_labels` × `labels` | **Can** this runner do this card | The runner reports its own; the card declares what it needs |
| `assigned_runner_id` | **Should** this card go to that one specifically | Whoever creates or dispatches the card |

**There is no third layer.** `project_agents` is not built — the reasoning is in
ADR 0032 §0 and **is not repeated here**. Authorization is a question about
secrets, not about routing; arguing it in two documents is how two documents start
to drift.

## B2 — The five eligibility conditions

A queued run is offered to a runner when all five hold:

1. The task is in `ready`
2. Its `dependsOn` are satisfied
3. The runtime matches
4. **The tags match** (B3)
5. `assigned_runner_id` is null, or is exactly this runner

Condition 4 is the one this amendment adds. V2.2 shipped four.

## B3 — GitLab semantics

- **Superset match**: `required_labels ⊆ runner.labels`. A card needing `docker`
  and `node20` goes to a runner that has both; extra tags on the runner are
  irrelevant. **Equality matching was rejected** — one extra tag on a machine would
  stop it claiming anything, which is unusable in practice.
- **`run_untagged`** (a boolean on the runner, default `true`): turned off, that
  runner only claims cards that declare at least one tag. It is the only way to
  reserve a machine for particular work; without it a dedicated box still fills up
  with ordinary untagged cards.
- **`accept_secrets`** (default `true`) is the same family of node-side declaration
  rather than a sixth condition: with it off, the runner is only offered cards whose
  `required_secrets` is empty.
- **Tags are free strings.** No pre-registered dictionary, no naming scheme, no
  per-project tag allowlist. That is consistent with GitLab and with "the runner
  reports its own capabilities"; a dictionary can be added when three spellings of
  one capability actually appear.
- **A payload that omits either boolean is read as `true`**, matching the column
  default, so behaviour is unchanged across an upgrade. The compatibility statement
  deliberately does not name a daemon version: it asserts a property of the payload,
  which is testable, rather than the behaviour of a release, which is not.

## B4 — Matching happens in Central, not on the runner

The platform is the only source of offers, so filtering on the runner would mean
trusting a runner's self-restraint. The more practical reason is different:
**"why has nobody claimed this card" has to be answerable on the platform** — and
that is a query, not a piece of copy. The reverse query returns the *smallest
missing tag set* across online, enabled, runtime-matching runners, because what the
user needs to know is what the closest machine still lacks. An intersection would
return the empty set whenever two runners lack different tags, and "no runner is
missing any tag" would then be false.

**The two eligibility queries share one predicate.** Central computes eligibility in
two places — the offer query (SQL) and the waiting-reason count (Python, because it
needs the in-memory online check). Adding condition 4 to only one of them makes the
console state a reason that is not true, and **no test would go red**. They are
therefore driven from one predicate each side, fed the same cases by one
parameterised test, and `GATE-SC-TAG-BOTH-QUERIES` asserts both call it.

## B5 — A tag is not authorization

**A tag is a string the runner reports about itself.** A compromised or
misconfigured runner changes what it is offered by reporting one more tag.

Two consequences that are enforced rather than merely stated:

- The UI shows tags **read-only**, annotated as declared by that node's `agentd`
  config, and **no padlock icon or the word "authorised" appears anywhere near
  them**. That is a rendered-DOM assertion in the frontend tests, not a promise in
  a document.
- **Editing a runner's tags through the API is not possible.** `agent.manage`
  covers enabling a runner and its concurrency — the disposition of compute — and
  nothing else. Allowing an edit would create a second source of truth that
  `runner.register` overwrites on the node's next reconnect.

## Alternatives rejected (amendment)

| Rejected | Why |
|---|---|
| A binding table, or tags doubling as authorization | ADR 0032 §0. Referenced, not re-argued |
| Exact-equality tag matching | One extra tag on a runner stops it claiming anything |
| Central overwriting a runner's tags | Two sources of truth: `runner.register` overwrites the edit on reconnect. A tag is the runner's declaration about itself, so changing one means changing that node's config file |
| A pre-registered tag dictionary | Premature. Let free strings run until one capability is spelled three ways |
| Filtering on the runner | Trusts self-restraint, and leaves "why has nobody claimed this" unanswerable on the platform |

---

# Amendment (V2.4, 2026-08-14) — a node declares what it can do, and the default is that it cannot

This amendment adds one field to `runner.register` and one rule about how Central
uses it. Neither changes the runner model; both close a hole that was already open.

## C1 — `features`, a list the node reports about itself

`runner.register` gains `features`, a bounded array of known strings. `agentd`
0.11.0 reports `["verification", "evidence"]`. **Absent means the empty set.**

Central puts feature-gated content into an offer **only for a node that named the
feature**. Nothing else consults it — it is not an eligibility condition, not a
filter on the offer query, and not shown as a capability the operator can grant.
It answers one question: *may this content be put on the wire to this machine.*

## C2 — Its default is the opposite of `run_untagged` and `accept_secrets`, on purpose

Those two are **refusal** flags: absent means the node does not refuse, so an older
daemon keeps behaving as it did. `features` is a **support** flag: absent means the
node does not support.

A permissive default on a support flag would mean assuming that a machine which has
never heard of a feature performs it. The two polarities look inconsistent in a
table and are the same rule — **an absent declaration means the older behaviour** —
and the older behaviour for a capability is not having it.

## C3 — Why this exists: central→node compatibility is not permissive

The two directions of the protocol have opposite failure modes, and V2.3 only tested
one of them.

**node→central is forgiving.** Central reads the keys it knows and ignores the rest;
an older node that omits a field gets the documented default. Exit condition 3f of
V2.3 tested exactly this.

**central→node is not.** `ValidateControl` decodes with `DisallowUnknownFields`, and
Go applies that recursively — so it also governs `spec`. When it fails,
`handleRunOffer` **returns without sending anything**: no decline, no error frame.
The card is claimed, the offer disappears, the lease expires, the card is retried to
exhaustion and blocked, and no message anywhere mentions compatibility.

**This was already true before V2.4.** `spec.branch` shipped in contract 1.12.0, so
a node still running `agentd` 0.8.0 drops every `delivery: branch` offer it is sent,
silently. That is a defect of V2.3 rather than of this amendment, and it is recorded
here because this is where the general rule is written:

> **New content in `spec` requires the receiving node to have declared support for
> it first.** A version number is not a substitute: it says what shipped, not what is
> configured, and V2.3 already ruled that capability is declared rather than
> inferred.

**One retrospective exception, and it is the only version check in the phase.** A
node that declares no `features` *and* reports an `agentd` older than 0.9.0 is not
offered a card whose `delivery` is anything but `none`, and the Agents page says
why. Deployed 0.8.0 binaries cannot be made to declare anything, so nothing else
would reach them. New nodes are judged by declaration alone.

## Alternatives rejected (amendment)

| Rejected | Why |
|---|---|
| Free-form feature strings | A misspelling becomes "silently unsupported", which is the failure class this amendment exists to remove |
| Treating an absent `features` as full support | Assumes an un-upgraded machine performs a feature it has never heard of |
| Gating on `nodes.daemon_version` generally | What shipped is not what is configured. Kept only for the 0.8.0 back-fill, where no declaration can ever arrive |
| Making the node decline an offer it cannot handle | It cannot: the frame fails to decode before any handler sees it, which is precisely why the check has to be on the sending side |
