# ADR 0038 — Project knowledge: where it comes from, how much it is trusted, and why it cannot leak

- Status: **accepted** (2026-08-27) — with SR-2, recorded from the repository owner's
  instruction of 2026-08-27. `plan/25`'s five A-class decisions (D77–D81) were adopted on
  2026-08-22 and this document is their written form. §6 is the retention policy of record
  for knowledge — ADR 0041 answers the same question for messages and deliberately does
  not answer it here.
- **Carried open by SR-2**: `CREATE EXTENSION pg_trgm` is unverified on Railway
  (`docs/security-review-v2k1.md` §6). Accepting this ADR did not close that.
- Date: 2026-08-22
- Amends: ADR 0030 (**amendment B** — the log / artifact / message distinction gains a
  fourth member: a *knowledge source*, which is a derived copy with the lifetime of the
  thing it was derived from), ADR 0041 (**amendment A** — §6 below extends its
  retention taxonomy to knowledge; the ADR's own text is unchanged, and that is
  deliberate: it is accepted, and its subject is messages).
- Related: ADR 0027 (a Project is platform data; project deletion cascades), ADR 0029
  (the lease sweep's shape, which the ingestion worker copies), ADR 0031 (the isolated
  run directory — §3.4's whole design exists because Central cannot reach a
  repository), ADR 0032 (`GATE-SC-SINGLE-DECRYPT`: redaction stays in one module),
  ADR 0033 (`FR-VERIFY-002`'s rule that the server decides provenance, not the
  payload — §2 is the same rule applied to authority), ADR 0035–0037 (the conversation
  this indexes), ADR 0039 (what is done with the result).
- Requirements: `FR-KNOW-001`…`-004`, `-008`…`-011`.
- Contract: **v1.13.0, unchanged.** §3.4 is why that is possible: the one new inbound
  data path is an HTTPS request an agent makes with a credential it already has.
- Ships in: Central (minor), `agentd` **0.14.1** (CLI subcommands only; the node half
  has a zero-byte diff), frontend (minor).

## Context

`alpha.1`'s known-limitations list, item 5:

> There is no project-scoped knowledge layer; each run's context pack is assembled
> from nothing, and an agent cannot cite an earlier decision.

The consequence is not that agents are less clever. It is that **every run starts by
asking a person something the project already answered**, and that the answer, once
given, is stored in a place — one card's conversation — where the next run will not
look. `alpha.2` made a card's conversation durable. This makes the *project's* memory
durable, and it introduces the two risks that come with it: content crossing a project
boundary, and a piece of quoted text being read as an instruction.

Four facts about this repository shaped the design more than the product brief did.
Each is a place where the obvious approach is unavailable.

**1. Central cannot read a repository.** There is no git client in the backend, and
`SCOPE-013` limits outbound connections to a single module (`services/providers.py`).
The one existing path to a node's files, `FileRelayService`, resolves through a
`terminal_sessions` row and authorises a `User` — a background worker has neither.

**2. PostgreSQL cannot tokenise Chinese.** `postgres:16-alpine` ships no CJK parser, so
`to_tsvector('simple', '租約過期時要怎麼處理')` yields **one** lexeme. Almost all
product content here is Traditional Chinese. A full-text channel built on the stock
parser would have zero recall for the majority of the corpus, and **zero recall does
not raise an error**.

**3. There is no safe cursor over `activity_events`.** Its `id` is a `uuid4` and its
`occurred_at` is the transaction's start time, so any reader that tails it in order
will skip a row that began earlier and committed later. Adding a `BIGSERIAL` does not
help: sequence holes are skipped the same way.

**4. `run.offer.context` is capped at 32 KiB by the daemon's decoder**
(`codec.go:962`), and a decode failure on that wire is silent — contract 1.13.0's
changelog already records what it looks like. That fact belongs to ADR 0039, which is
where the context pack is designed; it is listed here because it is why this ADR's
scope stops at "produce cited, ranked, project-scoped sources".

## Decision

### 1. A knowledge source is a versioned, derived copy of a fact that already exists

Eight source types in `alpha.3`: `policy`, `ticket`, `conversation`, `decision`,
`artifact`, `verification`, `repo_doc`, `activity`. Every one is derived from
something the platform already stores, or — for `repo_doc` — from a checkout the
platform already caused to exist.

**Nothing here is a new place for a person to type.** This is not a wiki, and the
absence of an authoring path is the property that keeps it true: a knowledge base
nobody maintains by hand cannot go stale relative to the thing it describes, because
it *is* the thing it describes.

The identity of a source is four columns:

    (project_id, source_type, source_external_id, source_version)

and `source_version` takes one of three shapes, in this order of preference:

| shape | example | used by |
|---|---|---|
| monotonic counter | `v3`, `seq:41` | ticket, conversation, decision |
| content address | `sha256:9f2c…`, a commit SHA | artifact, repo_doc |
| timestamp | `2026-08-22T11:03:07Z` | activity, verification, policy |

The order is not aesthetic. A timestamp cannot be an identity where two workers may
process the same entity in the same second; a content hash cannot be an identity for a
ticket, because then correcting a typo starts a new version and the supersede chain has
two hundred links by the end of the week. **Take a counter if one exists, a content
address if not, a timestamp only if neither.**

### 2. Authority is a stored column, and only the ingestion pipeline may write it

Ten levels:

    authoritative  a human's formal decision, a policy, an accepted ADR
    accepted       an accepted spec, an approved requirement
    canonical      merged code, a document at the current commit, a release
    verified       evidence or an artifact that passed verification; a platform-observed fact
    reviewed       a reviewed PR/MR, or a human-confirmed summary
    generated      an agent proposal, a turn summary, unapproved analysis
    discussion     ticket conversation, PR discussion
    diagnostic     a failure, or a log excerpt **a person chose**
    superseded     replaced by a newer version; history queries only
    retracted      withdrawn; never in default retrieval

Stored rather than derived at query time, for three reasons: deriving it needs a join
to the origin table and there are eight of those; it **changes over time** (a merged PR
raises `reviewed` to `canonical`) and the change is itself auditable; and "what was
this trusted as *at the time*" is a historical fact that a derivation cannot answer.

**The API never accepts an authority from its caller.** This is the same rule
`FR-VERIFY-002` states for a verification report's `source`, and it is enforced the
same structural way: the write path's function signature has no such parameter, and
`GATE-KN-AUTHORITY-SERVER-SIDE` asserts that no request schema has the field.

Two of the ten have **no writer in `alpha.3`**: `reviewed` and `released` arrive with
provider sync in `beta.2`. They are defined now anyway. Merging levels later is a
migration; splitting one later is a judgement about rows that were written before the
distinction existed, and nobody can make that judgement correctly.

`superseded` and `retracted` are **excluded, not down-weighted**. A weight of zero is
still a row that gets scored, still occupies a candidate slot, and still turns up after
some future join. Exclusion lives in the `WHERE` clause.

### 3. How a fact becomes a source

#### 3.1 One enqueue point

The only place that enqueues ingestion work is `ActivityService.record()`, through a
closed `activity kind → (source_type, entity id)` map.

The alternative — an `enqueue()` call in each of the eight writing services — was
rejected because **forgetting one is silent**: that source type simply never updates,
and on screen it looks like a project where nothing has been written lately.
`record()` is already called from 27 places, already runs inside the caller's
transaction (its docstring: *"Does **not** commit"*), and its `kind` is a closed
vocabulary — so a test can assert the map covers every source type, which is a thing
a list of call sites cannot do.

#### 3.2 A job is an entity key, never content

A row in `knowledge_jobs` means *"this entity may have changed; go and look"*. The
worker re-reads the entity's current state and upserts from that.

Three consequences, all of them the point: retries are free, duplicate enqueues are
free, and the scheduled reconciler and a human's "resync" button run **the same code**.
The bug class "the payload in the job was stale by the time it ran" does not exist.

Claiming uses `SELECT … FOR UPDATE SKIP LOCKED`, so there is **no cursor** and
therefore none of fact 3's problem. It also makes multiple Central replicas correct by
construction; the reconciler, whose cost is per-replica and whose benefit is not, is
single-flighted with transaction-scoped `pg_try_advisory_xact_lock`. A transaction lock
rather than a leader table or session lock because commit, rollback, connection death,
and a Central killed with `SIGKILL` all release it without a separate unlock on what may
be a different pooled connection.

#### 3.3 Idempotence is an upsert, not a read-then-write

    INSERT … ON CONFLICT (project_id, source_type, source_external_id, source_version)
    DO UPDATE SET … WHERE excluded.source_updated_at > knowledge_sources.source_updated_at

Read-then-write double-writes when two workers handle one resource at once, which is
not hypothetical here: `SKIP LOCKED` hands two replicas two jobs, and two jobs pointing
at one card is ordinary.

#### 3.4 Repository content is pushed from inside a run, never pulled by Central

Because of fact 1, the only paths available were: give Central a git client and an
egress (which ends `SCOPE-013`), widen the file relay so a worker without a session or
a user can drive it (which reopens a boundary `plan/04` closed), add a daemon control
message (which changes the contract and needs every node upgraded), or **have the agent
push**.

The agent pushes. `cliora knowledge sync` runs in the run's isolated working directory
— which already contains a clean checkout of exactly the commit in question — sends a
**full manifest** of `(path, sha256, size)`, receives back the subset Central does not
already have, and uploads only that. Content-addressed negotiation means an unchanged
repository costs one request and zero bytes, which is what makes syncing on every run
affordable.

It changes `internal/cli/` and nothing else: no protocol message, no new credential
(the run token already exists), no new egress, and a zero-byte diff in the node half.

**The cost is stated rather than hidden.** A project whose agents never run has no
repository knowledge, and repository freshness is bounded by the last run's commit. The
Source health panel must say so in words, because *a knowledge base that cannot show
you it is empty is worse than not having one*.

The manifest being full rather than incremental is what makes deletion work: Central
compares it against the previous commit's set and tombstones the paths that are gone.
It is also why force-pushes need no special handling — nothing in the comparison
depends on one commit being an ancestor of another.

### 4. Retrieval is lexical, and the Chinese half is carried by a tokenizer we wrote

D40 (2026-08-16) settled that `alpha.3` has no vector search: adding pgvector changes
the database image with no downgrade path, and an embedding provider adds an egress
whose payload is the most sensitive content in the system. `knowledge_chunks.embedding_ref`
exists and is always `NULL`; the retriever interface has room for a second candidate
source. **The architecture does not block it; this release does not do it.**

That decision puts the whole weight of retrieval on lexical channels, and fact 2 says
one of those channels does not work out of the box. So:

**One pure function produces the lexemes, and both the index and the query call it.**
It emits CJK **bigrams** (`租約過期` → `租約 約過 過期`), lowercased ASCII words, and
split identifiers (`lease_expires_at` → the original plus `lease`, `expires`, `at`).
The `tsvector` is built from its output with the `simple` configuration — `english`
would stem tokens we have already chosen, and a stemming mismatch between write and
read is, again, silent zero recall.

Bigrams rather than unigrams (`期` would match everything) or trigrams (`租約` would
match nothing). Computed in Python rather than in a trigger or a generated column,
because `to_tsvector` is `STABLE` and PostgreSQL refuses it in a generated column — and
because a trigger would split "how is the index computed" across two languages.

`GATE-KN-ONE-TOKENIZER` asserts there is exactly one such function and exactly one
caller of each half. The failure it guards is the worst kind available in a search
system: **everything runs, nothing errors, and the answer is always empty.**

The second channel is `pg_trgm` — a contrib extension, present in `postgres:16-alpine`,
which is the whole of its difference from pgvector. It covers exact references
(`CV-05`), symbols, commit SHAs and typos. Ranking combines the two channels with an
explicit graph boost, then multiplies by authority and a freshness decay that has a
**floor**: old is not the same as wrong, and a charter must not decay to nothing.

### 5. Isolation is a predicate, not a filter

`project_id` is denormalised onto `knowledge_chunks` and `context_packs` even though it
could be joined. The extra column buys a shorter proof: every table can be asserted
independently, and `GATE-KN-PROJECT-SCOPED` can require a `project_id` predicate on
every select — a gate that is only writable *because* the column is on every table.

An unauthorised query returns **zero results and a count of zero**, and a
cross-project source id returns **404**. Not 403: a 403 tells the caller the id exists
somewhere. Cross-project similarity search is not a feature that is switched off; it
is a query that cannot be expressed.

`alpha.3` adds **no retrieval cache**, and that is a decision rather than an omission.
The upstream plan lists cache isolation among the things to test; the honest form of
that test in this release is an assertion that no cache exists. Adding one before the
first measurement would be guessing, and it would need its own isolation suite.

### 6. Retention, deletion and export

This is the half of D51 that ADR 0041 leaves open, and it is here rather than there
because ADR 0041 is accepted and its subject is messages.

The taxonomy now has four members:

| | lifetime | why |
|---|---|---|
| run log | 3 / 14 days | a diagnostic |
| **context pack** | **with its run** | a diagnostic: *what this turn read* |
| message | indefinite | product data: *what someone said* |
| **knowledge source** | **with the fact it derives from** | a derived copy, and a copy must not outlive its original |

So knowledge has **no clock of its own**. Everything it holds is derived from data that
is already kept indefinitely or already cascades, and a second retention column would
be a column with no sweep behind it — which is worse than none, because someone will
read it and believe it.

`active` and `deleted_at` mean different things and both keep the row:

- `active = false` — not in default retrieval (the project's switch is off, the source
  was superseded, or a person excluded it).
- `deleted_at` — the original no longer exists (the file is gone, the artifact was
  deleted).

Neither deletes the row, because `context_packs.source_manifest` may cite it, and a
manifest that can answer *"this source has since been deleted"* is more useful than one
with a dangling id. That is exactly why the manifest stores ids and metadata and **not
content**: storing content would make a second copy of sensitive data and put it
outside every retention rule that governs the first.

Deleting a project removes everything: sources, chunks, links, jobs, pins, context
packs, all by `ON DELETE CASCADE` on `project_id`. `projects` has no delete path today
— only archival — so the test asserts the constraint directly. It is written now so
that it is already true on the day a delete path exists.

**Export is not in this release.** It is a new data-egress path and needs its own
quota, format and permission; it blocks no exit criterion. Its absence goes in known
limitations, because an empty limitations list is not good news.

### 7. Per-project opt-in

`projects.knowledge_enabled` defaults to **false**; turning it on requires
`project.manage` and writes an audit record. While off: nothing is ingested, nothing is
indexed, and the search API answers **404** — not 403, which would disclose that the
project exists and has the feature switched off.

Per project rather than per deployment (D52) because the cost and the risk are per
project: a 500-file repository and a 50,000-file monorepo need different answers, and a
deployment flag cannot give two.

Turning it off marks existing sources inactive and **deletes nothing**. Deletion is a
separate action requiring a second confirmation, and it has no UI in this release —
"I don't want this feature" is already fully served by the switch.

Enabling is also the backfill path. The reconciler's watermark queries find every
entity with no source yet, so **there is no backfill script**; one filling routine is
more correct than two, and the progress is visible on the Source health panel because
otherwise the first support question is "why is it still empty".

### 8. What never enters the index

| | why | how it is guaranteed |
|---|---|---|
| raw run logs | diagnostics with a retention period, high noise, likeliest to hold sensitive text | `GATE-KN-NO-RAW-LOG-INDEX`: the module may not import `RunLog` |
| secret values, credential-shaped strings | — | redaction before write, in `services/secrets.py` (`GATE-SC-SINGLE-DECRYPT` keeps decryption in one module) |
| sensitive filenames (`.env*`, `*.pem`, `id_rsa*`, …) | — | excluded before collection, not after |
| vendored, generated, minified, binary files | noise that would consume the index | `.gitignore` + `.clioraignore` + project globs + a builtin list |
| anything from another project | — | §5 |

A person may still put a log excerpt into the index deliberately, by quoting it in a
message (`discussion`) or marking it (`diagnostic`, `project.manage`). **The platform
never chooses a log excerpt by itself.**

A search query string is not stored anywhere: not in the audit log, not in a metric
label (metrics are the one sink with no redaction), and not in a table. The application
log keeps a digest of it, reusing the function `filesystem.search` already uses for the
same reason. A query says what someone is thinking about and has no audit value.

## Consequences

**What gets easier.** An agent can cite a decision made on another card six weeks ago,
and a person can see, before dispatching, exactly which sources the agent will read and
why each one was chosen. "Why did the agent do that?" acquires an answer that is not a
guess.

**What gets harder.** Every knowledge query now carries a project predicate that a
reviewer must check, and there is a gate for it because reviewers miss things. The
tokenizer is a new artefact with no upstream to defer to, and if it is wrong the
symptom is silence.

**What is deliberately worse than it could be.** Retrieval will miss a query whose
wording differs from the source's ("how do we handle timeouts" against a document that
says `lease expiry`). That is D40's accepted cost, and the mitigations are explicit
links and human pins — which is why a pin outranks every computed score rather than
merely adding to it. `KN-13` records the baseline so that a later vector experiment has
a control group.

**What this does not do.** It does not extract facts (`knowledge_facts` needs an
extractor, a confidence model and a review workflow — three separate problems). It does
not build a symbol map (that needs a language-aware parser, and `pg_trgm` already
covers symbol names). It does not answer natural-language questions about a project:
that needs an LLM call, and Central makes none.

---

# Amendment (V2-E1, 2026-08-29) — what retrieval costs at 20,000 chunks

**Status: accepted.** This amends the Consequences of ADR 0038; the Decision is unchanged.

`alpha.3` measured knowledge search at 110ms P95 and context pack build at 78.8ms P95, on
**1,000 chunks**, and both were read as comfortable. `HD-09` re-weighed them on 22,000 and
one of the two is now over budget.

| | 1,000 chunks | 22,000 chunks | Budget |
|---|---:|---:|---|
| knowledge search P95 | 110.70ms | 162.44ms | 1000ms — **PASS** |
| context pack build P95 | 78.80ms | **3167.62ms** | 2000ms — **FAIL** |

The two disagree because they ask different questions. A human search is short. Layer 4's
query is **the card's own title, objective and scope**, and that difference is the whole
of the 40×.

## The cost model

Measured, in `artifacts/hd/local/w6/perf-2000.md` §3:

```text
ts_rank_cd cost  ~=  0.018 ms  x  matched_rows  x  query_terms
```

Both factors are inflated by decisions this ADR made, each correct on its own terms:

- **`_tsquery` joins lexemes with `|`.** Its docstring defends this at length and the
  argument holds — an `AND` over CJK bigrams is a phrase match in disguise and would make
  layer 4 almost always empty, *silently*. But `|` maximises `matched_rows`.
- **The CJK bigram tokenizer makes `query_terms` large.** A 20-character Chinese title is
  19 lexemes where an English one is three or four words.

Neither is wrong. **What was never noticed is that they multiply**, and that nothing in the
module bounds either factor. `CANDIDATES = 50` does not help: PostgreSQL must rank the
whole matched set to find a top 50.

Rearranged into the number an operator can use:

```text
matched-row ceiling at the 2s budget  =  2000 / (0.018 x terms)

   7-lexeme query (an 8-character title)   ~= 15,800 chunks
  19-lexeme query (a 20-character title)   ~=  5,800 chunks
```

## What the measurement's own corpus does not prove

The 3167ms was measured on a seeded corpus whose vocabulary is templated: two of the seven
bigrams appear in 99% of chunks, so the disjunction swept all 22,220 rows and the GIN index
was correctly bypassed for a sequential scan. **Real prose will not do that**, and
"the context pack takes three seconds in production" is not what this measures.

What does not depend on the corpus is the shape. Cost is the product of two unbounded
factors, and a project whose knowledge is 20,000 chunks *about one subject* — which is what
a project's knowledge is — reproduces it with no templating at all.

## Why this was initially recorded rather than fixed

Every available fix changes what layer 4 returns:

- An inner `LIMIT` before ranking makes the top 50 an arbitrary 50 of the matches, silently
  — the same class of failure as the `%`/`<%` defect this milestone fixed.
- `|` to `&` is precisely the failure `_tsquery` exists to prevent.
- "at least *k* of *n* lexemes" is the right shape, has no `tsquery` operator, and needs a
  rewrite of the channel with a relevance evaluation beside it.

Choosing between those on evidence from a corpus this measurement has itself shown to be
unrepresentative would trade a measured number for an unmeasured one. **A remediation
therefore needed a heterogeneous corpus before it started** — the control added below,
not an afterthought to it.

## Remediation (2026-08-29)

The FTS channel now uses `ts_rank` in place of `ts_rank_cd`. The `@@` predicate, complete
matching candidate set, title/body A/B weights, top-50 candidate bound, trigram channel,
and authority/freshness/graph/pin rerank are unchanged. On the 22,240-chunk scale query,
direct SQL measured **3091.98ms** for `ts_rank_cd` and **18.94ms** for `ts_rank`; the two
returned the same ordered top-50 source set.

Because `ts_rank` produces scores at roughly one fifth the former scale for the weighted
documents used here, the FTS channel weight is 5.0. That preserves its established
boundary against the trigram channel: in particular, an exact title match still outranks
a body that repeats the phrase and receives an exact trigram score.

This change was admitted only with a human-labelled heterogeneous relevance control. It
mixes Chinese and English, title and body matches, seven source/authority shapes, fresh
and old material, exact references, symbols, SHAs, typos and repeated near-topic noise;
all seven expected top results pass. The full knowledge search/context DB set is **43/43**,
and the independent KN-13 fixed query set remains **8/8**, including its expected semantic
miss.

The same 2,000-card / 22,240-chunk database, with 20 warm iterations, now measures:

| | Before | After | Budget |
|---|---:|---:|---:|
| knowledge search P95 | 165.29ms | **9.08ms** | 1000ms — **PASS** |
| context pack build P95 | 3236.24ms | **102.76ms** | 2000ms — **PASS** |

The cost model above remains part of the decision record: restoring `ts_rank_cd` requires
re-running the scale gate, not merely the small-corpus relevance tests.
