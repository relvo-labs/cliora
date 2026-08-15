# ADR 0034 — Two kinds of run that produce no code, the fields an agent may write, and the three gates that only a person passes

- Status: **proposed** (2026-08-14) — waiting on gate two, which is a person's
  approval. Until it is accepted, `RQ-02` onward may not touch `backend/`,
  `frontend/` or `daemon/` (`plan/22/00-…md` §3). A document that marks itself
  accepted would make that gate meaningless.
- Date: 2026-08-14
- Amends: ADR 0028 (**amendment A**, the card's kind), ADR 0029 (**amendment D**,
  two run purposes that never modify a repository).
- Related: ADR 0022 (the tunnel's scope declaration — **deliberately not amended
  here**, §8), ADR 0027 (the rule that decides JSONB versus a table — this document
  applies it twice), ADR 0030 (artifacts are deliverables), ADR 0031 (the isolated
  run directory; both new run kinds use it unchanged), ADR 0032 (secrets — this
  document adds one narrowing: a clarification or decomposition run carries none),
  ADR 0033 (five delivery modes — decomposition *chooses* among them and adds no
  sixth).
- Requirements: `FR-SPEC-002`…`-008`. **`FR-SPEC-001` is deliberately absent**: the
  data model and the manual forms were delivered in V2.1 as `FR-TASK-005`, and a
  second ID over the same acceptance criteria would make the coverage report count
  them twice (§9).
- Contract: **v1.13.0, unchanged — not one byte.** This line is in the heading
  because it is the promise this phase is most likely to break by accident, and
  `GATE-RQ-CONTRACT-FROZEN` is what stops that.
- Ships in: Central (minor), `agentd` **0.12.0** (three CLI subcommands, no wire
  change), frontend (minor).

## Context

By the end of V2.4 the platform could take a card that a person had written, run it
unattended, deliver the result in one of five shapes, and decide on evidence whether
it was done. One question it still could not answer:

**Where does the card come from?**

Someone had to write it — objective, scope, non-goals, acceptance criteria, the
seven readiness items, the execution settings. A card is roughly a page of
considered prose, and the person best placed to write it is usually the person least
able to: they know what they want, not what the codebase makes cheap.

Monstrare answers this with three skills (`spec-interrogation`, `project-kickoff`,
`implementation-plan`) and two governance columns (`待釐清`, `待任務卡`). V2.1
internalised the *data* for both — `requirements`, `feature_specs`,
`task_proposals`, and the human forms over them — because `version2.md` §17 asked
for that order explicitly: build the structures and the human flow first, then point
an agent at the same API.

This phase is the second half of that sentence.

### What makes this phase different from the six before it

Every prior V2 phase opened a surface: a process on someone's machine, a credential
delivered to it, a branch pushed to a remote, a call to somebody else's API. **This
one opens none.**

|  | V2.0–V2.4 | V2.5 |
|---|---|---|
| New outward side effect | yes | **none** |
| New execution capability | yes | **none** |
| New credential | yes | **none** |
| Contract | v1.10 → v1.13 | **unchanged** |
| The daemon's node-side half | changed every phase | **unchanged** (CLI only) |

So the risk is not that the platform does something it should not. **The risk is
semantic: that something an agent wrote gets read as something a person decided.**
A specification an agent drafted, approved by nobody, looks exactly like one a
product owner wrote. A tree of twenty cards an agent proposed, accepted by nobody,
looks exactly like a backlog.

Every decision below is shaped by that one risk.

## Decision

### §1 — Clarification uses the channel that already exists

An agent interrogating a requirement needs to ask a person a question and wait.
**That path was built in V2.2 and is unchanged here**: `cliora task ask` posts a
`question` on the card, the run enters `waiting_for_input`, the lease keeps renewing
but the execution timeout stops counting, the board shows "waiting for your reply",
the person answers in the card's thread, and the agent sees it on its next pull
(D24).

**No second message channel.** Two threads split immediately: the user does not know
where to answer, the agent does not know which to read, and an audit has to look in
two places. This is listed under Alternatives rejected because it is the first idea
everybody has.

One thing is added: **the platform now refuses a second question while the first is
unanswered** (§4).

### §2 — What an agent may write, as a property of the schema

D28 says "an agent's output is a proposal, not a fact". That sentence becomes
checkable only if it names columns:

| An agent may write | Only a person may write |
|---|---|
| `feature_specs` (a whole row, `authored_by_kind='runner'`) | `requirements.status='approved'`, `approved_by`, `approved_at` |
| `task_proposals` (a whole row, `status` always `'pending'`) | `task_proposals.status ∈ {accepted, partially_accepted, rejected}`, `decided_by`, `decided_at` |
| `document_patch_proposals` (a whole row, `status='pending'`) | `document_patch_proposals.status`, `decided_by`, `decided_at` |
| `task_messages` (`author_kind='agent'`) | — |
| `tasks`: `EDITABLE_FIELDS` minus `AGENT_FORBIDDEN_FIELDS` | `gates`, `verification_commands`, **`card_kind`** |

The right-hand column is guarded the same way V2.4 guarded
`tasks.verification_commands`, and **not by an `if`**: those endpoints require
`task.approve`, `RUN_TOKEN_SCOPES` is `{project.view, task.update}`, and
`get_agent_principal` and `get_current_user` are two dependencies that 401 on each
other's token (`agent_auth.py`). An agent does not fail the check; it never reaches
one.

`GATE-RQ-HUMAN-ACTOR` asserts the left-hand claim in two layers: an AST pass over
`backend/app/` collecting every assignment to those three "who decided" columns, and
a test that walks **every route in `app.routes`** with an agent principal and asserts
all three stay NULL. The second layer is what makes a route added next phase fail
loudly instead of silently.

### §3 — Two new run purposes, and the four refusals that bound them

|  | clarification | decomposition |
|---|---|---|
| `source` | `repo` (default) or `none` | `repo` or `none` |
| `delivery` | **`none` or `artifact` only** | **`none` or `artifact` only** |
| `required_secrets` | **must be empty** | **must be empty** |
| produces | one or more `feature_specs` rows + the thread | one `task_proposals` row |
| effect on the repository | none | none |

All four are refused **at dispatch**, not at delivery: a run refused after doing its
work has already spent the work. This follows D17b, which the phase before last used
for the same reason.

**The secret rule is a refusal, not advice.** Clarification does not need a
credential to read code and ask questions; a card that declares one is a
misconfiguration, and the fix is to clear the field rather than to widen the
project's allowlist — which is why the message says so.

This does **not** widen what a run can do. Both kinds use the same lifecycle, the
same lease, the same log and artifact paths, the same isolated directory. What
changes is the context pack and those four refusals.

V2.4's honesty rule (`FR-DELIVERY-002`) applies unchanged: a clarification run that
ran `npm install` to read the code leaves a dirty working directory, and
`git status --porcelain` will say so. **That is correct behaviour, not a false
positive** — exit condition 8 relies on it.

### §4 — One question at a time, enforced by the server

The context pack says it. The CLI checks it. **Neither is the gate**: an agent has a
shell, `curl`, and a readable token file at `.cliora/context/run.token`. A rule that
only the client enforces constrains an agent that is careless, not one that is in a
hurry — and the second is the case this rule exists for.

`POST /api/cli/runs/messages` refuses `kind='question'` with `409
QUESTION_ALREADY_PENDING` while the run has a question with no later message from a
user on the same card.

Three judgements inside that sentence, each deliberate:

- **the answer is scoped to the card, not the run** — a person replying does not know
  which run is current, and should not have to;
- **any user message counts as an answer**, not only one marked `kind='answer'` —
  requiring a particular kind would leave the agent waiting for something that never
  arrives;
- **a system message does not count** — otherwise the 24-hour timeout notice would
  itself unblock questioning.

The refusal names the pending question and offers a way forward ("combine them into
one, or wait"), because *combining two related sub-questions into one message is
allowed*. What this rule prevents is five independent questions at once, which in
practice returns three answers and two the agent cannot tell were skipped.

**This applies to every run, including the implementation runs that have existed
since V2.2.** That is a behaviour change and belongs in the release note as one.

### §5 — A card has a kind, and it is not a tag

`tasks.card_kind ∈ {implementation, clarification, decomposition, mockup}`, default
`implementation`, **immutable once any run has existed for that card**.

It exists because three refusals need a server-side answer to "what kind of card is
this", and three plausible ways to derive one all fail:

| derived from | why it fails |
|---|---|
| a convention in `required_labels` | tags took on dispatch meaning in V2.3 (D18). One field would then decide both *which machine* and *what this is*, and tags are free text — **a typo would silently downgrade a clarification card to an ordinary one**, which is exactly what the secret refusal must catch |
| `requirement_id IS NOT NULL` | the implementation cards created by accepting a proposal carry it too |
| `delivery ∈ {none, artifact}` | an ordinary "write an investigation report" card is `artifact`; and `delivery` is decomposition's *output*, so deriving kind from it ties two concepts together permanently |

**`card_kind` takes no part in dispatch matching.** That is what tags are for. This
sentence is here because the next reader will reasonably wonder whether
clarification cards should go to particular runners.

It is in `AGENT_FORBIDDEN_FIELDS`: a clarification run that could rewrite its own
card to `implementation` would have bypassed the secret refusal for the next
dispatch.

`links.mockupDecision` is reserved here for the deferred mockup work (§8) so that
two spellings do not appear in two places later. Nothing writes it in this phase.

### §6 — The three human gates

| Gate | Entry condition | Action | Who |
|---|---|---|---|
| Specification approval | every open question has an `answer` **or** a `resolved_as`, and never both | `requirements.status → approved` | `task.approve` |
| Proposal acceptance | the requirement is approved | accept all / accept some / edit then create / reject with a reason | `task.approve` |
| UI variant selection | `card_kind='mockup'` and the tunnel integration is enabled | the decision is recorded in `links.mockupDecision` | `task.approve` |

The first two were delivered in V2.1 and refuse in the service layer, which is why
V2.5 can point an agent at the same routes without weakening anything. Three things
change:

1. **rejecting a proposal now requires a reason** — `POST /api/proposals/{id}/reject`
   with a non-empty note. A rejection with no reason produces a row that is
   indistinguishable from no row three months later, and the reason is the only
   accumulating learning signal on this path: it goes into the next decomposition's
   context pack as a negative example;
2. **"edit then create"** — the fourth decision V2.1 did not implement — arrives as
   an `overrides` map on acceptance, restricted to already-selected items and to
   fields that are not `readiness`. Letting a person tick `readiness` would turn
   "a card missing readiness lands in `backlog`" into a rule that disappears when
   inconvenient; to complete it, create the card and edit it, where the edit is
   audited;
3. **`depends_on` is translated** into `task_dependencies` on acceptance. A
   dependency pointing at an item the person did not select is **not** created, is
   reported, and costs that card its `dependencies_known` item — so it lands in
   `backlog`. Silently dropping it would leave a card asserting that its
   dependencies are known while the database holds none.

The third gate is not built in this phase (§8).

### §7 — A specification has the sections the decomposition needs

`feature_specs` had five columns. Monstrare's specification template has twelve
sections, and **three of the missing ones are load-bearing**: *user stories* (which
`project-kickoff` step 4 names as the decomposition's input), *screens* (the
upstream of the `ui` gate), and *verification plan* (the upstream of acceptance
criteria and verification commands).

They arrive as one `sections JSONB` column with **nine closed keys**, not as nine
text columns — ADR 0027's rule: read and written with the row, no independent query.
The keys are validated; **the contents are not**. A specification with every section
empty is legal, and what stops it is the approval gate, which is the point of having
a human gate at all.

`open_questions` is unaffected and stays the *only* place an unresolved question
lives. It is tempting to let questions appear inside `sections` as well; that would
make the approval gate's input ambiguous, which is the whole reason the column is
first-class.

### §8 — Not built here: the UI mockup gate's second half

The gate has three parts and V2.1 built one: the `ui` gate **derives its own
disabled state** from whether the tunnel integration is on, because a gate nobody can
ever satisfy is a deadlock rather than rigour (D31).

This phase completes the *integration-off* behaviour — a card whose deliverable is
mockup variants is refused at dispatch with a message that says plain ordinary UI
cards are unaffected, and the Settings screen states why the gate is off — and
**does not build the preview**.

Three reasons, and the third is the one that cannot be solved with time:

1. it is the only thing in this phase that would open an outward surface, taking the
   security review from one section to two;
2. nothing in the phase's goal needs it — a vague sentence reaching a card never
   passes through a mockup;
3. **Monstrare's mockup gate depends on a document the platform has no equivalent
   of.** `ui-mockup-gate.md` opens by requiring `ai/context/design-system.md` and
   insists variants be assembled from already-decided tokens and components. Without
   that, a platform mockup gate degrades into "look at three arbitrary pictures and
   pick one" — which resembles the Monstrare gate without being it.

ADR 0022 is therefore **not** amended. An amendment saying "the tunnel now also
serves mockups", written while no mockup preview exists, is a stale promise — and
`GATE-RQ-NO-STALE-PROMISE` exists for exactly that.

### §9 — The internalisation ledger

Monstrare's `kanban.md` defines twelve governance columns. This is where each one
lives in the platform, and it is the only place the question "did V2 actually
internalise Monstrare" can be answered in full:

| Monstrare column | Platform | Phase |
|---|---|---|
| Inbox | `requirements.status='intake'` | V2.1 |
| **Needs clarification** | `'clarifying'` + a run in `waiting_for_input` | **V2.5** |
| Needs product approval | `'specified'` → approve | V2.1 |
| Needs UI mockup | `tasks.gates.ui` (auto-disabled without the integration) | V2.1 / preview deferred |
| Needs architecture plan | `tasks.gates.architecture` | V2.1 |
| **Needs task cards** | `task_proposals.status='pending'` | **V2.5** |
| AI ready | `tasks.stage='ready'` + the readiness items | V2.1 |
| Agent working | `implementing` + `task_runs` | V2.2 |
| Needs verification | `verify` + `verification_reports` | V2.4 |
| Needs review | `tasks.gates.*` | V2.1 |
| Needs human acceptance | the Done Gate's six conditions | V2.4 |
| Done | `done` | V2.1 |

**Four things are not internalised, and saying so is part of the ledger:**

| Not internalised | Why not |
|---|---|
| the **Security Gate** (`review-gates.md`) | `process_definitions` seeds six gates and none is `security`, so stop condition 4 (secrets, auth, payments, migrations, infrastructure) has no gate to land in. Adding one changes the vocabulary every board and every cross-project metric is expressed in — bigger than this phase. Compensated instead: a proposal card hitting those terms is forced to `risk: high`, the question stays in `open_questions`, and the acceptance screen badges it |
| **`design-system.md`** | §8 |
| the **conditional Definition of Ready** (8 extra items for UI work, 6 for backend, 4 for high risk) | the platform's `readiness` is a flat list of seven. The cheapest fix is a per-`track` supplement in the *context pack*, not a data model change |
| **Epic 0 "project setup"** (`project-kickoff` step 2) | it assumes a brand-new project, and a requirement here is filed against a project that already exists |

Content internalised verbatim — the five stop conditions
(`ai/process/context-protocol.md`), the splitting rules
(`ai/skills/implementation-plan.md`), the five card sizes (`ai/process/workflow.md`
Phase 5) and the specification sections (`ai/templates/feature-spec.md`) — is
Monstrare's, MIT, and attributed where it is used, following migration `0026`'s
`source: 'monstrare'`.

### §10 — Coarse on purpose: the high-risk term match

A proposal item whose title, objective or scope contains one of a fixed list of terms
(secrets, auth, payments, migration, infrastructure, and their Chinese equivalents)
is refused unless `risk` is `high`.

**This is a guard rail, not a control.** An agent that wanted to evade it would
change a word. It exists for the honest-but-careless agent, and the direction of its
inaccuracy is chosen: it will over-report (a card about deleting old authentication
*documentation* gets badged) and the cost of that is one badge a person unticks,
while the cost of under-reporting is a card touching payments entering `ready` as
`low`. The costs are not symmetric, so the match errs toward noise.

Stating this in the ADR is not modesty. A security review reading the code would
otherwise be entitled to treat it as a control.

## Consequences

**A specification can now be written by something that cannot approve it, and the
distinction is a column.** `authored_by_kind` was added in V2.1 for a reader that
did not exist yet; from this phase it is what the review screen shows and what the
audit distinguishes.

**Two new routes exist whose resource boundary comes from the credential, not the
URL.** `POST /api/cli/runs/{spec,proposal}` derive their requirement through
`principal.task_id → tasks.requirement_id`. This is the sixth and seventh route of
that shape and the pattern is now load-bearing; the alternative — relaxing the
existing human routes to `task.update` — would have let any run credential write to
any requirement in the project, including a prompt-injected implementation run.

**The board's message thread gained a refusal.** Existing implementation runs that
asked several questions at once will now get a 409 on the second. This is the one
backwards-incompatible behaviour in the phase.

**`feature_specs` rows written before this phase have `sections = {}`.** They render
with five fields and nine empty sections. No backfill: there is nothing to backfill
from, and inventing content for a specification is precisely what the phase must
never do.

**A decomposition proposes `delivery` for every card it produces.** One acceptance
can create six cards that will each open a pull request. That multiplies the exposure
of an open question from V2.4 (`plan/21/09` §6.3: whether "the platform never merges"
should be rewritten as "the *platform* never merges" now that an agent may open a
pull request itself). This phase does not settle it; it makes the number visible — the
acceptance screen counts PR-producing cards on their own line — and records that the
ruling should happen before the first large decomposition.

**The platform still cannot tell a good specification from a bad one.** Every quality
judgement in this path is a person's: approving the spec, accepting the tree,
rejecting with a reason. The metrics that matter are therefore about people
(`plan/22/10-…md`), and a short median time from approval to acceptance is a warning
sign rather than an efficiency.

## Alternatives rejected

**A separate clarification chat interface.** Two channels split instantly: the user
does not know where to answer, the agent does not know which to read, an audit has to
look in both. The board thread was designed for a running agent's question and turned
out to fit the whole flow — which is evidence the shape was right, not a coincidence
to build over.

**Pushing questions to the user over WebSocket.** That is terminal relay semantics,
and D24 rejected it once already: interrupting a running CLI mixes the two execution
paths.

**Granting `task.create` to run credentials.** It would open
`POST /api/projects/{id}/tasks` at the same time — an agent creating real cards,
bypassing the Definition of Ready and every human gate. `agent_auth.py` already
records D28 as the reason that action is excluded.

**Relaxing `POST /api/requirements/{id}/proposals` to `task.update`.** Its
`requirement_id` comes from the URL with nothing binding it to the caller.

**Deriving the card's kind from tags, `requirement_id` or `delivery`.** §5.

**Nine text columns instead of one `sections` JSONB.** Each new Monstrare section
would become a migration, and the sections have no independent query. ADR 0027's
rule decides this the same way it decided `task_proposals.tree`.

**Having the platform summarise the conversation into a draft when a clarification
times out.** That is the platform writing the specification. It would need something
that turns Q&A into objective/scope/AC, and the only such thing available is another
run — an automatically dispatched run is the last thing this phase should grow. The
context pack asks the agent to submit a draft after every answered question instead,
and the exit condition checks `feature_specs` is non-empty rather than checking the
thread, which was never at risk.

**Validating the granularity of a decomposition server-side.** "Is this card too
big" has no form a server can judge; a guessed rule (word count? number of acceptance
criteria?) would reject correct cards and admit wrong ones. The convergence point is
the acceptance screen's count, and a person seeing "38 cards, 22 of which open a pull
request" stops.

**Building the mockup preview in this phase.** §8.

**Extracting a shared `Proposal` base for `task_proposals` and
`document_patch_proposals`.** They look alike and are not: accepting the first
creates cards, with partial selection, overrides, readiness checks and dependency
translation; accepting the second creates nothing at all. A shared base would make
the second carry the first's complexity for no use.

**Offering a "download as .patch" button for a PRD patch proposal.** Someone would
`git apply` it, which relocates the applying step to a terminal where none of this
document's gates exist. The friction of copying text is deliberate.
