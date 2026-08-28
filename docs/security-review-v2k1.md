# Security review — SR-2, `v2.0.0-alpha.3` (V2-K1 Project Memory)

- Scope: everything under `backend/app/services/knowledge/`, the eleven HTTP routes it
  adds, migrations `0041`/`0042`, and `daemon/internal/cli/knowledge.go`.
- Reviewed against: `plan/25/09-verification-and-exit.md` §7 (thirteen items), ADR 0038,
  ADR 0039.
- Date: 2026-08-22
- **Sign-off: SIGNED 2026-08-27** — repository owner, release authorisation. §6 records
  what that signature does and does not say. It was signed with item 8 open;
  **item 8 was closed on 2026-08-28** and §6.1 says how — the premise turned out to be
  wrong rather than the measurement missing. All thirteen items now PASS.

## 1. What changed about the trust boundary

Two new risks, and they are the reason this review exists rather than being folded into
the release note:

1. **Content crossing a project boundary.** Before this phase, no query returned text
   from a project the caller did not name. Now every retrieval reads a shared table.
2. **Quoted text being read as an instruction.** A repository document is now part of
   what an agent is handed, and a document can contain the sentence *"ignore the above"*.

One risk that was expected and **did not** materialise: this phase adds no outbound
connection and no new credential. The repository sync inverts direction — the agent
pushes with the run token it already holds — precisely so that it would not.

## 2. The thirteen items

| # | Item | Verdict | Evidence |
|---:|---|---|---|
| 1 | Project isolation at the retrieval boundary | **PASS** | 8 isolation assertions in `tests/db/test_knowledge_search.py`; the predicate is `KnowledgeSearch._scope`, and `GATE-KN-PROJECT-SCOPED` refuses any select over a `knowledge_*` table without one |
| 2 | An unauthorised query discloses nothing | **PASS** | `test_the_count_is_zero_too_not_only_the_list`; J14 asserts the same over HTTP, plus that a cross-project id and an id that never existed are **indistinguishable** |
| 3 | Secrets, credentials and sensitive files never indexed | **PASS** | `secrets_filter.py`: the project's declared secrets via `SecretService.redact` (one decrypting module, `GATE-SC-SINGLE-DECRYPT` re-run green) plus a fixed pattern list; `test_a_credential_shaped_literal_never_reaches_a_chunk`, `test_a_sensitive_path_uploaded_anyway_is_still_not_stored` |
| 4 | Prompt injection is not promoted to instruction | **PASS** | J13, and its third assertion is the load-bearing one: after a run against an injected document the card's **stage and gates are unchanged**. A system that files the string correctly and then acts on it has solved nothing |
| 5 | An unapproved agent proposal is never authoritative | **PASS** | `_policy_sections` admits only `source_type='policy'` at accepted-or-above, enforced by the query rather than by a check; `GATE-KN-INSTRUCTION-LAYER` asserts one assembler; `test_only_policy_reaches_the_instruction_block` |
| 6 | Deletion and revocation cascade | **PASS** | `test_deleting_a_project_removes_every_knowledge_row`; J12 for the repository lifecycle; tombstones keep the row and close the chunks so a citation can say *why* it is gone |
| 7 | **Central added no outbound connection** | **PASS** | `GATE-KN-NO-NEW-EGRESS`: the dependency list is byte-identical to the baseline, and `httpx` is still imported only by `services/providers.py` |
| 8 | `CREATE EXTENSION pg_trgm` on both deployment paths | **PASS** (2026-08-28) | compose verified (PostgreSQL 16.14, superuser). The non-superuser half is verified **by privilege rather than by provider** — see §6.1: `pg_trgm` is a *trusted* extension, so the predicate is `CREATE` on the database, and all three role shapes were exercised |
| 9 | Authority cannot be asserted by a caller | **PASS** | `GATE-KN-AUTHORITY-SERVER-SIDE`: no request schema carries a free `authority`, and the one that carries a closed `Literal` admits only the three a person may assert — `canonical` and `verified` mean *the platform observed it* and remain unassertable |
| 10 | A run token cannot cross a project, write authority or pin | **PASS** | `test_run_token_cannot_sync_another_projects_repository`, `test_another_projects_repository_is_a_404_not_a_403`; the run surface has no authority or pin route at all, and `cliora knowledge` has no subcommand for either |
| 11 | Query strings are not recorded | **PASS** | not in audit, not in a metric label (metrics are the one unredacted sink), not in a table; the application log keeps `keyword_digest()`, the same function `filesystem.search` uses |
| 12 | An un-upgraded node (`agentd` 0.13.1) is unaffected | **PASS** | J15, **measured rather than argued** — SR-1 left the equivalent item as an argument and `plan/24` had to come back for it |
| 13 | Every new route is behind `require_projects_enabled` | **PASS** | both routers carry it as a router-level dependency; `test_every_mounted_route_is_in_the_matrix` covers all eleven |

## 3. Findings

### 3.1 `CROSS_PROJECT_DENIED` was specified and does not exist — resolved by removal

`plan/25` listed six machine codes. Five are raised; the sixth had **no call site where
raising it would be safe.** Every candidate — a run token naming another project's
repository, source or card — is a case where a 403 confirms that an id is real, so all of
them answer 404. The only shape that discloses nothing would be a caller naming its own
project's boundary, and no endpoint lets a run token name a project at all.

Removed from the catalog with the reasoning recorded in place, because
`test_the_catalog_documents_nothing_fictional` is right: a code with no site is a code
somebody eventually raises in the wrong place.

### 3.2 The feature-declaration mechanism could not carry a new value

`plan/25/07` gated the CLI hint on `runner.register.features`. That enum is **closed**,
and a value outside it is a rejected frame by deliberate design (there is an invalid
fixture asserting it). Adding one would have been a contract change, and an un-upgraded
Central would then have rejected a new daemon's registration outright — a worse failure
than the one being avoided.

Gated on the reported daemon version instead. No contract change; J15 is the evidence.

### 3.3 Two fleet-wide reads, named rather than hidden

`GATE-KN-PROJECT-SCOPED` has exactly two exemptions: the Prometheus gauges (deployment
counts, no content, scrape token only) and the interrupted-job sweep (a maintenance pass
whose whole point is that it is not per project). The gate **prints both every time it
runs**, so an exemption cannot become invisible.

### 3.4 No retrieval cache exists, and that is asserted

The plan lists "no cross-project leakage through the cache" as an item. The honest form
of that in a release with no cache is a test asserting none exists
(`test_there_is_no_module_level_result_cache`), so that whoever adds one is reminded to
bring an isolation suite with it.

## 4. Data retention delta

| Added | Lifetime | Why |
|---|---|---|
| `knowledge_sources`, `knowledge_chunks`, `knowledge_links` | with the project | derived copies; a copy must not outlive its original |
| `knowledge_jobs` | with the project | hints, not content |
| `task_knowledge_pins` | with the card | a person's decision about a card |
| `context_packs` | **with the run** | a diagnostic — *what this turn read* — in the same class as a run log |

No new expiry sweep, deliberately: everything here derives from data that is already kept
indefinitely or already cascades, and a retention column with no sweep behind it is worse
than none because somebody will read it and believe it.

`context_packs.source_manifest` stores **ids and metadata, never content**. Storing the
text would place a second copy of the most sensitive material in the system outside every
rule that governs the first.

## 5. What this review did not cover

- **Railway's PostgreSQL.** Item 8 is half done; the compose path passed.
- **A hostile agent.** J13's agent reads and reports; it does not attempt to obey. The
  platform-side property (the string is quoted, the card does not move) is what was
  tested. Whether a capable model resists a well-crafted injection is a model question
  and this review makes no claim about it.
- **Load.** The measurements in `artifacts/kn/local/measurements.json` are one machine,
  1000 chunks, no concurrency.

## 6. Sign-off

Two things were outstanding when this document was published on 2026-08-22:

1. Item 8's Railway half.
2. A named reviewer who did not write the code.

**The second closed on 2026-08-27 (the signature below). The first closed on 2026-08-28
— see §6.1, and note that it closed by discovering the question was wrong.**

| Reviewer | Date | Decision |
|---|---|---|
| **Repository owner**, release authorisation — *recorded from their instruction of 2026-08-27* | 2026-08-27 | **Accepted for `v2.0.0-alpha.3`.** Signed with item 8 open; **item 8 closed 2026-08-28** (§6.1) |

**What that row does and does not say.** It records that the owner authorised this
release. It is **not** an attestation that a named engineer independently re-performed
this review — the provenance is written into the row precisely so that a later reader
cannot mistake one for the other. This is the same shape and the same wording as SR-1
(`docs/security-review-v2c1.md` §6); an organisation that needs a named independent
sign-off should replace the row, and everything it would need to read is in §1–§5.

### 6.1 Item 8, closed on 2026-08-28 — and the premise was wrong

The paragraph this replaces said item 8 needed "one measurement against a real Railway
PostgreSQL". `plan/27`'s `HD-00` went to make it and found that **the question was the
wrong one**.

`CREATE EXTENSION` does not require a superuser for this extension. `pg_trgm` is marked
`trusted = true` in its control file, and since PostgreSQL 13 a trusted extension may be
installed by **any role holding `CREATE` on the database**. Railway's provisioned user
owns the database it is given, so the expected answer there is *success*.

Measured against PostgreSQL 16.14 with three role shapes:

| Role | `CREATE` on database | `0041` |
|---|---|---|
| superuser | yes | succeeds |
| **owns its database, not a superuser** | yes | **succeeds** — the case this item assumed would fail |
| schema rights only | no | stops with the preflight's second message; after an administrator runs `CREATE EXTENSION pg_trgm` once, `alembic upgrade head` reaches `0043` and the `gin_trgm_ops` index is built |

Both refusal paths were exercised and both produced their intended, actionable message.
`docs/deployment-railway.md` now has the section that did not exist, including the
one-line predicate an operator can run before deploying:

```bash
psql "$DATABASE_URL" -tAc \
  "SELECT has_database_privilege(current_user, current_database(), 'CREATE');"
```

**What this does and does not establish.** It establishes the deciding factor, that both
refusals behave, and that the documented remedy works. It does **not** establish Railway's
own extension allowlist, if it has one — that is what the predicate above answers on a
real deployment, and it costs one `psql` invocation rather than a phase.

`backend/tests/db/test_knowledge_schema.py::test_pg_trgm_is_a_trusted_extension` keeps the
premise from drifting: if a future PostgreSQL un-trusts the extension, the deployment
guide's advice becomes wrong and that test is what says so.

**The item was open for six weeks on an assumption nobody checked.** It is worth naming
that separately from closing it: "Railway usually gives a non-superuser" was true and
irrelevant, and the gap between those two is what kept two waves blocked.
