# Security review — SR-3, `v2.0.0-beta.1` (V2-P1 Collaborative Project Workspace)

- Scope: everything under `backend/app/services/work/`, the **eleven** HTTP routes it adds,
  migration `0043`, and the frontend modules that consume them (`modules/work`,
  `modules/task`, `modules/mywork`, `modules/project`).
- Reviewed against: `plan/26/10-verification-and-exit.md` §2 (eight items), ADR 0040,
  ADR 0042.
- Date: 2026-08-23
- **Sign-off: NOT SIGNED.** §6 says what is outstanding. This document is the evidence,
  not the approval; a review the implementer signs is a review of nothing.

## 1. What changed about the trust boundary

**Nothing was added to it.** No outbound connection, no inbound channel, no credential, no
RBAC action, no protocol change. That is a short list for a security section, so here is
why it is empty rather than unwritten:

- `httpx` is still reachable from one module (`services/providers.py`);
- there is still exactly one WebSocket ticket in the browser client, and it is the
  terminal's. Freshness is a twenty-second poll of one endpoint, paused when the tab is
  hidden — a browser push channel was considered and moved to `beta.2` precisely because it
  is a new authenticated channel with a new subscription-authorization problem;
- twenty-seven RBAC actions, unchanged. Eleven new routes, none of them with a new action;
- the run token's scope is unchanged at two actions.

**What did change is the read surface.** Eleven new routes, and **two of them are
cross-project** (`/api/me/work-items`, `/api/me/attention-counts`). Before this phase no
query returned a card from a project the caller had not named in the path.

**One change narrows what an agent may do.** Three fields were **added** to
`AGENT_FORBIDDEN_FIELDS`: an agent may not set `is_blocked`, `blocking_reason` or `rank` on
its own card. The first two would clear the dependency gate — the one rule ADR 0028 says
the process refuses. The third would make `runner.poll`'s first-in-first-out advisory,
which is what "the platform does not schedule" means in code.

## 2. The eight items

| # | Item | Verdict | Evidence |
|---:|---|---|---|
| 1 | counts and items use the same predicate | **PASS** | `work_items()` and `work_counts()` take **the same `ProjectScope` instance and the same `CompiledFilter` instance** — the signatures require them, so a shared helper called separately is not possible. Where SQL stops, both call the same `filters.matches()`. `test_counts_and_items_describe_the_same_set` compares the two endpoints on one fixture |
| 2 | filter and group cannot bypass authorization | **PASS** | Fifteen fields, eight operators, one compilation path per pair in one dict; no `text()`, no f-string reaching a query, no concatenation (`GATE-PX-NO-DYNAMIC-SQL`, one printed exemption: a fixed `INSERT … SELECT` with bind parameters). Every `Task` select in the package takes its project predicate from a `ProjectScope` (`GATE-PX-ONE-PROJECT-SCOPE`, one printed exemption). Six negative tests, each asserting the refusal **names the field or the operator** |
| 3 | My Work does not leak across projects | **QUALIFIED** — §3 | `test_a_viewer_without_project_view_sees_no_work_items_and_zero_counts` plus `GATE-PX-ONE-PROJECT-SCOPE`. **Read §3 before signing: the verdict is not a pass and it is not a fail** |
| 4 | bulk update authorises per card | **PASS** | A loop through `TaskService.update_task`, asserted by `GATE-PX-BULK-USES-UPDATE` (calls the service, contains no `UPDATE Task` of its own, no raw SQL). One transaction; a batch containing an unreachable card is refused whole and nothing is written (`test_bulk_update_is_all_or_nothing`). Also verified that bulk cannot reach a field a single `PATCH` cannot |
| 5 | a view does not change task permissions | **PASS** | `test_visible_fields_shape_the_response_and_nothing_else`: the same card set and the same counts, a narrower payload. A hidden field is **absent from the response**, not null — `"owner_name": null` would mean both "no owner" and "this view hides owners". Somebody else's personal view is a 403 (`VIEW_NOT_OWNED`) rather than a 404, and it is already absent from their listing, so the 403 discloses nothing |
| 6 | simplification did not hide safety information | **PASS** | The Drawer's execution block is collapsed by default and **expands itself, naming the row to look at**, in four situations: no eligible runner → required labels; assigned runner offline → the assignment; a blocked card declaring a secret → the secret names; a declared delivery with no repository → repository/branch. One test each, plus one asserting it stays silent when nothing is wrong and one asserting it does **not** re-derive the reason from other fields |
| 7 | human approval shows the actor and the time | **PASS** | `tasks.gates` still stores `{approved_by, approved_at}` and no code in this phase writes it; the gate endpoint is untouched. Verified by inspection of the diff, not by a new test — a new test here would be testing V2.1 |
| 8 | an agent still cannot approve, merge or deploy | **PASS** | Run-token scope asserted as a **set**, unchanged at `{project.view, task.update}`. The run credential reaches **none** of seven representative new routes (`test_a_run_credential_reaches_none_of_the_new_endpoints`) — `get_agent_principal` never resolves into a `User`, so these routes cannot accept it at all. Three fields added to the deny list, one test each; `blocking_message` deliberately **not** added, and there is a test saying so |
| 9 | **named sign-off** | **OUTSTANDING** | §6 |

## 3. Item 3 in full, because its verdict is neither a pass nor a fail

The upstream condition reads: *cards from a project the caller has no rights to appear in
neither the items nor the counts.*

**On this deployment that condition cannot fail**, and saying so is more useful than a
green tick.

RBAC is three global roles. `_VIEWER_ACTIONS` contains `project.view`, `services/authz.py`
has no project-scope function, and there is no `project_members` table. So there are two
states: hold `project.view` and see every project, or hold nothing and see none. A test
written to the letter of the condition uses a role without `project.view` and asserts a
403 — which measures `require_action` and says nothing whatever about the read model's
query boundary.

**A frictionless isolation test is worse than no test**: it persuades the next reader that
the thing is guarded.

So the phase does three things instead:

1. the predicate that decides "which projects" lives in **one function**
   (`services/work/scope.py`), and the *decision* behind it lives in `authz.py`, where
   `test_authorization_logic_is_confined_to_two_modules` already requires every
   authorization decision to be;
2. `GATE-PX-ONE-PROJECT-SCOPE` fails the build if any `Task` select in the read-model
   package takes its project predicate from anywhere else, and it **prints the one
   exemption it honoured** — an exemption nobody can see is how a rule quietly stops being
   one;
3. the inference test is kept and **named honestly** —
   `test_a_viewer_without_project_view_sees_no_work_items_and_zero_counts` — so the name
   says which lever it pulls.

The scope object also refuses to be trivially satisfiable: an empty scope compiles to an
explicit `false()`, never to an absent clause, because an absent clause widens the query to
everything, which is the exact inversion of what an empty scope means. And a
single-project endpoint still takes its predicate from a `ProjectScope` rather than from
the path parameter, because *which project do you want* and *which may you have* are
different questions.

### What is therefore not proved

> **With per-project membership, counts do not leak the existence of a card in a project
> the caller cannot see.**

Recorded in `plan/26/11` §1 as an open measurement. **The signature in §6 signs this
sentence as well as the eight rows in §2.**

One consequence follows for whoever adds membership: `RANK_NEIGHBOR_STALE`'s cross-project
case is a **409** today, because both cards are visible to every caller who can see
either. **The day membership lands, that line becomes a 404** — a 409 would confirm the
existence of a card in a project the caller cannot see. The comment saying so is in
`plan/26/05` §6 and in the service.

## 4. What SR-3's scope contains that it should not have

Recorded here rather than in a footnote, because it was a decision and not an accident.

`v2.0.0-alpha.3` was never tagged: its own SR-2 has no signature and its Railway
`pg_trgm` check has not run. **`beta.1` was built on top of it anyway**, by explicit human
decision on 2026-08-23 (`plan/26/12` §2.7).

**So SR-3's surface includes `PX-62` — Drawer UI reading the knowledge layer SR-2 has not
signed off.** If SR-2 asks for changes to `KN-11`, that UI changes with it, on a surface
this review has already covered.

The repayment plan is that SR-2 closes before this release ships, and that this paragraph
is read at that point rather than found afterwards.

## 5. What this review did not cover

Stated, because a review's silence reads as a pass.

| Not covered | Why, and where it is tracked |
|---|---|
| ~~**J1, J4 and J15**~~ — **all three have now run** against a real daemon (32/32, 13/13, 8/8; `artifacts/px/local/journeys/*.json`) | Struck through rather than deleted, because the reason first written here was **false**: "no Go toolchain on the machine". Go was on the machine and `run-stack.sh` already put it on `PATH`. A reviewer should know that this document once excused a gap with a fact that was not one — it is the kind of error a reviewer is the last defence against. `plan/26/12` §6 records it |
| ~~A **flag-off deployment**~~ — **run**, against a Central started with `CLIORA_PROJECTS_ENABLED=false`. The rail is the pre-V2 picture and `/api/projects`, `/api/me/work-items` and `/api/me/attention-counts` all answer **404 rather than 403** — a 403 would confirm the route exists, and "this deployment has no project layer" is not an authorization answer (ADR 0028). The two `/api/me/*` routes are new this phase, so that was their first such test. `artifacts/px/local/journeys/j16-02-flag-off-rail.png` | |
| ~~A **complete run lifecycle** on a 0.14.1 node~~ — **covered by J1**: dispatch → claim → three continuations → spec → proposal → implementation → verification → done, on a 0.14.1 node whose code `GATE-PX-NO-DAEMON-DIFF` proves did not change (including `daemon/VERSION`). Exit condition 33 | |
| **Multi-worker correctness of attention levels 5 and 6** | They are answered from an in-process registry, so under more than one uvicorn worker they are per process. Central runs one worker today, which is the only reason this is currently harmless. `plan/26/11` §2 |
| A **penetration test** of the filter language | Out of scope by construction: the language is an allowlist with one compilation path per `(field, op)` pair and no string assembly, and `GATE-PX-NO-DYNAMIC-SQL` is what makes that checkable rather than claimed |

## 5a. What the three journeys found, since this review previously excused them

Worth a section rather than a footnote: the reason for running them is exactly this.

| Journey | Found |
|---|---|
| J4 | `derive_attention` level 1 read the **run status** instead of `waiting_for_actor`. An agent that asked a question and then *exited* — the supported and recommended shape (`cliora task ask` tells it to) — produced **no attention at all**: the person it was waiting for could not see that it was waiting. Fifteen in-process tests of that level passed, because they all staged the other shape |
| J1 | `CreateTaskRequest` declared neither `card_kind` nor `requirement_id` and does not forbid extras, so the console's "send this requirement to an agent" button had been posting both **since V2.5** and getting back an ordinary implementation card with no requirement. Nothing errored; the requirement flow simply never started. Every in-process test of that flow inserted its card directly into the database |
| J1 | The console had **no control for ticking a readiness item at all** — so PX-30's "fill it in" had nowhere to go. Found by writing the journey's Ready transition |

None of the three is a boundary this review covers, and none changes a verdict in §2.
They are here because "we could not run it" was the sentence that hid them, and a
reviewer reading §5 needs to know what that sentence cost.

## 6. Sign-off

**Not signed.** Two things are outstanding and neither is discretionary:

1. **A named reviewer who did not write this code.** Everything they would read is in §1–§5
   and in `artifacts/px/local/evidence.log`.
2. **An explicit acceptance of the unproved sentence in §3.** It is a separate line below
   because it is a separate act: rows 1–8 of §2 say "we checked this"; that sentence says
   "we know this is not checkable here, and we are shipping anyway".

`plan/23/10` §9.4 records SR-1 being left unsigned for a comparable reason, and `plan/24`
closing it. `plan/25` §8.1 records the same for SR-2, still open. The shape applies again:
this document is the evidence, and the signature is a separate act by a separate person.

| Role | Name | Date | Signature |
|---|---|---|---|
| Reviewer — must not be an author of V2-P1 | | | |
| Accepting §3's unproved sentence | | | |

### If the reviewer wants to re-derive rather than read

```bash
CLIORA_DATABASE_URL=postgresql+asyncpg://…  scripts/px/evidence.sh
```

Eleven gates, every static check, both unit suites, the database suite, traceability, both
published catalogues, four measurements, the rollback drill and **six journeys** — in one
run. The three daemon journeys are read from the JSON they wrote rather than re-run (each
needs a stack of its own); a **missing** file is a FAIL naming the command, never a silent
omission. The four items in §2 with a named test can each be run alone:

```bash
cd backend && CLIORA_TEST_DATABASE_URL=… uv run --project . pytest \
  tests/db/test_work_api.py tests/db/test_work_compatibility.py \
  tests/db/test_attention_consistency.py -q
uv run --project backend python scripts/px/gate_work_invariants.py   # items 1, 2, 4
cd frontend && npm run test:unit -- --run src/modules/task           # item 6
```
