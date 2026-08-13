# ADR 0028 — The V2.1 task layer: gates that refuse, a credential the agent may hold, and the one directory the platform writes into

- Status: accepted
- Date: 2026-08-09
- Amends: nothing. ADR 0027 recorded the project layer and the source-of-truth
  flip; this records the three surfaces V2.1 adds that 0027 deliberately left
  open — how the internalised process refuses, how an agent authenticates, and
  how the platform gets a context pack onto a node. It also **corrects one
  planning assumption**: `research/02/03-…md` said V2.1 touches neither the
  daemon nor the contract, and §4 records why the code says otherwise.
- Related: ADR 0014 (path security — the projection uses the same `workspace.Root`
  containment, with a second verb), ADR 0015 (preview policy — the token file
  joins the sensitive classification), ADR 0016 (RBAC is one table with two
  authorization layers; the agent principal adds a *caller kind*, not a third
  layer), ADR 0021 (`terminal.shell` sits with the session-shaped actions; the
  same reasoning puts `task.*` with them), ADR 0022 (`tunnel_integration.enabled`
  drives the derived state in §3.4), ADR 0024/0026 (write posture — §2 explains
  why a platform-owned destination is a *disjoint* path rather than a relaxation),
  ADR 0027 (the project layer this builds on)
- Requirements: `FR-TASK-001`…`008`
- Contract: **v1.10.0** — one message pair, `context.project` / `context.projected`.
  Every existing message is byte-for-byte unchanged.
- Ships in: Central minor, frontend minor, **`agentd` 0.8.0**, `cliora` CLI 0.1.0
  (the same binary as `agentd`). Migrations `0023` (tables), `0024`
  (`session_tokens`), `0025` (seed).
- Plan: `plan/17/`

## Context

ADR 0027 made the platform database the source of truth for the work itself, and
built the project layer around that. V2.1 is where the work becomes real: epics,
user stories and task cards, a six-lane board a human can drag cards across, and
the Definition of Ready / Review Gates from Monstrare turned from prose into
something the API can refuse.

That flip has a cost 0027 named but did not pay: **with the cards in the database,
an agent with no tool cannot record anything at all.** It cannot even discover
which card it is working on. So V2.1 also has to deliver the smallest possible
tool chain — a context pack projected into the workspace, a credential the agent
may hold, and a CLI that can move a card one lane.

Those two halves have very different risk. The first touches no existing surface.
The second adds a credential, a caller kind and a write path, and it triggers a
security review (`docs/security-review-v21.md`).

## Decision

### 1. The internalised process refuses exactly one thing in V2.1

The six lanes, the seven readiness items and the six review gates are seeded as
one global process definition (`process_definitions`, key `default`). It is not
overridable per project in this phase; `process.manage` arrives in V2.4.

**What actually refuses, and what only warns, is decided here rather than left to
the implementation:**

| Rule | V2.1 | Why |
|---|---|---|
| Moving a card into `ready` or beyond with an unfinished dependency | **409, naming the blocking `card_ref`s** | It is the one rule where the platform holds every fact needed to be certain |
| The seven Definition-of-Ready items | Warning on the response, never a refusal | Enforcing all seven from day one is how a process tool stops being used, and an unused board is a source of truth nobody writes to |
| WIP limits | Lane count turns colour; never a refusal | Monstrare's existing semantics |
| Done Gate's verification and delivery clauses | **Not enforced yet** — V2.4 wires them onto this same code path | There is no verification report to check against until then |

A card may be dragged between any two lanes. A session has a state machine
because it maps onto a real process; a card does not, and a board that refuses to
let someone drag a card backwards only teaches them to track the real state
somewhere else.

**Review gate approval always carries a human.** `gates[key]` stores
`{approved_by, approved_at}` rather than a boolean, so "an agent's output is not
an approval" is a fact in the data rather than a rule in a document. §3 is what
makes it unforgeable.

### 2. The platform writes into `.cliora/`, and that is a *disjoint* path, not a relaxed one

The context pack, the process notes and the session credential are files in the
user's workspace, because `claude` and `codex` read files. They land under
`.cliora/{context,process,reference}/`.

This is a new write path into a workspace, so it has to answer ADR 0024's four
rules. It does, and the shape is deliberately the mirror image of the user-facing
one:

| | User upload (ADR 0026) | Platform projection (this ADR) |
|---|---|---|
| Who initiates | A user holding `file.upload` | The **platform**, after a session starts |
| May write where | Anywhere under the allowed root **except** `.cliora/` | **Only** `.cliora/{context,process,reference}/` |
| Overwrites | Never (`O_EXCL`) | Never (same `O_EXCL`; `FILE_EXISTS` is *success*) |
| Names the destination | The caller | The platform |
| Who cleans it up | Nobody — they are the user's files | **The daemon, after 30 days** |

The invariant in one sentence: **the two writable sets are disjoint, and neither
path ever replaces a byte.** Red line 3 — the console adds files, it does not
edit, move or delete them — is untouched. `.cliora/uploads/` (image drop) and
`.cliora/.gitignore` belong to the *user-facing* path and the projection must not
touch them either; the exclusion runs in both directions.

**This is not a precedent for a third write path.** ADR 0026 said the same about
itself, and the reason holds again: each path pays for what it is allowed to name.
Here the platform names everything and the user names nothing, which is what buys
the mkdir the other path is not allowed to have.

### 3. A session credential that cannot become a user

Each session gets one token, projected to
`.cliora/context/<session_id>.token`. It is stored as an HMAC keyed by the
existing `token_pepper` (ADR 0008's construction, not a new one), it expires with
`CLIORA_SESSION_TOKEN_TTL_H` (default 24), and **it is revoked the moment the
session reaches a terminal state** — written into the state machine, not into the
four routes that can get there.

Its scope is two actions: `project.view` and `task.update`. What it can never
hold is `task.approve`, `project.manage`, any `file.*` and any `terminal.*`.

**Scope is the second line of defence, not the first.** The first is that a
session token never produces a `User`:

```text
Authorization: Bearer <JWT>           → get_current_user     → User
Authorization: Bearer cliora_st_…     → get_agent_principal  → AgentPrincipal
```

`require_action` takes a `User`, so a token that resolved into one would inherit
that person's entire action set — including approval. The two dependencies are
disjoint, each 401s on the other's token, and only four endpoints accept the
agent principal at all. `AgentPrincipal` deliberately carries **no `user_id`**:
a principal with one would eventually be passed to something that records an
actor, and the agent would start impersonating the person who opened the session.

Consequently the audit trail records an agent write as `user_id = NULL` plus
metadata naming the token, and `activity_events` gains an `actor_kind` column —
without it, "an agent did this", "the system did this" and "you lack `audit.view`"
all render as the same blank actor.

### 4. V2.1 does change the contract and the daemon, and the reason is in the code

The upstream plan (`research/02/03-…md`) said this phase would touch neither. Two
facts falsify it, both in `daemon/internal/files/`:

1. `store_policy.go` refuses every write under `.cliora/` for the only existing
   write verb (`platform_owned`). That refusal is correct and must stay: any
   holder of `file.upload` could otherwise overwrite the context pack — or the
   token file.
2. `store.go` requires the destination directory to already exist, and the
   protocol has no mkdir at all.

So the projection needs a **second write verb and a message to carry it**:
contract v1.10.0 adds `context.project` / `context.projected`, and `agentd` 0.8.0
adds `VerbProject` plus a retention loop. The daemon's own `Verb` type exists for
exactly this — its comment says the `.cliora/` rules are per-verb, so that a
second verb cannot silently inherit the first one's answers.

The same reading changes how the CLI ships. It cannot be projected: a Go binary
exceeds the 4 MiB single-file ceiling, `.cliora/` is closed to the user-facing
verb, and the updater extracts exactly one archive member by name. **So `cliora`
*is* `agentd`** — the same binary, dispatched on `argv[0]`, with a symlink placed
at install time. This also settles, three phases early, the "MCP needs a stable
executable path" requirement that `research/02/01` D11 deferred to V2.4.

Consequence: the contract and `agentd` version numbers for V2.2–V2.4 each shift
by one, as do the ADR numbers. `research/02/` has been rewritten accordingly.

### 5. Old daemons stay useful

`node.register` gains an optional `context_projection` boolean, the same shape
`image_upload` and `file_upload` already use. A node that does not send it is
treated as incapable: sessions on it are created and run exactly as before, no
`context.project` is sent, and the console says *"this node's agentd needs 0.8.0
to receive task context"* with a link to the update page — not a 500, and not a
node that quietly disappears from a list.

**A failed projection never fails a session.** It is a second round trip after the
session is already running; the failure is recorded on the timeline and offered a
retry button. Context is an addition, not a precondition.

### 6. Three new stores, three different answers to "who cleans this up"

ADR 0024's W2 question has to be answered per store, and here the answers differ —
which is precisely why they are written down together:

| Store | Who cleans it | When |
|---|---|---|
| `activity_events` (task kinds) | Nobody | Product content; it lives as long as the project (ADR 0027 §7) |
| `.cliora/{context,process,reference}/` | **The daemon** | 30 days. `uploads/` and `.gitignore` are excluded in code |
| `session_tokens` rows | The existing retention loop | 90 days after revocation — the audit trail names a token id and must stay resolvable |

### 7. `card_ref` is an identifier, not a counter

`TASK-12` is allocated from `projects.next_card_seq` with a single
`UPDATE … RETURNING`, which takes the row lock and makes a collision impossible.
Epics, user stories and tasks share one sequence, so **numbers skip**. That is
deliberate: three counters means three places to lock, and the reference's only
jobs are to be readable by a human and — from V2.3 — to name a branch.

`card_ref` is immutable once allocated, for the same reason `projects.slug` is.

### 8. The `ui` review gate disables itself

`tunnel_integration.enabled = false` ⇒ the `ui` gate is disabled when the process
definition is read, and cards are not held against it. It is derived state, not a
switch an administrator has to remember, because the alternative is a card stuck
behind a gate that can never be satisfied — a deadlock, not rigour. Project
Settings states the reason rather than silently omitting the gate.

### 9. Execution settings are declared but inert

`tasks` carries `source`, `delivery`, `repository_id`, `base_branch`,
`target_branch`, `existing_pr_ref` and `required_secrets` from `0023`. **Nothing
reads them in V2.1.** They exist because people will want to state the intent now
and because adding them later would leave every existing card without them; the
behaviour arrives in V2.3/V2.4.

## Consequences

- A card that says `delivery: pull_request` produces no pull request in this
  phase. The UI has to say so — this is a state we know misleads, accepted
  deliberately rather than discovered later.
- The context pack and the token land in the user's workspace, so any local user
  who can read that directory can read the token. This is not fixable: the agent
  has to read it. The containment is a 24-hour ceiling, revocation on session
  end, and a two-action scope.
- Enforcing only `dependsOn` means a card can reach `done` with an empty
  Definition of Ready. V2.4 tightens this on the same code path; until then the
  board reports rather than refuses.
- `agentd` 0.8.0 must be rolled out before a node can receive context. The
  existing staged update mechanism is unchanged and is **not** triggered
  automatically by this phase.

## Alternatives rejected

| Option | Why not |
|---|---|
| Relax the existing write verb so `filesystem.store` can write `.cliora/` | Any holder of `file.upload` could then overwrite the context pack and the **token file**. The `Verb` type exists to stop a second verb inheriting the first one's answers |
| Put the context pack in the workspace root to avoid a new verb | The destination directory must already exist, so only the root is writable — that pollutes the user's repository and falls outside the `.cliora/.gitignore` the platform already writes |
| Have the CLI fetch its own context from Central | The credential is one of the things being projected, so it is circular; and D14 requires `context show` to work with no network at all, which a fetch-then-cache design cannot promise on first use |
| Project the `cliora` binary into `.cliora/bin/` | 4 MiB single-file ceiling, `.cliora/` closed to the user verb, and the updater extracts exactly one member — three independent refusals |
| Resolve a session token into a `User` and reuse the existing dependency | It inherits every action that user holds, including `task.approve`. Scope becomes the only defence, and a single refactor eventually walks past it |
| `count(*) + 1` for `card_ref` | Two browser tabs creating a card at once collide, and the reference goes on to name a branch and a pull request |
| Enforce all seven Definition-of-Ready items from day one | The board stops being used, and an unused board is a source of truth nobody writes to |
| A per-project process definition in V2.1 | Configurability is the easiest thing to over-build with no users; cross-project comparison also needs the fields to match (`research/02/01` D15) |
| Let an administrator turn the `ui` gate off manually | A gate that can never be satisfied is a deadlock; derived state cannot be forgotten |
