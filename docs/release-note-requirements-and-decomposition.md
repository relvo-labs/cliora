# Release note — V2.5: requirement clarification and task decomposition

- Phase: V2.5 (`RQ-`), ADR 0034, PRD §8.16
- Ships: Central (minor), `agentd` **0.12.0**, frontend (minor)
- Contract: **v1.13.0, unchanged — not one byte**
- Flags: `CLIORA_PROJECTS_ENABLED` (data and human forms, from V2.1),
  `CLIORA_AGENT_RUNS_ENABLED` (the agent-driven half)

## What this adds

A vague sentence can now become a set of cards without anybody writing them.

```text
Requirements 分頁丟一句話
  → 派給 Agent 釐清   一次一個問題，答案回在卡片訊息串上
  → 每答完一輪送一版規格草稿
  → 人核准規格        （未解決的問題還在時，API 會拒絕）
  → 派給 Agent 拆解   產出一棵 Epic → Story → Task 的提案樹
  → 人逐張勾選、就地改欄位、拒絕其餘並寫理由
  → 卡片建立，每一張都回溯得到來源需求與提案
```

**The data model and the human forms shipped in V2.1.** This phase points an agent at
the same API — which is the order `version2.md` §17 asked for, and the reason the
refusals it meets are the ones a person already met.

## What it deliberately does not add

**No outward side effect, no execution capability, no credential, no contract change.**
Clarification and decomposition runs use the existing lifecycle, the existing isolated
directory and the existing lease; a run of either kind leaves a remote repository
byte-identical.

The phase's only new risk is semantic: that something an agent wrote reads as something
a person decided. Every gate in it is shaped around that one sentence.

## Changed behaviour (read this one)

**One question at a time now applies to every run, including implementation runs that
have existed since V2.2.** An agent that posts a second question while the first has no
reply gets `409 QUESTION_ALREADY_PENDING`, naming the question still waiting.

Two related sub-questions in one message are fine. What this prevents is five
independent questions at once, which in practice returns three answers and two the agent
cannot tell were skipped.

It is enforced by the **server**, not by the CLI: an agent has a shell and a readable
token file, so a client-side rule constrains carelessness rather than haste.

`POST /api/proposals/{id}/reject` replaces `DELETE /api/proposals/{id}`, which is
deprecated and now also requires a reason. A `DELETE` body is legal HTTP and is stripped
by enough clients that the reason arrived only sometimes — and a silently lost reason is
the defect this replaced.

## New

| Area | What |
|---|---|
| Cards | `card_kind`: `implementation` (default) / `clarification` / `decomposition` / `mockup`. Fixed once the card has been run, and never settable by an agent |
| Specifications | Nine more sections (`user_stories`, `screens`, `verification_plan` and six others), from Monstrare's template. Keys validated, contents not |
| Runs | Two purposes that produce no code, with four dispatch refusals bounding them |
| CLI (0.12.0) | `cliora spec submit`, `cliora spec template` (offline), `cliora proposal submit`, `cliora patch propose`, `cliora requirement show` |
| Documents | Patch proposals: the platform renders a diff and records a decision, and **never applies one** |
| Console | A real specification review screen, a three-level acceptance tree with per-card readiness, and "from requirement N" on every card that came from one |

## Known limitations

Ten, in two groups, and the split is the useful part. The first four are answers to
*why not in this phase*; the last six are answers to *what the platform still cannot
do* — they were true before V2.5 and V2.5 does not touch them.

### The four this phase decided

Each is a decision rather than an omission.

1. **The mockup preview is not built** (`RQ-11b`). With the tunnel integration off,
   everything behaves correctly — the `ui` gate disables itself, Project Settings says
   why, a card whose deliverable is mockup variants is refused at dispatch with a message
   that spells out that ordinary UI cards are unaffected. **With the integration on, a
   `mockup` card is simply an ordinary artifact card**: no interactive preview, no
   variant comparison, no `links.mockupDecision`.
   Deferred for three reasons, the third being that Monstrare's mockup gate requires a
   `design-system.md` the platform has no equivalent of — which time alone does not fix.

2. **Epics and user stories in a proposal are grouping headings only.** Accepting does
   not create them as rows; the created cards carry no `epic_id` or `user_story_id`. The
   tree says so on screen rather than offering a checkbox that does nothing. Tracked.

3. **There is no Security Gate.** `process_definitions` seeds six review gates and none
   is `security`, so stop condition 4 — secrets, authentication, payments, migrations,
   infrastructure — has nowhere to land. Compensated: a proposal card mentioning those
   areas is **refused unless marked high risk**, and the acceptance screen badges it. The
   term match is coarse on purpose and errs toward false positives.

4. **Intake text is unclassified.** Someone may paste a credential into the box, and it
   becomes project data readable with `project.view` and included in a context pack. This
   is the posture a card description has had since V2.1, but the intake box is now the
   first thing a new user meets. One line of UI guidance is recommended before wide
   rollout (`docs/security-review-v25.md` §3.4).

### The six the platform still carries

Confirmed against the code rather than remembered (`research/03/01` §2). They are also
the reason the next two releases exist, so the right-hand column is a pointer and not
an apology. **Four of the six are closed by `v2.0.0-alpha.2`** — noted here so that a
reader of this note is not left believing they are still open.

| # | Gap | Evidence at `alpha.1` | Closed by |
|---:|---|---|---|
| 5 | A card's conversation is paged by **timestamp, not by a monotonic sequence**. Two messages written in the same millisecond can be delivered twice or not at all | `cliora task messages --since <timestamp>`; `task_messages` has no `seq` column | `alpha.2` (`CV-03`) |
| 6 | **A message POST carries no idempotency key.** A retried send is a second identical message | `task_messages` has no `idempotency_key` column | `alpha.2` (`CV-04`) |
| 7 | **A conversation ends when the agent's process does.** There is no continuation model, so the only way to hold one open is to keep polling — which holds a lease and a `max_waiting` slot for up to 24 hours | `ACTIVE_STATUSES` includes `waiting_for_input`; the lease sweep deliberately skips it | `alpha.2` (`CV-05`, `CV-07`) |
| 8 | **An ordinary comment and an answer are the same API call**, distinguished only by a `kind` string, with no "should this resume the run" semantics | `agents.py` changes the run's state only when `kind == "question"` | `alpha.2` (`CV-05`) |
| 9 | **There is no project-scoped knowledge layer.** Every run's context pack is assembled from nothing, and an agent cannot cite an earlier decision | `services/context_projection.py` projects the card and the process, and nothing else | `alpha.3` (`KN-*`) |
| 10 | **Board cards have no single attention projection.** "Whose turn is it" is assembled by each client | `BoardCardDTO` carries `active_run_status`, `waiting_reason` and `blocking_count` side by side, with no precedence between them | `PX-24` |

## Upgrading

```bash
alembic upgrade head        # 0039_requirements_agent_driven
```

Additive only; **no existing row is rewritten**, and `alembic downgrade
0038_runner_features` restores the previous schema byte for byte
(`GATE-RQ-MIGRATION-ROUNDTRIP`).

Specification versions written before this release have `sections = {}` and render with
their five original fields and nine empty sections. **There is no backfill**, because
there is nothing to backfill from — and inventing content for a specification is exactly
what this phase must never do.

Nodes still on `agentd` 0.11.0 keep working: they claim clarification cards, run them and
report normally. Their CLI has no `spec submit`, so an agent calling it gets
`unknown command` and a non-zero exit code — **visible, and in the run log**, not a
silent drop. The context pack tells the agent to fall back to `cliora task say` with the
draft inline.

## Verification

```bash
scripts/rq/gates.sh                                  # 12 checks
uv run --project backend pytest tests -q             # 1727 tests
cd daemon && go test ./...
cd frontend && npx vitest run src                    # 662 tests
```
