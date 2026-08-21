# ADR 0041 — A message is product data: retention, attachments and size

- Status: **accepted** (2026-08-21), together with ADR 0035–0037 — one decision, and the
  provenance is in ADR 0035's status block. (D51, the retention question this ADR answers,
  was separately confirmed as decided on the same date: `plan/24/00` §0.3.)
- Date: 2026-08-16
- Related: ADR 0030 (run logs expire, artifacts do not — this document places
  messages relative to both), ADR 0024 / ADR 0026 (every write path ships with its
  quota and either an expiry or a visible destination), ADR 0027 (project deletion
  cascades).
- Requirements: `FR-CONV-010`.
- Scope note: this ADR is numbered 0041 because `research/03` reserved 0038–0040 for
  the `alpha.3` and `beta.1` milestones. Nothing in it depends on those.

## Context

ADR 0024's rule for any new write path is: *bounded by size, bounded by cumulative
quota, and either an expiry or a guarantee that every byte lands somewhere the user
chose and can see.* Ask "who cleans this up", not "what is its retention".

A conversation is a write path. It needs an answer.

## Decision

### 1. Messages are kept indefinitely

A run log is a diagnostic and expires (3 or 14 days). An artifact is a deliverable
and follows the card. **A message is what someone said**, and the phase's whole
premise is that it outlives every execution that produced it — including the one
whose log has already been swept.

So messages have no expiry column and no sweep. The exit criterion "delete every
`run_log` row for a card and the conversation, its questions and its proposals are
intact" is the property, and an expiry would contradict it directly.

This satisfies ADR 0024's rule through its second branch, not its first: the bytes
land on the card, the person who wrote them can see them there, and nothing removes
them on a timer.

### 2. Cleanup is by cascade, and it already exists

`task_messages.task_id → tasks.id ON DELETE CASCADE`, and `tasks.project_id →
projects.id ON DELETE CASCADE`. Deleting a project removes its conversations; this
phase adds `task_questions` and `conversation_consumers` to the same chain with the
same `CASCADE`.

Nothing in this phase creates a row that outlives its card. `conversation_consumers`
comes closest — its `consumer_id` deliberately has no foreign key, so a cursor may
name a run that retention has already removed — but the row itself is keyed by
`task_id` and cascades with the card. A dangling cursor is harmless; a cursor deleted
because a run aged out would make a reconnecting consumer re-read from zero.

### 3. Size: 20000 characters, refused with a machine code

The existing limit is kept. What changes is how it is refused: a Pydantic
`max_length` produces a 422 with no machine code, and a client cannot tell it from
any other validation failure. The service layer refuses at 20000 with
`400 MESSAGE_TOO_LARGE` carrying limit and actual, and the schema bound is loosened
slightly so the service is the one that speaks.

The correct interface for "too long" is *your text is safe, shorten it*. That is not
the correct interface for a malformed request, so the two must be distinguishable.

### 4. No new attachment path

`POST /api/tasks/{id}/artifacts` already accepts an optional `message` and links the
result through `task_artifacts.message_id`. That path has a size limit, a per-project
quota, server-determined content type, `attachment` + `nosniff` on download, and no
render path in the application origin.

A conversation-specific upload would need all of those again. ADR 0026 is explicit
that a third write path needs its own ADR; this phase declines to open one and reuses
the second. The composer's attach button posts to the artifact endpoint and shows the
result inline as a link.

### 5. No editing, and therefore no revision table

Human editing is not offered in this phase. Agent messages are never editable — a
correction is an additional message, the same shape as an artifact's immutability in
ADR 0030.

`task_messages` has no `UPDATE` path at all, asserted by `GATE-CV-APPEND-ONLY`. The
whitelist is `task_questions.state` and its two `answered_*` columns, which are the
CAS.

If a later phase adds human editing it must add a revision table, **and feed the edit
event into the next turn's input** — otherwise an agent reads a history that has
silently changed underneath it. Recording that here is cheaper than rediscovering it.

### 6. Export is deferred to `beta.2`

There is no export endpoint in this phase, and that is a decision rather than an
omission: the thread is readable through the API with `project.view`, and a
first-class export wants to answer format, redaction and authorization questions that
`beta.2`'s wider retention work is already going to open.

## Consequences

The conversation becomes a permanent store of user- and agent-authored prose inside
PostgreSQL. Three controls bound what can accumulate there: the 20000-character
message limit, the absence of a second upload path, and Central-side secret redaction
on agent writes (ADR 0037 §3).

What is deliberately *not* bounded is the number of messages per card. A card with
ten thousand messages is a product problem, not a storage one, and the cursor
pagination means reading it costs the same as reading any other.
