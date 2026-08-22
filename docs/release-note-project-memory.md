# `v2.0.0-alpha.3` — Project Memory (V2-K1)

**Status: not tagged.** Two exit conditions are outstanding (§8). This note is the
evidence for the ones that are met.

Implementation plan: [`plan/25/`](../plan/25/README.md). Upstream design:
[`research/03/03`](../research/03/03-phase-k1-project-knowledge.md).

## What this version does

Every project can keep a **traceable memory**: the facts it already holds — cards,
conversation, decisions, verification, artifacts — become versioned, ranked, citable
sources, and an agent is handed the relevant ones with their provenance attached.
Repository documents join them, pushed by the agent from inside its own run.

The one sentence that matters to a person using it:

> An agent can now cite a decision made on another card six weeks ago, and **you can see,
> before dispatching, exactly which sources it will read and why each one was chosen.**

`alpha.1`'s known-limitations item 5 — *"there is no project-scoped knowledge layer; each
run's context pack is assembled from nothing, and an agent cannot cite an earlier
decision"* — is closed by this release.

## Who it is for

Anyone whose project has answered the same question twice. The failure this addresses is
not that agents are unintelligent; it is that an answer, once given, was stored where the
next run would not look.

## Turning it on

**Off by default, per project, not per deployment.** A 500-file project and a
50,000-file monorepo need different answers about what is worth indexing, and a
deployment flag cannot give two.

    Project → 專案記憶 → 啟用專案記憶        (needs `project.manage`, writes an audit row)

Enabling is also the backfill: existing cards, conversation and decisions are indexed
within a few minutes, and progress is on the Source health panel. Turning it **off**
marks sources inactive and deletes nothing.

Repository documents need one more step, and it is worth knowing about before it puzzles
somebody: they are pushed by an agent running `cliora knowledge sync`, because Central has
no git client and no outbound connection it may use for this. **A project whose agents
have never run has no repository knowledge**, and the Source health panel says so in
words rather than showing an empty list.

## Compatibility

| Component | Before | After |
|---|---|---|
| Central | `45a3143` | this release |
| `agentd` | 0.13.1 | **0.14.0** — `internal/cli/` only; the node half has a zero-byte diff |
| contract | 1.13.0 | **1.13.0, unchanged** (`GATE-KN-CONTRACT-FROZEN`) |
| migration | 0040 | **0042** |
| RBAC actions | 27 | **27** — no new action |
| requirements | 178 | **189** (`FR-KNOW-001`…`-011`) |

**An `agentd` 0.13.1 node keeps working and is not told to run a command it does not
have.** Central decides from the node's reported version whether to mention
`cliora knowledge context`; the project's rules are delivered either way. Measured in
journey J15, not argued.

## Known limitations

An empty list here would need an explanation, not congratulations.

1. **No symbol map.** `plan/25` scoped one and it is not built: it needs a
   language-aware parser per language, and `pg_trgm` already finds function names.
   `**/*.sql` and `**/*.proto` are indexed as partial compensation — a schema is
   documentation.
2. **A project whose agents never run has no repository knowledge**, and repository
   freshness is bounded by the last run's commit. Visible on Source health.
3. **A query worded differently from its source will miss it.** "How do we handle
   timeouts" does not find a document that says `lease expiry`. This is D40's accepted
   cost of shipping without vector search; explicit links and human pins are the
   mitigation, which is why a pin outranks every computed score rather than adding to it.
   The miss is **measured** in `artifacts/kn/local/measurements.json` so that a future
   vector experiment has a control group.
4. **No export.** A new data-egress path needs its own quota, format and permission.
   Deferred to `beta.2`.
5. **No PR, MR or release ingestion.** That is `beta.2`'s `HD-01`…`HD-03`; it is the only
   work in this area that adds an outbound side effect, and it is deliberately not mixed
   with a release that adds none.
6. **The "conflicting decisions" column may never be non-empty.** Supersede is automatic.
   It is kept because the day it is non-empty somebody needs to see it; whether it earns
   its place is a `beta.1` decision.
7. **A commit id is not a search filter.** A SHA is findable when a document mentions it;
   "which documents are at commit X" is a filter this release does not have.

## Security delta

- **No new outbound connection and no new credential.** `pyproject.toml` gained no
  dependency and `httpx` is still reachable from one module (`GATE-KN-NO-NEW-EGRESS`).
  The repository sync inverts direction — the agent pushes with the run token it already
  holds — specifically so that this stayed true.
- Eleven new routes: reads take `project.view`, writes take `project.manage`, and the
  run-token surface has no write to authority or pins at all.
- New long-lived data: `knowledge_sources`, `knowledge_chunks`, `knowledge_links`,
  `knowledge_jobs`, `task_knowledge_pins` (with the project or the card) and
  `context_packs` (**with the run** — it is a diagnostic).
- Full review: [`docs/security-review-v2k1.md`](./security-review-v2k1.md). **Not
  signed**: the Railway `CREATE EXTENSION` path is unverified and a reviewer who did not
  write the code has not looked at it.

## Migration and rollback

    0041  CREATE EXTENSION pg_trgm  +  projects.knowledge_{enabled,settings}
    0042  six tables and their indexes

`0041`'s single `CREATE EXTENSION` is **the only change in this release that is not purely
additive**, which is why it is alone in its own revision: the failure message points at
one line rather than at three hundred, and the downgrade order is enforced by the
revision chain rather than by somebody remembering it.

It needs a superuser or an extension allowlist. The migration checks availability first
and refuses with an actionable message rather than failing halfway.

Downgrade is `0042` then `0041`, verified: `upgrade → downgrade → schema unchanged →
upgrade` (`GATE-KN-MIGRATION-ROUNDTRIP`). Rolling back loses the index and the pins; it
loses no product data, because everything here is derived.

## Feature flag matrix

The third axis is **not a deployment flag**. `CLIORA_PROJECTS_ENABLED` and
`CLIORA_AGENT_RUNS_ENABLED` behave as before; project memory is switched per project, so
one deployment can hold projects with it on and off at once — and **a project with it off
behaves exactly as it did in `alpha.2`**: nothing is collected, nothing is indexed, and
the API answers 404 rather than 403 so the status does not disclose the setting.

## Test and gate evidence

| | |
|---|---|
| backend | 1918 passed (`+70` for this phase) |
| frontend | 699 passed (`+13`) |
| daemon | `go test ./internal/cli` green (`+11`) |
| contract | 192 passed, `contracts/v1` byte-identical to baseline |
| gates | 8 new + 4 re-run, all green — `scripts/kn/gates.sh` |
| journeys | J11–J15, **5/5 PASS** against a real daemon — `artifacts/kn/local/journeys/` |
| measurements | `artifacts/kn/local/measurements.json` |

### Measured

| Budget | Target | Measured |
|---|---|---|
| ingest freshness (decision → searchable) | P95 < 10 s | **1.5 s** (J11) |
| knowledge search | P95 < 1 s | **0.11 s** |
| context pack build | P95 < 2 s | **0.08 s** |
| offer context vs the wire's 32 KiB ceiling | must fit | **~0.7 KiB** measured, worst case asserted under 8 KiB |

Recorded without a threshold, on purpose: the CJK-bigram index is **3.54×** the size of
the text it indexes. Nobody knows what a good value is, and a threshold raised the first
time it goes red is a formality rather than a standard.

## Sign-off

Not signed. See §8 of [`plan/25/11-implementation-status.md`](../plan/25/11-implementation-status.md).
