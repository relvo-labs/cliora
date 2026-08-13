"""Role-based authorization over stable action keys (PRD §8.1, ADR 0007/0016).

This module owns the **action layer** only: the vocabulary of action keys and
which role holds which. Resource-scope questions ("may this user terminate *this*
session?") live in `app/services/authz.py` — see ADR 0016. Keeping them apart is
what stops a role check from being mistaken for an ownership check.

A user has one role; the role's `permissions.actions` list is the seeded
authorization vocabulary. Checks operate on the loaded User so a disabled
account or a role change takes effect on the next request.

`ROLE_ACTIONS` is the single source of truth (ADR 0016). Three automated
assertions keep the copies from drifting — see
`backend/tests/db/test_permission_matrix.py`:

1. it matches what the seed migrations actually produce in PostgreSQL,
2. it matches the `ACTION_*` constants exported by `frontend/src/api/dto.ts`,
3. every action is enforced somewhere (or is listed in `UNENFORCED_ACTIONS`).
"""

from __future__ import annotations

from app.db.models import User

# Stable action keys (must match the role seed migrations 0002 + 0006 + 0007 + 0008 + 0012 + 0016).
NODE_VIEW = "node.view"
SESSION_CREATE = "session.create"
SESSION_VIEW = "session.view"
TERMINAL_OPERATE = "terminal.operate"
TERMINAL_TAKEOVER = "terminal.takeover"
TERMINAL_SHELL = "terminal.shell"
SESSION_TERMINATE = "session.terminate"
FILE_BROWSE = "file.browse"
FILE_UPLOAD = "file.upload"
ENROLLMENT_MANAGE = "enrollment.manage"
NODE_MANAGE = "node.manage"
AUDIT_VIEW = "audit.view"
TUNNEL_VIEW = "tunnel.view"
TUNNEL_MANAGE = "tunnel.manage"
INTEGRATION_MANAGE = "integration.manage"
# V2.0 project layer (ADR 0027, seed migration 0022).
PROJECT_VIEW = "project.view"
PROJECT_MANAGE = "project.manage"
# V2.1 task layer (ADR 0028, seed migration 0025).
TASK_CREATE = "task.create"
TASK_UPDATE = "task.update"
TASK_APPROVE = "task.approve"
# V2.2 agent runner (ADR 0029, seed migration 0030).
AGENT_VIEW = "agent.view"
AGENT_MANAGE = "agent.manage"
RUN_DISPATCH = "run.dispatch"
RUN_CANCEL = "run.cancel"
# V2.3 secrets and dispatch routing (ADR 0032, seed migration 0034).
SECRET_MANAGE = "secret.manage"

ADMIN = "Admin"
DEVELOPER = "Developer"
VIEWER = "Viewer"

# --- The permission matrix (PRD §8.1). Single source of truth, ADR 0016. ---
#
# Viewer holds the read-only actions: node.view, session.view (read-only attach,
# P2/ADR 0013) and file.browse (read-only browse + preview, ADR 0015). It holds
# no mutation action, so a Viewer's forged create/terminate/takeover/enrollment
# request fails at the action layer before any resource is loaded.
#
# `project.view` joins the read-only set for the same reason `node.view` is in it:
# a Viewer may look at the shape of the fleet, and a project is a name for part of
# that shape. What it must *not* become is an actor feed — the project timeline is
# readable with this action, so `services/activity.py:redact_actors` strips actor
# identity from it unless the caller also holds `audit.view` (ADR 0027 sec 7).
#
# `agent.view` joins it for the same reason again: the fleet's runners are part of the
# shape of the fleet. It is read-only in the strict sense — posting a message on a card
# or attaching an artifact requires `task.update`, not `project.view`, precisely so that
# this phase does not open a Viewer write path (plan/18/06-…md §1).
#
# **What `agent.view` does not bound, and this is a posture rather than an omission:**
# there is no project↔agent binding, so a runner on **any** enrolled node can claim any
# project's card, pull any project's code, and — from V2.3 — receive the secrets that
# card declares. The authorization boundary is `enrollment.manage`, an Admin-only
# action, and it is **permanent**: the 2026-08-12 ruling cancelled `project_agents`
# rather than deferring it (ADR 0032 §0). What narrows the radius is four compensating
# controls, not a table: a card gets only the secrets it declares from the project's
# allowlist, a node may refuse them, every delivery is audited and revocable, and the
# enrollment screen says the consequence out loud. The same sentence appears in
# ADR 0032, on the Agents page and on the enrollment page, because it is the kind of
# design that gets filed as a bug when it is written down only once.
_VIEWER_ACTIONS = frozenset({NODE_VIEW, SESSION_VIEW, FILE_BROWSE, PROJECT_VIEW, AGENT_VIEW})
# `terminal.shell` sits with the other session-mutation actions rather than in the
# Admin set (ADR 0021): a Developer already drives a CLI in their own session. The
# boundary is ownership, not role — `authz.may_open_shell` requires the caller to own
# the session, and nobody may attach to a shell they did not open.
_DEVELOPER_ACTIONS = _VIEWER_ACTIONS | {
    SESSION_CREATE,
    # The task layer's three actions sit with the session-shaped ones: writing down
    # and moving work is day-to-day, in the way that deciding which projects exist is
    # not (ADR 0028).
    #
    # `task.approve` and `task.update` have **deliberately identical holders**, and
    # that is not an oversight waiting to be tidied up. Splitting them separates
    # nothing at the role layer; the entire effect is that a session credential's
    # scope can exclude approval — and an action that does not exist cannot be
    # excluded from a scope (research/02/01 D13, ruling 3). Merging them because "the
    # holders are the same anyway" would silently open the path to an agent approving
    # its own work.
    #
    # Not raised to Admin either: a gate that needs an administrator for every card
    # makes the internalised Review Gates something nobody can afford to use.
    TASK_CREATE,
    TASK_UPDATE,
    TASK_APPROVE,
    # Image drop writes to the node's workspace, so it is deliberately NOT part of
    # `file.browse` — all three roles hold that one, and handing Viewer a write
    # would contradict the read-only viewer the rest of the system promises
    # (ADR 0024 sec 6). It is also not `terminal.operate`: that action means
    # driving a terminal, and reusing it would make "typed something" and "wrote a
    # file" indistinguishable in the audit trail.
    FILE_UPLOAD,
    SESSION_TERMINATE,
    TERMINAL_OPERATE,
    TERMINAL_TAKEOVER,
    TERMINAL_SHELL,
    # Port forwarding sits with the other session-shaped actions (ADR 0022): a Developer
    # already drives sessions on the nodes they work on. Viewer holds neither, because a
    # web application's read-only-ness is not something the platform can promise on the
    # application's behalf — "read-only user" and "can open the preview" do not compose.
    TUNNEL_VIEW,
    TUNNEL_MANAGE,
    # Dispatching a card to an agent is deliberately **not** covered by `task.update`.
    # Editing a field changes a record; queueing work spends compute — it clones a
    # repository onto a machine and starts a process there (ADR 0029, ADR 0031). The
    # audit trail has to be able to tell those apart, and a filter over one merged
    # action could not.
    RUN_DISPATCH,
    # Cancelling sits with dispatching rather than with `project.manage`: whoever may
    # start the work may stop it, and needing an administrator to stop a runaway run
    # is how a stop button stops being used.
    RUN_CANCEL,
}
# `integration.manage` is Admin-only for the same reason as enrollment and node management:
# it covers supplying the organisation's third-party credential and deciding that traffic
# may leave for a third party at all. A Developer may open tunnels; they may not decide
# whose service and whose account (ADR 0022).
_ADMIN_ACTIONS = _DEVELOPER_ACTIONS | {
    ENROLLMENT_MANAGE,
    NODE_MANAGE,
    AUDIT_VIEW,
    INTEGRATION_MANAGE,
    # `project.manage` sits with enrollment and node management, not with the
    # session-shaped Developer actions: deciding which projects exist, and which
    # machines and directories they cover, is an organisation-level call rather than
    # day-to-day work (ADR 0027 sec 4). From V2.3 it decides one thing more — which
    # secret **names** a project's cards may ask for — while the values themselves are
    # `secret.manage`, a separate action, because holding a credential and shaping a
    # project are different powers.
    PROJECT_MANAGE,
    # Admin from the first day. `agent.manage` covers enabling a runner and its
    # concurrency — the disposition of compute — and **nothing else**. It notably does
    # not cover editing a runner's tags: those are declared by that node's `agentd`
    # config, and a platform-side edit would create a second source of truth that
    # `runner.register` overwrites on the next reconnect (ADR 0029 amendment B5).
    # (This comment used to say the action would grow to cover binding a runner to a
    # project. The 2026-08-12 ruling cancelled that table — see ADR 0032 §0.)
    AGENT_MANAGE,
    # The values behind those names. Admin-only for the same reason as enrollment: a
    # credential the platform holds on a user's behalf, hands to a machine on demand
    # and can revoke is an organisation-level asset. It also guards repository
    # registration from V2.3, because a repository row stopped being "where the code
    # is" and became "which credential fetches it" (ADR 0032).
    SECRET_MANAGE,
}

ROLE_ACTIONS: dict[str, frozenset[str]] = {
    ADMIN: _ADMIN_ACTIONS,
    DEVELOPER: _DEVELOPER_ACTIONS,
    VIEWER: _VIEWER_ACTIONS,
}

ALL_ACTIONS: frozenset[str] = frozenset().union(*ROLE_ACTIONS.values())

# Actions that exist in the vocabulary but are not yet enforced by any endpoint
# or WebSocket handler. Every entry is a permission that does not really exist
# yet, so the list must be emptied by the ticket that wires the action up —
# `test_every_action_is_enforced_somewhere` fails in *both* directions, so a
# stale entry is as loud as a missing one.
#
# Now empty. `audit.view` was seeded to Admin in migration 0002 (P1) and checked
# by nothing until P4-05 landed `GET /api/audit`; P4-03 is what made that
# visible. Every action in the vocabulary is now enforced somewhere.
# Actions whose vocabulary and seed data exist but which no route enforces yet. The list is
# not an exemption: `test_every_action_is_enforced_somewhere` fails both when an action is
# missing from it *and* when a listed action starts being enforced, so an entry here has to
# be removed by the change that adds the endpoint.
#
# Empty again. `tunnel.view`, `tunnel.manage` and `integration.manage` were listed here for
# exactly as long as their vocabulary existed without an enforcement point: they arrived with
# the port-forwarding data layer (PG-04) and were removed by the services and routes that
# check them (PG-07/PG-08/PG-09) — `app/services/authz.py` for the resource layer,
# `app/api/http/{tunnels,integrations}.py` for the action guard.
UNENFORCED_ACTIONS: frozenset[str] = frozenset()


def role_actions(user: User) -> set[str]:
    permissions = user.role.permissions or {}
    actions = permissions.get("actions", [])
    return set(actions) if isinstance(actions, list) else set()


def has_action(user: User, action: str) -> bool:
    return action in role_actions(user)
