# Security review — V2.1: the session credential and the platform's write into a workspace

- Date: 2026-08-09
- Scope: `plan/17` (`TK-06`, `TK-07`), ADR 0028
- Trigger: two of the four conditions in `research/02/10-verification-and-exit.md` §6 —
  **a new credential flow** and **a new write path / storage surface**. The other two
  (a new authorization *input*, a new ability to run a process on a node) are not
  triggered: V2.1 adds no way to start anything on a node, and the agent principal is
  a new caller *kind* rather than a new authorization layer.
- Reviewer: implementation team, with the assertions below as the evidence rather than
  the summary. Every claim in this document has a test named next to it.

V2.0's review recorded *why nothing was triggered*. This one records what was
triggered and what was done about it. It is deliberately in three sections with three
independent sets of boundary tests, rather than one essay about "agent security" —
V2.3 will need the same separation and doing it now sets the shape.

---

## 1. Credential issue and revocation

### What exists

One credential per session, scoped to one project, valid for at most
`CLIORA_SESSION_TOKEN_TTL_H` hours (default 24), revoked the moment the session
reaches a terminal state.

| Property | How | Test |
|---|---|---|
| Stored as `HMAC-SHA256(pepper, value)` | `security/hashing.py`, the same construction enrollment tokens and node secrets already use (ADR 0008) — not a new one | `test_a_session_token_hash_is_unique_and_dies_with_its_session` |
| The plaintext exists once | `SessionTokenService.issue` returns it to the caller that projects it; nothing stores it | `test_the_token_value_never_reaches_the_audit_trail` |
| Scope fixed at issue time | `scopes` is a snapshot column, not a live read of a constant | `test_the_scope_excludes_every_action_that_would_matter` |
| Dies with the session | Revocation is written into the state machine (`_revoke_tokens_then_record_ended`), not into the four routes that can end a session | `test_ending_a_session_revokes_its_credential` |
| Retry never leaves two live credentials | Reissuing first revokes every active token for that session | `test_reissuing_for_projection_retry_leaves_only_one_active_token` |
| Expiry is a real ceiling | Compared in UTC against an aware `expires_at`; equality counts as expired | `test_a_revoked_or_expired_credential_is_refused` |
| Revoked rows have a finite DB lifetime | The retention worker purges only rows with `revoked_at` older than 90 days; live rows are excluded | `test_revoked_session_tokens_have_ninety_day_retention` |

**Why the scope is snapshotted rather than read live.** A credential is a fixed grant.
If verification consulted `SESSION_TOKEN_SCOPES` per request, then editing that
constant — a one-line change nobody would flag as a security event — would silently
re-authorise every token already sitting in a workspace.

### Threat: a copied token

The context pack and the credential land in the user's workspace, so **any local user
who can read that directory can read the token**. This is not fixable: the agent has
to read it, and it runs as the user.

What a copied token can do, in full: read the cards of **one** project, and change
non-decision fields on those cards, for at most 24 hours or until the session ends —
whichever comes first. It cannot approve a review gate, create a card, read or write a
file, touch a terminal, open a session, reach another project, or authenticate as the
person who issued it.

**Accepted, with the containment named**: short ceiling, revocation on session end, a
two-action scope, and a per-project boundary. The alternative — keeping the credential
out of the workspace — would mean the agent could not read it, which is the whole
point of projecting it.

### Threat: a token in a log or a backup

`redact_mapping` (`app/logging.py`) and `FORBIDDEN_METADATA_KEYS` already guard the
structured log and the audit metadata. The audit rows for issue and revoke carry the
token **id**, never the value, and a test reads every audit row after an issue and
asserts the value and even the prefix are absent.

**Residual**: a database backup contains the HMACs. Those are not usable without the
pepper, which lives in the environment — the same posture as enrollment tokens, and
the same consequence: **losing the pepper does not expose credentials, and stealing the
database alone does not either.**

---

## 2. The authentication path

### What exists

Two dependencies that do not overlap:

```text
Authorization: Bearer <JWT>            → get_current_user     → User
Authorization: Bearer cliora_st_…      → get_agent_principal  → AgentPrincipal
```

`get_current_user` refuses the `cliora_st_` prefix **before it can become a `User`**,
and with the same 401 body as any other bad credential. On mutation routes it may do
a bounded token-id lookup solely to attribute the denial audit row; the dependency
still never returns that principal to the route. `get_agent_principal` refuses
anything that is not a session token, and refuses everything when
`CLIORA_PROJECTS_ENABLED` is off.

| Property | Test |
|---|---|
| A session token is refused on **every** user route, reads included | `test_the_two_authentication_paths_are_disjoint` |
| A gate attempt through the human route is 401 and leaves an agent-attributed denial audit | `test_an_agent_can_move_a_card_and_nothing_else` |
| A valid user JWT is refused on the agent surface | same test |
| The agent surface is four routes, on their own prefix | `ROUTE_ACTIONS` in `test_authz.py` (all four map to `None`, with the reason recorded) |
| A card in another project answers **404**, not 403 | `test_a_credential_cannot_reach_another_project` |
| The `PATCH` body cannot set `gates`, an owner, a runner or a secret list | `test_an_agent_may_not_set_a_person_s_fields` |
| An agent's write is audited and timelined as an agent, with no user id | `test_an_agent_write_is_recorded_as_an_agent` |

**Why the paths are separate rather than one path with a scope check.** `require_action`
answers with a *user's whole action set*. A token that resolved into a `User` would
inherit `task.approve` and every terminal action along with it, and the scope list
would become the only thing in the way. A list is one refactor away from being
bypassed; a type that cannot be produced is not.

`AgentPrincipal` carries no `user_id` for the same class of reason: a principal that
had one would eventually be handed to something that records an actor, and the agent
would start signing the name of the person who opened the session.

### Threat: a refactor merges the two paths

This is the realistic failure, not an attacker. The defences are the disjointness test
above (which fails loudly in both directions), the absent `user_id` field (asserted by
`test_an_agent_principal_has_no_user_id`), and `docs/permission-matrix.md` recording
that `task.approve` and `task.update` have identical holders **on purpose**.

### Threat: a 403 used as an oracle

A cross-project card answers 404. A revoked, expired and unknown credential all answer
the same 401. Neither can be used to enumerate.

---

## 3. The write into a workspace

### What exists

The platform writes into `.cliora/{context,process,reference}/` and nowhere else,
through a **second daemon verb** that the user-facing upload path cannot reach — and
which cannot reach the user-facing areas either.

| Property | Where |
|---|---|
| The two writable sets are disjoint and neither overwrites | `daemon/internal/files/store_policy.go` (`VerbStore` vs `VerbProject`) |
| A path outside `.cliora/{context,process,reference}/` is unrepresentable on the wire | `contracts/v1/schemas/messages/context-project.schema.json` pattern, plus invalid fixtures |
| `.cliora/uploads/` and `.cliora/.gitignore` are refused to the projection | policy test |
| Directories are created 0700, files 0600, and `O_EXCL` never replaces | daemon unit tests |
| Every `.cliora/**/*.token` is intrinsically sensitive, regardless of local policy configuration, and search never returns it | `TestProjectedTokenIsDeniedAndHiddenFromReadSurfaces`, `TestProjectedTokenDenialCannotBeDisabledByConfig` |
| Retention touches only closed process versions and expired context/token files inside the three projected subtrees | `TestRetentionLeavesTheUserSFilesAlone`; live workspaces are supplied by `session.Manager.Workspaces` |
| Projection retention is bounded and configurable | defaults: 30 days, sweep on connection and every 6 hours; validation rejects non-positive values |

**Why a new verb rather than relaxing the existing one.** `.cliora/` is closed to the
user-facing write verb today. Opening it would let any holder of `file.upload`
overwrite the context pack — or the credential file. The daemon's `Verb` type exists
precisely so a second verb does not inherit the first one's answers.

### Threat: a poisoned context pack

Someone who can write `.cliora/context/` can feed the agent a false brief. Two things
bound it: only the daemon writes there (on a request that arrived over the node's
authenticated WSS), and everyone else who can write that directory is already the user
whose workspace it is. This is a real capability and is **accepted**: an attacker who
can write a user's workspace can also edit the code the agent is about to read.

### Threat: path traversal through the projection message

The path pattern makes `..` and any prefix outside the three subtrees unrepresentable,
and the daemon re-validates rather than trusting Central (SEC-001, defence in depth).
An in-root symlink at `.cliora` is caught by `Lstat` before any write, the same check
`ensureUploadDir` already performs.

---

## Conclusions

1. **The largest accepted risk is that the credential is readable by anyone who can
   read the workspace.** It is inherent to handing a file to an agent, and it is
   contained by a 24-hour ceiling, revocation on session end, and a scope of two
   actions in one project.
2. **The largest engineering risk is a future refactor merging the two authentication
   paths.** Three tests and one ADR paragraph exist to make that loud.
3. Nothing here changes the workspace write posture for users: ADR 0024/0026 are
   untouched, and the platform still only ever *adds* files — in one directory it owns.
4. **Not triggered, and worth recording**: no new ability to execute anything on a
   node. V2.2 will trigger that, and its review starts from this document's section 3.
