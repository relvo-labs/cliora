# ADR 0027 — The V2 project layer: internalised process, the platform DB as source of truth, and the withdrawal of the "no git automation, no task routing" red line

- Status: accepted
- Date: 2026-08-08
- Amends: the scope sentence in
  `.agent/skills/cliora-project-context/SKILL.md` — "Do not introduce … Git
  automation, task routing, or multi-agent orchestration without a requirements
  change". **This ADR is that requirements change**, and it withdraws two of the
  four V1 red lines. §6 records exactly what replaces them. Nothing else in that
  file changes; in particular the workspace write posture (ADR 0024/0026) is
  **not** touched by V2.
- Related: ADR 0011 (node removal is a *soft* delete — §5 depends on this),
  ADR 0013 (session lifecycle; `terminal_sessions` gains one nullable column and
  no state-machine change), ADR 0014 (path security; §4 is its application to a
  second stored-path structure), ADR 0016 (RBAC is one table, and authorization
  has two layers), ADR 0022 (`CLIORA_SECRET_ENCRYPTION_KEY`; V2.3's secret master
  key is deliberately **separate**, §7), ADR 0024/0026 (write posture —
  unchanged, and §6.3 explains why V2 must not be read as a precedent)
- Requirements: `FR-PROJECT-001`…`005`, `SCOPE-014` (new; §6.4)
- Contract: v1.9.0 — **unchanged**. V2.0 adds no protocol message.
- Ships in: Central minor, frontend minor. **`agentd` is not touched** (0.7.0).
  Migrations `0021` (tables) and `0022` (seed).
- Plan: `plan/16/`

## Context

Cliora V1 is a remote console for CLI agents across VMs. V2 makes it a control
plane for AI development: a user states a task on a board, an agent claims it,
works in an isolated directory, and delivers the result back where a human has to
look at it before it takes effect.

That is a large change, and it was decided in four rulings on 2026-08-08
(`research/02/00-upgrade-roadmap.md`). This ADR records the four decisions that
V2.0 — the project foundation — rests on, plus the scope change that makes the
rest of V2 legal to build at all.

**V2.0 itself is deliberately small.** It adds three tables, two RBAC actions,
seven endpoints and two screens. It touches no daemon code, no protocol message,
no file path, and no terminal byte. The reason is recorded in `plan/16/00-…md`
D0: every later V2 stage moves a security posture, and each of those needs a
known-good baseline that already contains the V2 data model to regress against.

## Decision

### 1. Monstrare is internalised as platform capability, not copied as files (D2)

A workspace does **not** need `ai/`, `tools/kanban/` or `.claude/skills/` to be a
project Cliora can manage. The process definitions become platform data.

Whether something can be internalised is decided by **who reads it**, and that
boundary is not a preference — it is fixed by how Claude Code and Codex load
context:

| Monstrare asset | Read by | Internalised as |
|---|---|---|
| Six-lane board vocabulary, DoR, DoD, review gates, workflow stages | human / platform | Platform lanes, task fields, and **gates that actually refuse** |
| Card schema (`risk`, `readiness`, `gates`, `links`, `dependsOn`) | human / platform | Columns on `tasks` |
| Epic → User Story → Task | human / platform | Platform entities with CRUD |
| `ai/templates/*` | human / agent | Form schemas and generators |
| `tools/kanban/` | human | Replaced wholesale by the platform Board |
| `ai/context/*.md` | agent | Platform stores content, **projects it as files at run time** |
| **`.claude/skills/`, `.claude/agents/`, `AGENTS.md`** | **agent (loaded from disk)** | **Hard boundary — cannot be internalised** |

The last row is the load-bearing one. `claude` and `codex` read files in the
working directory; a skill that exists only in PostgreSQL is invisible to them.
**The platform cannot use an API to make an agent *know* a rule** — it can only
put a file in the agent's working directory.

The bridge is a platform-owned `.cliora/` directory, projected at session start
(V2.1) or run start (V2.2), never `.claude/` and never the user's `~`. Process
files go under a version-numbered subdirectory so the existing `O_EXCL` write
posture (ADR 0026) is satisfied without ever replacing a file.

There is a real trade-off: a skill under `.cliora/process/` is **not**
auto-loaded, where one under `.claude/skills/` would be. We accept it, because
**when the platform can actually refuse, the part that has to persuade the agent
shrinks.** Monstrare could only persuade — it had files and no execution engine.
Cliora has an API, so a Done Gate can answer 409. The rule moves from "please
comply" to "non-compliance does not persist", and the skill's role drops from
enforcement to explanation.

Process wording and structure derive from Monstrare (MIT). Seed data records the
attribution; this is not presented as original work.

### 2. The platform database is the source of truth for task data (D1)

The user's repository holds code. The platform holds tasks, conversations, plans,
verification and run records. An agent's isolated working directory is temporary.

The cost of this is transferred, not removed, and it is recorded so nobody
re-discovers it as a surprise:

- An agent can only record work **through a tool** (`cliora` CLI, V2.1) — it
  cannot write a card file. This makes the CLI a *precondition* of V2.1, not a
  convenience.
- When Central is unreachable, the agent cannot record anything. The decision
  there is **fail directly, no offline queue**, and the message must say
  "the session can keep working" — see `research/02/01` D14.
- Task history has to be built rather than inherited from git: `activity_events`
  plus versioned rows.

What it removes is larger: no `filesystem.replace`, no `expected_sha256`, no path
allowlist, no index service, no "data as of" semantics. **Dragging a card is one
`UPDATE`.** Red line 3 (§6.3) is therefore not touched at all.

### 3. Two independent feature flags, and a permanently nullable association (D12)

`CLIORA_PROJECTS_ENABLED` gates the project layer and the board (V2.0/V2.1).
`CLIORA_AGENT_RUNS_ENABLED` will gate autonomous execution (V2.2+). They are
separate on purpose: a board and an unattended agent differ by an order of
magnitude in risk, and an organisation may reasonably want the first and not the
second. With both off the system behaves exactly as V1.

`terminal_sessions.project_id` is nullable **and always will be**. An ad-hoc
session — one belonging to no project — is part of the product, not a
transitional state. The platform never infers a project from the workspace path:
one path may be bound to several projects, so there is no unique answer, and
"is this ad-hoc" must remain the caller's statement rather than ours.

The flag is enforced **inside the handler (404), not by conditional mounting.**
`backend/tests/test_authz.py::test_every_mounted_route_is_in_the_matrix` reads
`app.routes`, which is fixed at import time; conditional mounting would make
`make check` pass or fail according to the environment it ran in, which is not a
gate. 404 rather than 403 because the layer genuinely does not exist in that
deployment, and a deployment that never enabled it should not advertise a roadmap.

The browser learns the flag from a new `features: list[str]` on `UserResponse`.
It is deliberately shaped like `permissions` (a string array) so V2.2 adds one
string rather than a new response shape. **`features` is not a permission**: one
answers "does this deployment have the capability", the other "may this person";
the UI ANDs them and the server checks both independently.

### 4. New RBAC actions (D13)

| Action | Viewer | Developer | Admin |
|---|:--:|:--:|:--:|
| `project.view` | ✅ | ✅ | ✅ |
| `project.manage` | ❌ | ❌ | ✅ |

`project.manage` sits with `enrollment.manage` and `node.manage`: deciding which
projects exist and which machines and directories they cover is an
organisation-level call. From V2.3 the meaning of a binding widens again (binding
a runner to a project authorises it to draw that project's secrets), so this
action must not start life in Developer hands. Viewer holds only the view action,
preserving the read-only role.

Later stages add `task.create`, `task.update`, `task.approve`, `agent.*`,
`run.*`, `secret.manage` and `process.manage`. One clarification is recorded now,
because it will otherwise be lost:

> **`task.approve` and `task.update` deliberately have the *same* holders**
> (Developer + Admin). Splitting them separates nothing at the role layer. The
> split exists so that "an agent credential cannot approve" is expressible as a
> token scope — **an action that does not exist cannot be excluded from a scope.**

Without that sentence someone will later propose merging the two "since the
holders are identical", and that merge silently opens the path to an agent
approving its own work.

Every new action is wired to an enforcement point **in the same commit** that
adds it to `ROLE_ACTIONS`: `test_every_action_is_enforced_somewhere` is a text
scan and fails in both directions, and `UNENFORCED_ACTIONS` stays empty.

### 5. A workspace binding is a shortcut, never an authorization

`project_workspaces` stores `(project_id, node_id, path)`. Binding calls
`sessions.authorize_workspace()`; **every subsequent use calls it again.** Roots
get disabled and directories get deleted, so a path that was legal when bound may
not be now. This is the same rule and the same wording as `WorkspaceFavorite`,
which is the first instance of this shape in the codebase. Two implementations of
one prefix rule would eventually disagree, and the day they disagree is a
security event rather than a bug.

Node removal is a **soft delete** (ADR 0011), so `ON DELETE CASCADE` on
`project_workspaces.node_id` is a safety net that does not fire on the normal
path. The service filters `nodes.deleted_at IS NULL` instead, exactly as
`services/favorites.py` does. A consequence worth stating: re-enabling a node
that was removed by mistake brings its bindings back.

### 6. Red lines: what is withdrawn, and what replaces it

V1 had four red lines. Two are withdrawn here. **Withdrawing a guard rail
obliges us to name its replacement**, so each is answered in turn.

#### 6.1 SEC-002 (the caller names no command) — partially withdrawn, V2.3, agent-run path only

Preserved unchanged: argv is still assembled by the daemon from an allowlist;
`StartOptions` still accepts no command string; the interactive session path is
untouched. Withdrawn: an agent run needs environment variables. Three constraints
replace the withdrawn clause, and the invariant becomes one sentence:

> **No request payload can name a command, or carry the value of a secret.**

Values come only from the platform secret store, names only from a per-project
allowlist, and values never reach a log, event, error or screen (the runner
redacts before the log leaves the node).

A related clarification, because `research/02/01` D10 contradicted itself and the
contradiction would otherwise be re-litigated in V2.4: what is **refused** is *an
API through which a caller names a command*. What is **allowed** is *the daemon
running the verification command declared on the task card, inside the run
directory*. The command comes from the card, the card lives in the platform
database, and the daemon decides execution. That is consistent with the invariant
above. There is still no "run an arbitrary command on an arbitrary node" API.

#### 6.2 ADR 0014 (path security) — unchanged, but its scope is now explicit

It governs the *user's* allowed roots. An agent run's isolated directory is
**not** inside an allowed root and must not be: the daemon owns it, it is created
per run and destroyed after, and it has its own quota and cleanup rules. The two
must not interconnect — an agent run cannot read or write the user's allowed
roots, and the user's file browser cannot reach a run directory.

#### 6.3 ADR 0024/0026 (writes only ever add) — completely unchanged

**V2 adds no write path to any allowed root.** V2.0 performs no file access at
all. An agent may of course read and write freely inside its own sandbox — that
is a sandbox, not the user's workspace — and this ADR states the distinction
explicitly so that nobody later cites V2 as a precedent for "the write posture
has been relaxed". It has not.

#### 6.4 "No git automation or task routing" — withdrawn, and this is `SCOPE-014`

This is the substance of the third ruling. Four constraints replace it:

1. **Branch namespace is enforced**: an agent may only push
   `cliora/<card_ref>-<run_seq>`, hard-coded in the daemon, not a setting.
2. **Never onto a shared branch**: base, target and protected branches are
   refused even if the card says otherwise.
3. **Never auto-merge.** A PR is reviewed and merged by a person.
4. **Dispatch is pull-based**: agents claim work. The platform does no automatic
   assignment, no scheduling optimisation, no load balancing. What was withdrawn
   is "a task may be claimed by an agent", **not** "the platform decides who does
   what". A card's "assigned agent" is a filter in the agent's own poll query,
   never a push.

The first three have **no code until V2.3**, three stages from now. A constraint
written only in an ADR is, three stages later, only a paragraph. So the four are
also registered as **`SCOPE-014`**, whose criteria each take a `guards_scope`
link to a real gate (the daemon's git argv assembly tests, its four push-refusal
tests, the assertion that no auto-merge code path exists, and the route-matrix
assertion that Central exposes no push endpoint). When `SCOPE-014` goes `active`
at the end of V2.4, `make traceability` enforces it.

Scope that remains **out**: automatic assignment, cross-agent collaboration,
agents dispatching to each other, auto-deploy, auto-approval of risky changes, a
Web IDE, and a visual workflow designer.

### 7. Storage: who cleans it up

ADR 0024's W2 asks of every new store: *who cleans this, and when.* Three answers,
and they are deliberately different:

| Store | What it is | Cleaned by |
|---|---|---|
| `activity_events` | **product content** — what happened on this project | Nobody. It lives as long as the project. Archiving does not remove history |
| `run_logs` (V2.2) | **diagnostics** | A retention period |
| `task_artifacts` (V2.2) | **deliverables** | Nothing; they follow the card |

Confusing the first two is the easiest mistake in V2, so it is written here rather
than left to the stage that introduces them.

`activity_events` is visible to `project.view`, which **all three roles hold** —
wider than `audit_logs`, which needs `audit.view`. Two consequences:

1. The same forbidden-key list that guards audit metadata guards the activity
   payload. Constraints on a wider surface can only be tighter, never looser.
2. **Actor identity is redacted without `audit.view`**, exactly as
   `services/dashboard.py::project_for` already does for the dashboard's recent
   activity: knowing *that* a node was removed is operational context, knowing
   *who* removed it is the audit trail (`FR-AUTH-002`). Without this, V2.0 would
   quietly reopen a channel P4 deliberately closed, in a place nobody would think
   to look.

V2.3's secret master key (`CLIORA_SECRET_MASTER_KEY`) is **separate** from ADR
0022's `CLIORA_SECRET_ENCRYPTION_KEY`, same pattern but independent: the two are
rotated on different occasions, and sharing one would tie them together.

## Consequences

- V1 behaviour is preserved exactly while `CLIORA_PROJECTS_ENABLED` is false, and
  that claim is executable: an OpenAPI diff limited to new paths and optional
  fields, a column-by-column schema comparison, a per-role navigation dump, and
  the full V1 regression suite (`plan/16/06-…md` §3).
- **Every holder of `project.view` sees every project**, matching how `node.view`
  already works. With no `project_members` table, two teams sharing one Cliora
  see each other's project names, descriptions, bound node names and paths. This
  is a real disclosure and is accepted for now; project-level membership is a new
  table plus one authorization layer that **would not change any column or
  endpoint shape decided here**, so building it now would only be paying early.
- **A project's `owner_name` is visible to every role, and that is a deliberate
  narrow exception to the redaction above.** It discloses the same fact the
  timeline's `project.created` actor would — who made this — so it is worth naming
  rather than leaving to be discovered. It is kept because ownership is an attribute
  of the resource rather than an entry in a trail: a Viewer who is told "ask an
  Admin to create one" has to be able to see which Admin. The distinction that
  matters is scope. One durable attribute answers "whose project is this"; an
  unredacted timeline would answer "who did every single thing here, and when",
  which is the audit trail restated.
- A project can be archived but never deleted. `activity_events` is history and
  `terminal_sessions.project_id` points at it; deleting would either orphan rows
  or erase something that really happened.
- Interactive sessions are unchanged in every respect. They remain the path for
  when a person wants to do the work themselves, and V2 does not deprecate them.

## Alternatives rejected

| Alternative | Why not |
|---|---|
| Copy Monstrare's files (`ai/`, `tools/kanban/`, `.claude/skills/`) into the user's repository | Pollutes a repository we do not own; colliding with an existing `CLAUDE.md` would require replacing it, which the ADR 0024/0026 write posture forbids. And it is unnecessary: the platform has an API and can *refuse*, so the rules do not need to persuade |
| Write process files into the node's `~/.claude/` | Outside every allowed root, and global to the node — no isolation between projects on one machine |
| Keep task data in repository files, with the DB as a projection | After internalisation there are no card files left to be the writer of record. It would also turn dragging a card into a file overwrite (`filesystem.replace` + `expected_sha256` + a path allowlist) — precisely the gap red line 3 declines to open |
| Implement the feature flag by mounting the router conditionally | `test_every_mounted_route_is_in_the_matrix` reads the import-time `app.routes`; the suite's result would depend on the environment it ran in |
| Add `GET /api/features` for the browser to read the flag | One more path, one more startup round-trip, and the rail must render before it returns — so it would flicker. It would also need a named exemption from "every new path answers 404 when the flag is off" |
| A `VITE_PROJECTS_ENABLED` build-time variable | Two sources of truth; flipping the flag would require rebuilding the frontend while a backend restart takes effect immediately, and the UI would disagree with the server in between |
| Carry the flag in `permissions` | Seed migrations run unconditionally, so an Admin holds `project.manage` even where the flag is off. `permissions` structurally cannot express it |
| Build `project_members` in V2.0 | See Consequences: it changes nothing decided here, so it can be added when a second team actually needs it |
| Give the project timeline the same actor fields for everyone | `project.view` is held by all three roles; it would undo `dashboard.project_for` |
| Let the platform run verification commands on any node | That needs a general "execute a command on a node" path. Even from an allowlist, the allowlist is user-writable, so it amounts to arbitrary execution — which SEC-002 exists to make impossible. §6.1 states the narrow thing that *is* allowed |
| Auto-assign a session to a project by looking up its workspace | One path may be bound to several projects, so there is no unique answer; and it would make "is this ad-hoc" the platform's judgement rather than the user's |
