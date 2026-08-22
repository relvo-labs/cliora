# ADR 0037 — Who may say what on a card, and why an agent's sentence is never an approval

- Status: **accepted** (2026-08-21), together with ADR 0035 and ADR 0036 — one decision,
  and the provenance is in ADR 0035's status block.
- Date: 2026-08-16
- Related: ADR 0028 (`AgentPrincipal` carries no `user_id` — this document extends
  that to a third actor kind on the thread), ADR 0032 (secrets — §3 adds one
  redaction point the existing one does not cover), ADR 0033 (`RUN_TOKEN_SCOPES`
  excludes `task.approve`), ADR 0034 (the three human gates — this document adds no
  fourth and weakens none).
- Requirements: `FR-CONV-007`, `-010`; narrows nothing in `SEC-002`.
- Contract: **v1.13.0, unchanged.**
- RBAC: **no new action.** That is a decision, recorded in §2.

## Context

V2.5 established that an agent writes *proposal* columns and a person writes
*decided* columns, and put three gates on the boundary. This phase adds a channel
that both actors write to with the same HTTP verb and the same RBAC action
(`task.update`) — which is what makes "humans and agents share one channel" true in
the authorization layer and not merely in the URL.

A shared channel needs its boundary stated in one place, because the boundary is no
longer visible from the endpoint.

## Decision

### 1. Three actor kinds on one thread, and the thread records which

`author_kind ∈ {user, agent, system}`, already present. A run token writes as
`agent`, with `author_runner_id` set from the token and `author_user_id` **null** —
`AgentPrincipal` still has no `user_id` to offer, and the message DTO exposes the
runner's name so a reader sees `runner-03`, never a person.

A request that supplies `author_user_id` with a run token does not fail; the field is
**ignored**, because it is not an input. There is no path by which a token that is
not a person's produces a message attributed to one.

### 2. No new RBAC action

| capability | existing action |
|---|---|
| read the thread and its questions | `project.view` |
| write `comment` / `question` / `answer` | `task.update` |
| trigger a continuation | `task.update` |
| write `decision` (accept or reject a proposal) | **`task.approve`** |

Adding a `conversation.*` action would mean touching `rbac.py`, a seed migration and
three role rows — and creating one more thing that every future review must confirm
is absent from `RUN_TOKEN_SCOPES`. The holders of the four existing actions are
already exactly the right sets.

`task.approve` is not in `RUN_TOKEN_SCOPES` and is not going to be, so an agent
writing `decision` fails at the authorization layer regardless. The explicit
`403 AGENT_CANNOT_DECIDE` is added anyway, for two reasons: a legible error instead of
a generic one, and an audit row instead of silence. **A refusal nobody records is a
refusal nobody can review.**

### 3. Redaction has a second entrance, and this phase opens it

The existing secret redactor wraps the daemon's protocol `send`, covering
`run.failed`'s stderr and `run.complete`'s summary. `cliora task say` does not go
through it — it is an HTTPS request to Central.

So Central redacts message bodies written by a run token, against the set of secret
values materialised for that run, **before the insert**. After the insert is too
late: the value is already stored, and storage is the thing being prevented.

This is not a new promise. It is the existing promise applied to a channel that did
not exist when it was written.

### 4. What a `comment` cannot do, stated as refusals

- A `comment` never changes a run's status, and never creates a turn. Only the answer
  endpoint does, and only for an `open` question.
- An `answer` never approves anything. Gates, delivery approval and the Done Gate
  keep their own human-only endpoints, unchanged.
- A `proposal` never changes readiness. It is a message; a person's `decision` is
  what moves anything.
- A `system` message is written by the platform only. Neither actor may forge one,
  and the write path (`post_event`) is not reachable from either HTTP surface.

The UI reinforces the first of these by making "留言" and "回覆並繼續" two visually
distinct actions with different accessible names, and by *not rendering* the second
when no question is open. A permanently greyed-out button reads as broken; an absent
one reads as not applicable.

### 5. Audit records that it happened, never what was said

| event | recorded | not recorded |
|---|---|---|
| message created | actor, kind, task, `conversation_seq` | **body** |
| answer + resume | question id, continuation run id, mode | answer text |
| `decision` | actor, proposal id, outcome | proposal text |
| agent attempted `decision` | actor, task, run | — |
| question expired | question id, hours waited | question text |

The thread is already durable and already readable with `project.view`; copying its
contents into the audit log would create a second copy under a different retention
rule and a different access rule, for no investigative gain. Audit answers *who did
what, when*. The card answers *what was said*.

### 6. A Viewer reads and does not write

`project.view` is held by all three roles, and `task.update` is not held by Viewer.
The thread is therefore readable by a Viewer and not writable — the same shape as
every other V2 surface, asserted with a negative test rather than assumed from the
dependency.

## Consequences

The boundary this phase must defend is narrower than it first appears, because three
of the four halves were already true: an agent already could not approve, already
could not resolve into a user, and already wrote as a distinct actor kind. What is
genuinely new is (a) an agent-authored message that a person is invited to *act* on
(`proposal`), and (b) a Central-side redaction point.

Both are covered by SR-1 (`plan/23/08-…md` §5), and both are the kind of property
that a test proves by failing to do something — which is why they are negative tests
and a gate rather than assertions about a happy path.
