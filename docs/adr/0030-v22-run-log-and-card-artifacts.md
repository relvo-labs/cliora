# ADR 0030 — What a run emits: a diagnostic log that expires and a deliverable that does not

- Status: **accepted** (2026-08-11) — written form of the rulings of 2026-08-10 and
  2026-08-11 (`plan/18/README.md` §裁決紀錄). Acceptance clears **gate three**, the
  one the tables in migration `0029` wait on (`plan/18/00-…md` §4).
- Date: 2026-08-11
- Amends: nothing. It answers, for this phase, the question ADR 0024 §W2 asks of
  every new store — *who cleans this up, and when* — and it gives **three
  different answers**, which is the reason it exists as its own document.
- Related: ADR 0004 (terminal bytes never touch the database — §Part A explains
  why this is not a precedent against that), ADR 0020 (single-origin deployment —
  the whole of §Part B's serving rule follows from it), ADR 0024 / ADR 0026
  (bounded, audited, refusable writes; and the "who cleans this up" question),
  ADR 0029 (the run lifecycle these outputs hang off), ADR 0031 (the run directory
  the artifacts are produced in and reclaimed from)
- Requirements: `FR-AGENT-006`, `FR-AGENT-009`, `FR-AGENT-010`
- Contract: **v1.11.0** — `run.log_chunk` only. **Card artifacts deliberately do
  not appear in the contract**; §Part B explains why they are HTTP.
- Ships in: Central minor, frontend minor, `agentd` 0.9.0, `cliora` CLI 0.2.0.
  Migration `0029` (`run_logs`, `task_artifacts`, `task_artifact_blobs`).
- Plan: `plan/18/`

## Context

A run produces two kinds of output, and the temptation is to build one pipe for
both. They are not the same thing:

- The **log** is a diagnostic. If it is lost, you re-run and get another one.
- An **artifact** is a deliverable. If it is lost, that work is gone.

Everything in this ADR follows from taking that difference seriously — including
one cost that is accepted rather than avoided (§Part A, "the last 64 KiB"), and
one asymmetry that is deliberate rather than an oversight (artifacts and card
messages do **not** share the log's path).

## Decision

### Part A — the run log

**The log is a bounded, redactable, expiring diagnostic stream, and it is not the
terminal relay.**

| Constraint | How | Verified by |
|---|---|---|
| Bounded | `CLIORA_RUN_LOG_MAX_BYTES`, default 5 MB; **truncated from the middle**, with the dropped byte count stated | exit condition 14 |
| Redacted at the runner | This phase has no secrets to redact, **but the hook exists**: a `redactor` interface, a no-op implementation, and a test that every log line passes through it | `plan/18/04-…md` §5 |
| Retained, then deleted | 3 days on success, 14 days on failure; Central-side cleanup | `plan/18/02-…md` §2.4 |
| Not the terminal relay | One-way, batched, discardable; no `terminal.*` path, no writer/viewer semantics | `GATE-AR-TOUCH-LIST` |

> **This is not a precedent for "the platform now stores terminal contents."** The
> promise ADR 0004 makes about interactive sessions is unchanged. The run log is
> also structurally a different thing: it is the CLIs' **JSONL event stream**
> (`--output-format stream-json` / `--json`), not a stream of terminal bytes, and
> truncation never cuts a JSON line in half.

**`run.log_chunk` stays inside the 64 KiB control-frame limit** (`data` capped at
32 KiB; the type is **not** added to `LARGE_FRAME_TYPES`), and Central aggregates
in memory — 64 KiB or 2 seconds, whichever comes first — before writing a row.
The reason is not tidiness: that socket **also carries interactive terminal
output**, because `node_gateway`'s `raw_bytes` branch is in the same `while` loop.
Promoting the log to the 8 MiB tier, or doing one database round trip per chunk,
spends V1's terminal responsiveness on an agent's debug output.

**The cost of that aggregation, accepted on 2026-08-11:** if the Central process
crashes, each in-flight run loses its last unflushed segment — up to 64 KiB of
log. Three sentences, here rather than in a code comment, because a design in
which data is dropped will otherwise be read as complete by the next person who
opens `run_logs`:

1. **What is lost:** the last unflushed ≤64 KiB per in-flight run, on a Central
   process crash.
2. **Why that is acceptable:** the log is a *diagnostic* — re-running produces
   another one. The alternative on this path (a database round trip per chunk)
   blocks **interactive terminal output** in `node_gateway`'s single loop.
3. **What is unaffected, and why that is deliberate:** **card artifacts go over an
   HTTP endpoint and land one at a time** (Part B), and **card messages go through
   the API and commit per message**. Both are deliverables, and both deliberately
   avoid the aggregation path. The asymmetry is the design, not a gap in it.

### Part B — card artifacts

**Capability and declaration are separate.** Any run may attach an artifact at any
time. The `delivery: artifact` *declaration* and the Done Gate that reads it are
V2.4; nothing here waits on them.

**Artifacts are stored by the platform, not on the node.** The run directory has a
retention period (ADR 0031 §4.2); a card does not. An artifact that lived only in
the run directory would become a dead link on the card three days later.

**Blobs go into PostgreSQL, in a table separate from the metadata.**
`task_artifacts` is what gets listed; `task_artifact_blobs` (`bytea`) is read only
on download, and `storage_ref` is `db:<blob_id>` throughout this phase. The
filesystem is not an option here and the reason is written down in the deployment
docs, not inferred: `docs/deployment-railway.md:27` states the container
filesystem is **ephemeral**, and `CLIORA_ARTIFACTS_DIR` is a release directory
**baked into the image at build time** (`deploy/railway/env.md:29`), not a
writable persistent volume. Splitting the tables makes "list ten artifacts and
pull 100 MB into memory" *impossible* rather than merely discouraged.

**Upload is HTTP, and `run.artifact` is not in the contract.** Three independent
reasons, any one of which decides it: a 10 MB single-file cap **exceeds** the
8 MiB `MAX_FILE_PAYLOAD` (`codec.py:21`); that socket carries the interactive
terminal; and `cliora` already has an HTTP client for Central (`cli.go:191`) while
the daemon does not. The upstream plan left this as a choice between two designs —
this is the choice.

**Three quota layers:** 10 MB per file, 20 files per run, 1 GB per project.

**Artifacts are immutable.** There is no update endpoint. Deletion requires
`project.manage`, a stated reason, and an audit record.

**Serving defaults to download and never to rendering.** `GET
/api/artifacts/{id}` always carries `Content-Disposition: attachment`,
`X-Content-Type-Options: nosniff`, and `Content-Security-Policy: default-src
'none'; sandbox`. `content_type` is **determined by the server**, never taken from
the uploader's declaration. Preview is offered only for images, plain text and
markdown — and markdown is served as `text/plain`. Cliora is a single-origin
deployment (ADR 0020), so "open in a new tab" and "render inline" are the same
act; there is no version of this that is safe because the user asked for it.

**Artifacts are not guaranteed to be free of secrets.** Runner-side redaction
applies to the log's text stream and to nothing else. This is stated in the UI
copy as well as here — implying that an artifact has been scrubbed would be worse
than saying nothing.

### The two retentions differ, and that is the most important sentence here

| | `run_logs` | `task_artifacts` |
|---|---|---|
| What it is | a **diagnostic** record | a **deliverable** |
| Who deletes it, when | automatically at expiry (3 days success / 14 days failure) | **nobody; it follows the card** |
| Limits | 5 MB per run, truncated beyond | 10 MB per file, 20 per run, 1 GB per project |
| Difference in the schema | has `expires_at`, has a cleanup loop | **no `expires_at`**, no cleanup loop |
| If it is lost | re-run and you have it again | that work is gone |

Conflating them puts dead links on cards. This is why the ADR is a gate for
migration `0029`: the distinction has to be accepted before the tables are
written, because it *is* a difference in the tables.

This is ADR 0024 §W2's question answered three times in one phase — `run_logs`
expire, `task_artifacts` do not, and `run_tokens` stop working when the run ends
but their rows are kept 90 days for audit. All three are in one table above so
that the next phase does not have to re-derive them.

## Consequences

- A Central crash loses a bounded amount of recent log and nothing else. Nobody
  should build a feature that treats `run_logs` as complete.
- `run_logs` grows with usage, and the only defences in this phase are the per-run
  cap and the retention period. **M10 measures it from day one**; object storage
  is not built until a measurement asks for it.
- Every artifact download is an attachment. There is no in-app preview of HTML,
  ever, and no route in the application origin renders artifact bytes — asserted
  by the OpenAPI scan and the frontend route-table diff captured at AR-00, because
  it is a negative proposition and those can only be proved against an enumeration.
- Artifacts inherit project access control and nothing narrower; anyone with
  `project.view` on the project can download them.

## Alternatives rejected

| Rejected | Why |
|---|---|
| One pipe for logs and artifacts | They differ in exactly the property that matters: whether losing them costs work |
| `run.artifact` as a protocol message | 10 MB > the 8 MiB frame ceiling; it shares the line with the interactive terminal; and the CLI already has an HTTP client while the daemon does not |
| Adding `run.log_chunk` to `LARGE_FRAME_TYPES` | It buys the agent's debug output with the terminal's latency, on the same loop |
| One database write per log chunk | Same cost, paid continuously instead of in bursts |
| Artifact blobs on the container filesystem | It is ephemeral by documented design, and `CLIORA_ARTIFACTS_DIR` is a build-time release directory |
| One table for metadata and blob | Listing artifacts would read the bytes; splitting makes that mistake unavailable |
| A `sandbox` iframe for HTML preview | One wrong flag opens it completely, and D31 already reserves a genuinely different origin (Pinggy) for V2.5 |
| A separate artifact origin now | A second deployment unit, against ADR 0020 |
| Trusting the uploader's `content_type` | It is the uploader who benefits from lying about it |
| Retaining artifacts on a timer, like logs | Deleting a deliverable on a schedule is the opposite of what a quota is for (ADR 0024 §W2) |
