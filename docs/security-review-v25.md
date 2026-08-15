# Security review — V2.5 (clarification, decomposition and the three human gates)

- Date: 2026-08-14
- Scope: `RQ-02`…`RQ-11a`, ADR 0034, migration `0039`, `agentd` 0.12.0
- Reviewer: to be signed off before the merge proposal
- Method: `.agent/skills/cliora-security-review` — assets, actors, boundaries, entry
  points, then untrusted input traced through validation, authorization and execution

## 0. Why this is one section and not three

`research/02/10` §6 names three triggers for a mandatory review: **a new credential, a
new storage surface, a new execution capability**. This phase hits **none of them**, and
that is a property of the design rather than an accident of scope:

| | V2.3 | V2.4 | **V2.5** |
|---|---|---|---|
| New outward side effect | git push | provider API | **none** |
| New execution capability | secrets in a run's env | verification commands | **none** |
| New credential | `git_*` secrets | `provider_token` | **none** |
| Contract | v1.12.0 | v1.13.0 | **unchanged** (`GATE-RQ-CONTRACT-FROZEN`) |
| daemon node-side half | changed | changed | **unchanged** (`GATE-RQ-TOUCH-LIST`) |

`research/02/10` itself says V2.5 "does not necessarily trigger" a review. It gets one
anyway, because it opens something those three triggers do not describe:

> **§1 — a path by which an agent's output becomes a platform fact.**

A specification an agent drafted looks exactly like one a product owner wrote. A tree of
twenty cards an agent proposed looks exactly like a backlog somebody planned. Nothing
leaves the sandbox; what can go wrong is that a reader believes a person decided
something.

## 1. The one new surface

### 1.1 Authorization: two new write routes whose boundary is the credential

```text
POST /api/cli/runs/spec            task.update   → feature_specs
POST /api/cli/runs/proposal        task.update   → task_proposals
POST /api/cli/runs/patch-proposal  task.update   → document_patch_proposals
GET  /api/cli/runs/requirement     project.view  → read-only
```

**Traced boundary**, and this is the claim to check rather than take:

```text
Bearer cliora_rt_…
  → get_agent_principal            (agent_auth.py; refuses a user token)
  → principal.task_id              (fixed at issue, immutable for the run's life)
  → _run_task()                    (404 unless task.id == principal.task_id)
  → task.card_kind                 (409 unless it matches the route)
  → task.requirement_id            (409 if null)
  → the requirement the write lands on
```

**No step reads the URL.** That is the whole reason these are new routes rather than a
relaxation of `POST /api/requirements/{id}/proposals`: that route takes its requirement
from the path with nothing binding it to the caller, so lowering it to `task.update`
would let **any** run credential in the project write to **any** requirement — including
a prompt-injected implementation run. Recorded in ADR 0034's Alternatives rejected and
asserted by
`test_a_decomposition_run_may_only_propose_for_its_own_requirement`.

| Checked | Result |
|---|---|
| `RUN_TOKEN_SCOPES` still exactly `{project.view, task.update}` | ✅ asserted as a **set**, not by membership (`test_run_credential.py`) |
| The seven V2.1 human routes' `require_action` arguments | ✅ unchanged from the baseline |
| RBAC action count | ✅ 27, unchanged; no 28th added |
| An agent reaching a human route | ✅ **401, not 403** — the two dependencies are disjoint, so it is not recognised rather than refused |
| `AGENT_FORBIDDEN_FIELDS` gains `card_kind` | ✅ and the reason is specific: a clarification run rewriting its own kind would clear the secret refusal for the card's next dispatch |

**One residual, stated rather than closed.** The authorization boundary is still
enrollment (2026-08-12 ruling, permanently). Any enrolled node's runner may claim any
project's clarification card and read that project's requirement text. V2.5 does not
narrow that and does not widen it; requirement text is project data of the same
sensitivity as a card's description, which was already reachable.

### 1.2 The three columns that assert a person decided

`requirements.approved_by`, `task_proposals.decided_by`,
`document_patch_proposals.decided_by`.

Guarded in **two layers**, deliberately, because either alone has a known gap:

| Layer | What it catches | What it misses |
|---|---|---|
| `GATE-RQ-HUMAN-ACTOR` (AST over `backend/app/`) | a second write site, in any function | a write that reaches the column through an ORM path it cannot name |
| `test_no_agent_reachable_route_ever_writes_a_decider` | anything reachable with a run credential, over **every route in `app.routes`** | a write triggered by something other than an HTTP request |

The dynamic layer reads its route list from the application rather than from a literal,
so **a route added by a later phase is covered without anybody remembering this file** —
which is the failure mode most worth designing against here.

Verified: 4 writers, all expected, and the gate fails in **both** directions (a missing
writer means a human gate quietly disappeared).

### 1.3 Provision: two agent-written strings reach a browser

Cliora is a single-origin deployment (ADR 0020), so this is the same shape as ADR 0030
Part B's artifact path, and it is answered the same way rather than re-argued.

| Content | Path | Control |
|---|---|---|
| `document_patch_proposals.diff` | patch review screen | rendered as a **text node**, never `v-html`; no markdown, no syntax highlighter, no parser |
| `feature_specs.sections` | specification review screen | same; non-string values are `JSON.stringify`ed into a `<pre>` |
| `task_proposals.tree` | acceptance tree | fields are interpolated as text; `title`, `delivery` and `risk` reach attributes only as `data-*` values compared against fixed strings |

**No download route for a patch, deliberately.** A `.patch` file someone can fetch would
be `git apply`ed, which relocates the applying step to a terminal where none of this
phase's gates exist. The friction of copying text is the control. `GATE-RQ-NO-PATCH-APPLY`
asserts the service cannot touch a filesystem at all, by AST rather than grep.

`target_path` is validated (no absolute path, no `..`) **even though the platform never
opens the file**: the check exists so a reviewer's screen never renders a string shaped
like an attack, which is a usability control rather than a path control. Stated here so
a later reader does not mistake it for one.

### 1.4 Denial of service and unbounded growth

| Surface | Bound | Why that bound |
|---|---|---|
| specification versions per requirement | 20 | an agent in a loop could otherwise submit one a second |
| tasks per proposal | 40 | a runaway backstop, **not** a granularity judgement — a server cannot make one |
| patch diff | 256 KiB | refused at submission, never truncated at render: a truncated diff looks complete and a person decides on it |
| context pack | 6 KiB, layered | the wire allows 32 KiB, which is not a licence — `run.offer` is a 64 KiB control frame shared with the secrets block |
| questions per run | one unanswered at a time | server-side 409, §1.5 |

### 1.5 The rule that had to move from the client to the server

"One question at a time" was specified in `research/02/07` as a context-pack instruction
plus a CLI limit. **Both are unenforceable**: the agent has a shell, `curl`, and a
readable token at `.cliora/context/run.token`. A client-side rule constrains an agent
that is careless, not one that is in a hurry — and the second is the case the rule
exists for.

It is now `409 QUESTION_ALREADY_PENDING` in `MessageService.post`. The CLI check remains
as a round-trip saver and applies **the same rule**, pinned by one fixture fed to both
sides — two rules that disagree produce "sometimes I can ask", which reads as flakiness
rather than as a bug.

**Behaviour change to declare**: this applies to every run, including implementation runs
that have existed since V2.2. It is in the release note's "changed", not its "added".

## 2. Red line 5

Unchanged and untouched. The phase adds no exit: clarification and decomposition cards
are refused any `delivery` beyond `none` and `artifact` **at dispatch**, before a run
exists.

```text
card_kind ∈ {clarification, decomposition, mockup}
  → delivery ∈ {none, artifact}          409 TASK_KIND_DELIVERY_NOT_ALLOWED
card_kind ∈ {clarification, decomposition}
  → required_secrets == []               409 TASK_KIND_FORBIDS_SECRETS
```

The secret refusal is ordered **before** the project allowlist check. That ordering is a
usability decision with a security consequence: a message saying "that name is not on the
allowlist" would send someone to Project Settings to add a name that must not be used at
all, and they would be refused again on the next attempt.

`GATE-RQ-TOUCH-LIST` asserts `daemon/internal/{runtime,runner,workspace,gitfetch}` are
byte-identical to the baseline. The five hard push constraints are not merely unchanged;
their file was not opened.

## 3. What this phase does **not** claim

1. **The platform cannot tell a good specification from a bad one.** Section keys are
   validated; contents are not. A specification with every section empty is legal, and
   what stops it is the approval gate — which is the reason a human gate exists.
2. **The high-risk term match is a guard rail, not a control** (ADR 0034 §10). An agent
   that wanted to evade it would change a word. It exists for the honest-but-careless
   agent, and it errs toward false positives on purpose: an unnecessary badge costs one
   untick, a missed one puts a payments card into `ready` as low risk.
3. **There is no Security Gate to route stop condition 4 into.**
   `process_definitions` seeds six gates and none is `security`, so a card touching
   secrets, authentication, payments, migrations or infrastructure is marked `risk: high`
   and badged — and nothing refuses it. Adding the gate changes the vocabulary every
   board and every cross-project metric uses, which is larger than this phase.
   Tracked in `plan/22/10-…md` §4.
4. **Requirement text is not classified.** Someone may paste a credential into an intake
   box. It is then project data with `project.view` access, redacted nowhere, and
   included in a context pack. This is the same posture a card description has had since
   V2.1 and is not made worse here — but V2.5 makes the intake box the **first** thing a
   new user sees, so the exposure is more likely to be exercised. **Recommendation**:
   one line of guidance on the intake box before this ships widely.

## 4. Findings

| # | Severity | Finding | Status |
|---|---|---|---|
| 1 | — | No confirmed defect found in the traced paths | — |
| 2 | Low (design question) | §3.4: intake text is unclassified and now more prominent | **Open** — one line of UI guidance recommended |
| 3 | Info | §3.3: stop condition 4 has no gate to land in | **Accepted**, tracked |
| 4 | Info | §1.1 residual: enrollment remains the authorization boundary | **Accepted** (2026-08-12 ruling) |

## 5. Evidence

```bash
scripts/rq/gates.sh                       # 12 checks, all PASS
uv run --project backend pytest tests -q  # includes 28 V2.5 tests
cd daemon && go test ./...                # includes the CLI's same-rule fixture
```

The authorization claims in §1.1 and §1.2 rest on
`backend/tests/db/test_clarification_and_decomposition.py`, groups 2 and 5, and on
`scripts/rq/gate_human_actor.py`.
