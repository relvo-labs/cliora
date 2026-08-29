# ADR 0043 — Reading a provider: pull rather than push, and the ceiling on what it may assert

- Status: **accepted** (2026-08-28) — `plan/27`'s ★ D120, D119, D121, D122, D128, D129, D132.
- Date: 2026-08-28
- Amends: ADR 0038 (**amendment C** — §2's authority ladder gains its first writer for
  `reviewed`, and §1's source table gains two types whose trigger is not a Cliora action).
- Related: ADR 0033 §3 (the three provider *actions*, and the four absences beside them),
  ADR 0031 (the branch namespace a delivered pull request lives in), ADR 0029 §1 (a
  runner's online state is not stored — the same argument shape as §5 here).
- Requirements: `FR-PROV-001`…`-004`.
- Contract: unchanged (**1.13.0**). No node learns that any of this exists.

## 1. The decision

Cliora reads pull requests and published versions from a provider **by polling, in the
knowledge reconciler, over read-only HTTPS**. It does not accept webhooks.

## 2. Why not webhooks, which is what was planned

The upstream plan (`research/03/12` §6) specified a webhook entry point with signature
verification, delivery de-duplication and asynchronous enqueue. Measured against this
repository, that design needs six things that do not exist:

| Webhook needs | Exists? |
|---|---|
| An unauthenticated `POST` route | **No** — all 140 HTTP routes carry an authenticated dependency |
| Constant-time HMAC verification | No |
| A `provider_deliveries` de-duplication table | No |
| A general rate limiter | **No** — the only two 429s in the codebase are ad-hoc, and one derives its limit from data rather than a counter |
| A `webhook_secret` credential kind and its rotation | No |
| A security review of a new unauthenticated ingress | No |

And everything polling needs **already exists**, because the knowledge layer was built
around it:

```text
knowledge/worker.py:19   an advisory-locked reconciler — "its cost is per replica and
                         its benefit is not"
knowledge/worker.py:49   RECONCILE_INTERVAL_SECONDS = 300.0
knowledge/outbox.py:15   "a row here means *this entity may have changed; go and look*"
                         — retries are free, duplicate enqueues collapse
knowledge/repo.py:255    a rate ceiling "counted from the sources themselves rather than
                         from a counter table"
```

The de-duplication requirement in particular **disappears rather than moving**: a job in
this system carries an entity key, not content, and processing one means re-reading the
entity's current state. Delivering the same fact twice costs one redundant read.

**What is given up is freshness, and it is a number rather than a property**: a merge
becomes visible within one reconcile interval — 300 seconds — instead of within seconds.
That figure is a product commitment and belongs in the release note, alongside
`alpha.2`'s "message commit → continuation turn P95 < 10 s".

**The webhook design is not discarded.** If freshness later matters more than the six
absences above, the addition is a route that calls `enqueue()` — the *same* ingest path,
not a second one, because the job it would write is the job the reconciler writes.

## 3. Two modules may reach the network, and each keeps a property a grep can state

`services/providers.py` owns the three provider **actions** (create a pull request, find
one, comment on one). `services/provider_reads.py` owns the **reads**.

They deliberately do not share transport code. Two gates meet on the first file —
`GATE-KN-NO-NEW-EGRESS` (httpx is importable from one module) and
`GATE-DV-PROVIDER-VERBS` (that module does not contain seven words, red line 5 verified
*by absence*) — and extending it would have required rewriting the second into "except
when it is a read". That converts a fact into a judgement, and a judgement needs a reader.

So the allowlist is now two **named** modules, and the new one carries its own absences:

| Gate | Asserts |
|---|---|
| `GATE-HD-EGRESS-ALLOWLIST` | exactly those two modules import `httpx` |
| `GATE-HD-READS-ARE-GETS` | the only HTTP method literal in `provider_reads.py` is `"GET"` |
| `GATE-HD-NO-WRITE-IMPORT` | it cannot reach `create_pull_request` or `comment_on_pull_request` |
| `GATE-HD-NO-PROVIDER-IN-REQUEST` | nothing under `api/http/` imports it — **outbound reads happen in the worker, never in a person's request** |

The last is the pull-model form of the upstream review item "the webhook does not fetch
synchronously inside the request", and it is stronger: the original reviews a behaviour,
this asserts a dependency.

The duplication is three constants and about twenty lines of transport. It buys two
independent greps, and the alternative bought one comment.

## 4. Provider data has a ceiling, and it is a value domain rather than a process

```text
pull request / MR, not merged    →  discussion   (0.75)
pull request / MR, merged        →  reviewed     (1.15)
published version                →  reviewed     (1.15)
draft version                    →  not ingested at all — a draft is not a fact

accepted · authoritative · canonical · verified   →  unreachable from provider data
```

`reviewed` has had a rerank weight and no writer since `alpha.3`, whose store module
already recorded why: it "arrives with provider sync". This is that arrival.

**`verified` is excluded too, and that is the least obvious line.** In this system
`verified` means *Cliora's* verification ran and passed (`sources.py` reads
`report.source == "machine_verified"`). A provider's green CI is somebody else's
verification. The value of a ten-level ladder is entirely that each level means one thing.

Enforced by file boundary rather than by review: the two handlers live in
`services/knowledge/provider_sources.py`, and
`GATE-HD-PROVIDER-AUTHORITY-CEILING` asserts those four words do not appear in it.
`sources.py` could not host them — several of its handlers legitimately write
`authority="accepted"`, so the same grep there would need an AST to say *which function*.

## 5. What is stored, and what is deliberately not

`0044` adds **no table**. Provider facts are `knowledge_sources` rows with two new
`source_type` values, their chunks are `knowledge_chunks`, their jobs are
`knowledge_jobs`. A new table would have needed its own cascade rules, its own isolation
suite and its own retention answer — three questions ADR 0038 has already answered.

Four columns and two CHECK constraints:

```text
knowledge_sources.source_type CHECK    8 values → 10
knowledge_jobs.source_type    CHECK    8 values → 10     ← both tables carry it
projects.provider_sync_enabled              BOOLEAN NOT NULL DEFAULT false
project_repositories.provider_synced_at     TIMESTAMPTZ NULL
project_repositories.provider_sync_error    TEXT NULL
project_repositories.provider_sync_failures SMALLINT NOT NULL DEFAULT 0
```

**`provider_sync_error` is a stored copy of a transient fact, which this codebase usually
refuses** (ADR 0029 §1 declines to store a runner's online state for exactly that reason).
The distinction: a runner's liveness is re-derivable at any moment from the registry, and a
failed poll that happened four minutes ago is not re-derivable from anything. Without the
column, a revoked token presents as "no new pull requests" — identical, on screen, to a
repository where nothing has been merged. That is the failure this column exists to make
visible, and the settings page is where it is shown.

**No deployment flag.** Provider sync is `projects.provider_sync_enabled`, per project,
for the reason D52 gave about knowledge: the cost and the risk are per project, and a
deployment-wide switch cannot express "this project, not that one".

## 6. Rate, failure, and stopping

| | |
|---|---|
| Interval | the existing 300 s reconcile pass — **no second background loop** |
| Reads per repository per round | ≤ 3 (pull-request list, version list, one detail) |
| Ceiling per repository per hour | ≤ 36, derived from `provider_synced_at` rather than a counter table (`knowledge/repo.py:255`'s shape) |
| Consecutive failures before stopping | **3**, then the repository is skipped and `provider_sync_error` says why |
| Retry within a round | none — the next pass is the retry, which is what a reconciler is |

At 50 repositories this is **1800 GET/hour, 36 % of GitHub's authenticated quota**.
Around 140 repositories a deployment reaches the ceiling; that number belongs in the
release note, because an operator adding repositories has no other way to learn it.

The cadence promise is measured from a changed provider entity's event timestamp to its
ingest timestamp, only after the repository has a live cursor; initial history is not a
reconcile-lag sample. A 3613.071-second production-worker observation over twelve
unchanged 300-second rounds produced 24 samples and P95 **291.013 seconds**
(`provider-lag-hour.json`). That observation also replaced the reconciler's session lock
with the transaction-scoped lock above: the old `commit(); unlock()` could return the
owning connection to the pool and attempt the unlock on another connection.

## 7. Retention

Provider sources follow ADR 0038 §6 — knowledge has no clock of its own — with two rules
this ADR adds because they are not derivable from that one:

| Event | Effect |
|---|---|
| Pull request closed **unmerged** | stays `discussion`, `active=false`. **Not tombstoned**: "this proposal was rejected" is worth keeping |
| Published version deleted upstream | `deleted_at` set, `active=false`, **content retained** — a context pack that cited it must be able to say "this source was later removed" rather than hold a dangling id |
| Repository removed from the project | its provider sources tombstoned, as `repo_doc` already is |
| `provider_sync_enabled` turned off | **nothing happens** — data stays, updates stop. Same shape as `knowledge_enabled`: switching off is "stop spending", not "delete" |

## 8. Credentials

The existing `provider_token` secret kind, per repository, already in
`UNDELIVERABLE_KINDS` — it is never delivered to a node. `services/secrets.py` is
unchanged, and rotation is therefore a regression test of an existing mechanism rather
than new work: replace the secret, the next round uses the new value, the old one appears
nowhere.

No new RBAC action. Enabling provider sync is a project setting and takes `project.update`,
which is the action that already governs every other project setting. A dedicated action
would add a row to three role matrices and a seed migration to protect something at
exactly the same level.

## 9. What this ADR does not decide

- **GitLab.** `reader_for` has one entry, deliberately, the same way `adapter_for` does:
  a half-built provider fails after the work is done.
- **Webhooks.** §2 — designed, not implemented, and the note there says what it would take.
- **Anything a provider could tell Cliora to do.** Provider content enters the evidence
  layer of a context pack and never the instruction layer (ADR 0039). A pull request body
  containing "ignore the above" is quoted data, and `HD-14` asserts it with a test.
